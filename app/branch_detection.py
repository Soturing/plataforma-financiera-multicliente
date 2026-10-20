import json
import re
import unicodedata
from collections import defaultdict
from typing import Any
from uuid import UUID

from psycopg import Connection


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.upper())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", plain).split())


def detect_branch(conn: Connection, text: str) -> dict[str, Any] | None:
    """Detect an explicit recipient using RFC, legal name or configured aliases."""
    plain_text = normalize_text(text)
    compact_text = plain_text.replace(" ", "")
    candidates = []
    branches = conn.execute(
        """
        SELECT id, clave, nombre, restaurante, razon_social, rfc, aliases
        FROM catalog.sucursales WHERE activa AND clave <> 'POR-ASIGNAR'
        """
    ).fetchall()
    for branch in branches:
        score = 0
        matches = []
        rfc = normalize_text(branch.get("rfc") or "").replace(" ", "")
        if rfc and rfc in compact_text:
            score += 100
            matches.append({"tipo": "rfc", "valor": branch["rfc"]})
        reason = normalize_text(branch.get("razon_social") or "")
        if reason and reason in plain_text:
            score += 80
            matches.append({"tipo": "razon_social", "valor": branch["razon_social"]})
        for alias in branch.get("aliases") or []:
            normalized_alias = normalize_text(alias)
            if normalized_alias and re.search(
                rf"(?<![A-Z0-9]){re.escape(normalized_alias)}(?![A-Z0-9])", plain_text
            ):
                alias_score = min(50, 15 + len(normalized_alias))
                score += alias_score
                matches.append({"tipo": "alias", "valor": alias})
        if score:
            candidates.append((score, branch, matches))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    score, branch, matches = candidates[0]
    return {
        "id": branch["id"],
        "clave": branch["clave"],
        "nombre": branch["nombre"],
        "restaurante": branch["restaurante"],
        "confianza": min(1, score / 100),
        "nivel": "alta",
        "metodo": "receptor",
        "coincidencias": matches,
        "productos": [],
        "puntajes": [],
    }


def _matched_products(conn: Connection, text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    products = conn.execute(
        """
        SELECT id, clave, nombre, aliases
        FROM catalog.productos_consumo
        WHERE activo
        ORDER BY length(nombre) DESC, nombre
        """
    ).fetchall()
    occurrences = []
    for product in products:
        for alias in product.get("aliases") or []:
            normalized_alias = normalize_text(alias)
            if not normalized_alias:
                continue
            for match in re.finditer(
                rf"(?<![A-Z0-9]){re.escape(normalized_alias)}(?![A-Z0-9])", normalized
            ):
                occurrences.append((
                    -(match.end() - match.start()), match.start(), match.end(), product, alias
                ))
    occurrences.sort(key=lambda item: (item[0], item[1]))
    used_spans: list[tuple[int, int]] = []
    used_products: set[UUID] = set()
    matches = []
    for _, start, end, product, alias in occurrences:
        if product["id"] in used_products:
            continue
        if any(start < used_end and end > used_start for used_start, used_end in used_spans):
            continue
        used_spans.append((start, end))
        used_products.add(product["id"])
        matches.append({
            "id": product["id"], "clave": product["clave"],
            "nombre": product["nombre"], "alias": alias,
        })
    return matches


def infer_branch_by_consumption(
    conn: Connection, text: str, provider_id: UUID | None = None
) -> dict[str, Any] | None:
    """Score branches from distinct products, leaving shared products with low weights."""
    products = _matched_products(conn, text)
    if not products:
        return None
    product_ids = [item["id"] for item in products]
    if provider_id:
        provider_filter = "AND (r.proveedor_id IS NULL OR r.proveedor_id = %s)"
        params: tuple[Any, ...] = (product_ids, provider_id)
    else:
        provider_filter = "AND r.proveedor_id IS NULL"
        params = (product_ids,)
    rules = conn.execute(
        f"""
        SELECT DISTINCT ON (r.producto_id, r.sucursal_id)
               r.producto_id, r.peso, r.proveedor_id,
               s.id AS sucursal_id, s.clave, s.nombre, s.restaurante
        FROM catalog.reglas_consumo_sucursal r
        JOIN catalog.sucursales s ON s.id = r.sucursal_id AND s.activa
        WHERE r.activa AND r.producto_id = ANY(%s) {provider_filter}
        ORDER BY r.producto_id, r.sucursal_id, (r.proveedor_id IS NOT NULL) DESC, r.version DESC
        """,  # nosec B608
        # Motivo: filtro armado con literales del propio código; los valores van como parámetros
        params,
    ).fetchall()
    if not rules:
        return None

    product_by_id = {item["id"]: item for item in products}
    scores: dict[UUID, int] = defaultdict(int)
    branch_data: dict[UUID, dict[str, Any]] = {}
    contributions: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for rule in rules:
        branch_id = rule["sucursal_id"]
        product = product_by_id[rule["producto_id"]]
        scores[branch_id] += rule["peso"]
        branch_data[branch_id] = {
            "id": branch_id, "clave": rule["clave"], "nombre": rule["nombre"],
            "restaurante": rule["restaurante"],
        }
        contributions[branch_id].append({
            "tipo": "producto", "clave": product["clave"],
            "valor": product["nombre"], "alias": product["alias"], "peso": rule["peso"],
        })

    ranked = sorted(scores.items(), key=lambda item: (-item[1], branch_data[item[0]]["clave"]))
    top_id, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    tied = len(ranked) > 1 and top_score == second_score
    top_positive = [item for item in contributions[top_id] if item["peso"] > 0]
    distinct = len(top_positive)
    margin = top_score - second_score
    if not tied and top_score >= 60 and distinct >= 2 and margin >= 25:
        level = "alta"
        confidence = min(0.98, 0.72 + margin / 300 + distinct * 0.04)
    elif not tied and top_score >= 40 and margin >= 15:
        level = "media"
        confidence = min(0.79, 0.48 + margin / 250 + distinct * 0.03)
    else:
        level = "baja"
        confidence = min(0.49, max(0.15, top_score / 160))

    score_rows = []
    for branch_id, score in ranked:
        score_rows.append({
            "sucursal_clave": branch_data[branch_id]["clave"],
            "restaurante": branch_data[branch_id]["restaurante"],
            "puntaje": score,
            "productos": [item["valor"] for item in contributions[branch_id]],
        })
    suggestion = None if tied else branch_data[top_id]
    return {
        **(suggestion or {"id": None, "clave": None, "nombre": None, "restaurante": None}),
        "confianza": round(confidence, 4),
        "nivel": level,
        "metodo": "consumo",
        "coincidencias": top_positive if suggestion else [],
        "productos": [
            {key: value for key, value in product.items() if key != "id"} for product in products
        ],
        "puntajes": score_rows,
    }


def _save_inference(
    conn: Connection,
    *,
    invoice_id: UUID,
    ocr_result_id: UUID | None,
    provider_id: UUID | None,
    result: dict[str, Any],
    applied: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO audit.inferencias_sucursal (
            factura_id, ocr_resultado_id, proveedor_id, metodo,
            sucursal_sugerida_id, confianza, nivel, puntajes, evidencias, aplicada
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
        ON CONFLICT (factura_id, ocr_resultado_id, metodo) DO UPDATE SET
            proveedor_id = EXCLUDED.proveedor_id,
            sucursal_sugerida_id = EXCLUDED.sucursal_sugerida_id,
            confianza = EXCLUDED.confianza, nivel = EXCLUDED.nivel,
            puntajes = EXCLUDED.puntajes, evidencias = EXCLUDED.evidencias,
            aplicada = EXCLUDED.aplicada, creada_en = now()
        """,
        (
            invoice_id, ocr_result_id, provider_id, result["metodo"], result.get("id"),
            result["confianza"], result["nivel"],
            json.dumps(result.get("puntajes") or [], default=str),
            json.dumps({
                "coincidencias": result.get("coincidencias") or [],
                "productos": result.get("productos") or [],
            }, default=str),
            applied,
        ),
    )


def apply_detected_branch(
    conn: Connection,
    invoice_id: UUID,
    text: str,
    *,
    provider_id: UUID | None = None,
    ocr_result_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Apply explicit identity, or a high-confidence consumption suggestion for CEDIS."""
    detected = detect_branch(conn, text)
    if detected:
        applied = True
    else:
        detected = infer_branch_by_consumption(conn, text, provider_id)
        if not detected:
            return None
        current = conn.execute(
            """
            SELECT s.clave FROM core.facturas f
            JOIN catalog.sucursales s ON s.id = f.sucursal_id
            WHERE f.id = %s
            """,
            (invoice_id,),
        ).fetchone()
        applied = bool(
            detected.get("id") and detected["nivel"] == "alta"
            and current and current["clave"] == "POR-ASIGNAR"
        )

    evidence = {
        key: value for key, value in detected.items() if key != "id"
    }
    evidence["aplicada"] = applied
    if applied:
        conn.execute(
            """
            UPDATE core.facturas SET sucursal_id = %s,
                sucursal_origen = %s,
                sucursal_deteccion = %s::jsonb, actualizada_en = now()
            WHERE id = %s
            """,
            (
                detected["id"],
                "reconocimiento_automatico" if detected["metodo"] == "receptor" else "inferencia_consumo",
                json.dumps(evidence, default=str), invoice_id,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE core.facturas SET sucursal_deteccion = %s::jsonb, actualizada_en = now()
            WHERE id = %s
            """,
            (json.dumps(evidence, default=str), invoice_id),
        )
    _save_inference(
        conn, invoice_id=invoice_id, ocr_result_id=ocr_result_id,
        provider_id=provider_id, result=detected, applied=applied,
    )
    return {**detected, "aplicada": applied}
