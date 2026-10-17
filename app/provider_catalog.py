import csv
import io
import json
import re
import unicodedata
import zipfile
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET

from psycopg import Connection

from app.errors import DomainError


EXPECTED_COLUMNS = (
    "rfc", "razon_social", "nombre_normalizado", "nombre_comercial",
    "categoria", "subcategoria", "aliases", "activo",
)

# Estos RFC se usan para operaciones con público general o extranjeros. No
# identifican de forma única a un proveedor y nunca deben participar en la
# normalización automática del catálogo.
GENERIC_RFCS = frozenset({"XAXX010101000", "XEXX010101000"})


def normalize_provider_rfc(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", "", (value or "").upper()) or None
    return None if normalized in GENERIC_RFCS else normalized


def normalize_alias(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").upper())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^A-Z0-9&]+", " ", plain).split())


def find_provider(
    conn: Connection, *, rfc: str | None = None, proposed_name: str | None = None
) -> dict[str, Any] | None:
    normalized_rfc = normalize_provider_rfc(rfc)
    if normalized_rfc:
        row = conn.execute(
            """
            SELECT id, rfc, nombre_normalizado FROM catalog.proveedores
            WHERE rfc = %s AND activo LIMIT 1
            """,
            (normalized_rfc,),
        ).fetchone()
        if row:
            return row
    normalized_name = normalize_alias(proposed_name or "")
    if not normalized_name:
        return None
    return conn.execute(
        """
        SELECT p.id, p.rfc, p.nombre_normalizado
        FROM catalog.proveedores p
        LEFT JOIN catalog.proveedor_aliases a
          ON a.proveedor_id = p.id AND a.confirmado
        WHERE p.activo AND (
            a.alias_normalizado = %s
            OR regexp_replace(
                translate(upper(p.nombre_normalizado), 'ÁÉÍÓÚÜÑ', 'AEIOUUN'),
                '[^A-Z0-9&]+', ' ', 'g'
            ) = %s
        )
        ORDER BY CASE WHEN a.alias_normalizado = %s THEN 0 ELSE 1 END
        LIMIT 1
        """,
        (normalized_name, normalized_name, normalized_name),
    ).fetchone()


def find_provider_in_text(conn: Connection, text: str) -> dict[str, Any] | None:
    """Find a provider whose meaningful canonical name occurs in text.

    This is a conservative fallback for documents whose heading is preceded by
    fiscal boilerplate. Learned aliases are intentionally excluded here: an
    alias can occur in the customer, product or payment sections and is only
    safe when it is the provider name already extracted from the heading.
    """
    normalized_text = f" {normalize_alias(text)} "
    if len(normalized_text) < 8:
        return None
    rows = conn.execute(
        """
        SELECT p.id, p.rfc, p.nombre_normalizado,
               regexp_replace(
                   translate(upper(p.nombre_normalizado), 'ÁÉÍÓÚÜÑ', 'AEIOUUN'),
                   '[^A-Z0-9&]+', ' ', 'g'
               ) AS candidato
        FROM catalog.proveedores p
        WHERE p.activo
        """
    ).fetchall()
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        candidate = normalize_alias(row["candidato"])
        letters = sum(char.isalpha() for char in candidate)
        if letters < 6 or not candidate:
            continue
        position = normalized_text.find(f" {candidate} ")
        if position >= 0:
            matches.append((-len(candidate), position, row))
    if not matches:
        return None
    # En una factura el emisor suele aparecer antes que el receptor y que los
    # conceptos. La posición tiene prioridad; la longitud solo desempata.
    return min(matches, key=lambda item: (item[1], item[0]))[2]


def remember_provider_alias(
    conn: Connection,
    *,
    provider_id: UUID,
    alias: str,
    actor: str,
    invoice_id: UUID | None = None,
    review_id: UUID | None = None,
    origin: str = "revision_humana",
) -> dict[str, Any] | None:
    normalized = normalize_alias(alias)
    if len(normalized) < 3:
        return None
    canonical = conn.execute(
        "SELECT nombre_normalizado FROM catalog.proveedores WHERE id = %s",
        (provider_id,),
    ).fetchone()
    if not canonical or normalized == normalize_alias(canonical["nombre_normalizado"]):
        return None
    conflict = conn.execute(
        """
        SELECT p.id AS proveedor_id, p.nombre_normalizado
        FROM catalog.proveedores p
        LEFT JOIN catalog.proveedor_aliases a
          ON a.proveedor_id = p.id AND a.confirmado
        WHERE p.activo AND p.id <> %s AND (
            a.alias_normalizado = %s
            OR regexp_replace(
                translate(upper(p.nombre_normalizado), 'ÁÉÍÓÚÜÑ', 'AEIOUUN'),
                '[^A-Z0-9&]+', ' ', 'g'
            ) = %s
        )
        LIMIT 1
        """,
        (provider_id, normalized, normalized),
    ).fetchone()
    if conflict:
        raise DomainError(
            f'El alias "{alias}" ya pertenece a {conflict["nombre_normalizado"]}.', 409
        )
    row = conn.execute(
        """
        INSERT INTO catalog.proveedor_aliases (
            proveedor_id, alias, alias_normalizado, origen, confirmado, creado_por
        ) VALUES (%s, %s, %s, %s, true, %s)
        ON CONFLICT (alias_normalizado) DO UPDATE SET
            apariciones = catalog.proveedor_aliases.apariciones + 1,
            alias = EXCLUDED.alias,
            confirmado = true,
            actualizado_en = now()
        RETURNING id, alias, alias_normalizado, apariciones
        """,
        (provider_id, alias.strip(), normalized, origin, actor),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO audit.aprendizajes (
            factura_id, revision_id, proveedor_id, tipo, entrada, salida,
            registrado_por
        ) VALUES (%s, %s, %s, 'alias_proveedor', %s::jsonb, %s::jsonb, %s)
        """,
        (
            invoice_id, review_id, provider_id,
            json.dumps({"texto_ocr": alias}),
            json.dumps({"alias_normalizado": normalized, "proveedor": canonical["nombre_normalizado"]}),
            actor,
        ),
    )
    return row


def remember_accounting_rule(
    conn: Connection,
    *,
    provider_id: UUID,
    category_id: UUID,
    subcategory_id: UUID | None,
    actor: str,
    invoice_id: UUID | None = None,
    review_id: UUID | None = None,
) -> dict[str, Any]:
    previous = conn.execute(
        """
        SELECT COALESCE(max(version), 0)::integer AS version
        FROM catalog.reglas_clasificacion WHERE proveedor_id = %s
        """,
        (provider_id,),
    ).fetchone()["version"]
    conn.execute(
        "UPDATE catalog.reglas_clasificacion SET activa = false WHERE proveedor_id = %s AND activa",
        (provider_id,),
    )
    row = conn.execute(
        """
        INSERT INTO catalog.reglas_clasificacion (
            nombre, prioridad, proveedor_id, categoria_id, subcategoria_id,
            activa, version
        ) VALUES (%s, 10, %s, %s, %s, true, %s)
        RETURNING id, version
        """,
        (
            f"APRENDIDA:{provider_id}", provider_id, category_id,
            subcategory_id, previous + 1,
        ),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO audit.aprendizajes (
            factura_id, revision_id, proveedor_id, tipo, entrada, salida,
            registrado_por
        ) VALUES (%s, %s, %s, 'regla_contable', '{}'::jsonb, %s::jsonb, %s)
        """,
        (
            invoice_id, review_id, provider_id,
            json.dumps({
                "categoria_id": str(category_id),
                "subcategoria_id": str(subcategory_id) if subcategory_id else None,
                "version": row["version"],
            }),
            actor,
        ),
    )
    return row


def _category_key(conn: Connection, category_id: UUID) -> str:
    return conn.execute(
        "SELECT clave FROM catalog.categorias WHERE id = %s", (category_id,)
    ).fetchone()["clave"]


def _provider_rows(conn: Connection) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT p.id, p.rfc, p.nombre_legal AS razon_social,
               p.nombre_normalizado, p.nombre_comercial,
               p.activo, p.es_informal, p.telefono, p.giro,
               c.id AS categoria_id, c.clave AS categoria,
               sc.id AS subcategoria_id, sc.clave AS subcategoria,
               COALESCE(a.aliases, '[]'::json) AS aliases
        FROM catalog.proveedores p
        LEFT JOIN LATERAL (
            SELECT r.* FROM catalog.reglas_clasificacion r
            WHERE r.proveedor_id = p.id AND r.activa
            ORDER BY r.prioridad, r.version DESC LIMIT 1
        ) r ON true
        LEFT JOIN catalog.categorias c ON c.id = r.categoria_id
        LEFT JOIN catalog.subcategorias sc ON sc.id = r.subcategoria_id
        LEFT JOIN LATERAL (
            SELECT json_agg(json_build_object(
                'id', pa.id, 'alias', pa.alias, 'origen', pa.origen,
                'apariciones', pa.apariciones, 'confirmado', pa.confirmado
            ) ORDER BY pa.alias) AS aliases
            FROM catalog.proveedor_aliases pa WHERE pa.proveedor_id = p.id
        ) a ON true
        ORDER BY p.nombre_normalizado
        """
    ).fetchall()


def list_providers(conn: Connection) -> list[dict[str, Any]]:
    return _provider_rows(conn)


def _catalog_id(conn: Connection, table: str, key: str | None, active: str) -> UUID | None:
    if not key:
        return None
    row = conn.execute(
        f"SELECT id FROM catalog.{table} WHERE upper(clave) = upper(%s) AND {active}",
        (key.strip(),),
    ).fetchone()
    if not row:
        raise DomainError(f"No existe {table}: {key}.", 422)
    return row["id"]


def save_provider(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    provider_id = data.get("id")
    rfc = normalize_provider_rfc(data.get("rfc"))
    if rfc and not re.fullmatch(r"[A-Z&Ñ]{3,4}[0-9]{6}[A-Z0-9]{3}", rfc):
        raise DomainError("El RFC no tiene un formato válido.", 422)
    legal = str(data.get("razon_social") or data.get("nombre_normalizado") or "").strip()
    canonical = str(data.get("nombre_normalizado") or "").strip()
    if not canonical or not legal:
        raise DomainError("Razón social y nombre normalizado son obligatorios.", 422)
    if provider_id:
        if rfc and conn.execute(
            "SELECT 1 FROM catalog.proveedores WHERE rfc = %s AND id <> %s",
            (rfc, provider_id),
        ).fetchone():
            raise DomainError("El RFC ya pertenece a otro proveedor.", 409)
        row = conn.execute(
            """
            UPDATE catalog.proveedores SET rfc = %s, nombre_legal = %s,
                nombre_normalizado = %s, nombre_comercial = %s, activo = %s
            WHERE id = %s RETURNING id
            """,
            (
                rfc, legal, canonical, data.get("nombre_comercial") or None,
                bool(data.get("activo", True)), provider_id,
            ),
        ).fetchone()
        if not row:
            raise DomainError("Proveedor no encontrado.", 404)
    else:
        existing = find_provider(conn, rfc=rfc, proposed_name=canonical)
        if existing:
            provider_id = existing["id"]
            conn.execute(
                """
                UPDATE catalog.proveedores SET rfc = COALESCE(%s, rfc),
                    nombre_legal = %s, nombre_normalizado = %s,
                    nombre_comercial = %s, activo = %s
                WHERE id = %s
                """,
                (
                    rfc, legal, canonical, data.get("nombre_comercial") or None,
                    bool(data.get("activo", True)), provider_id,
                ),
            )
        else:
            provider_id = conn.execute(
                """
                INSERT INTO catalog.proveedores (
                    rfc, nombre_legal, nombre_normalizado, nombre_comercial, activo
                ) VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    rfc, legal, canonical, data.get("nombre_comercial") or None,
                    bool(data.get("activo", True)),
                ),
            ).fetchone()["id"]

    category_id = _catalog_id(conn, "categorias", data.get("categoria"), "activa")
    subcategory_id = _catalog_id(conn, "subcategorias", data.get("subcategoria"), "activa")
    if category_id:
        if _category_key(conn, category_id) == "FIJOS":
            from app.fixed_expenses import require_fixed_provider
            require_fixed_provider(conn, provider_id)
        if subcategory_id:
            valid = conn.execute(
                "SELECT 1 FROM catalog.subcategorias WHERE id = %s AND categoria_id = %s",
                (subcategory_id, category_id),
            ).fetchone()
            if not valid:
                raise DomainError("La subcategoría no pertenece a la categoría elegida.", 422)
        remember_accounting_rule(
            conn, provider_id=provider_id, category_id=category_id,
            subcategory_id=subcategory_id,
            actor=actor,
        )
    elif provider_id and "categoria" in data:
        conn.execute(
            "UPDATE catalog.reglas_clasificacion SET activa = false WHERE proveedor_id = %s AND activa",
            (provider_id,),
        )
    for alias in data.get("aliases") or []:
        remember_provider_alias(
            conn, provider_id=provider_id, alias=str(alias), actor=actor,
            origin=data.get("alias_origin", "administracion"),
        )
    return next(row for row in _provider_rows(conn) if row["id"] == provider_id)


def provider_quality(conn: Connection) -> dict[str, Any]:
    issues = conn.execute(
        """
        SELECT p.id, p.nombre_normalizado AS proveedor,
               CASE
                 WHEN p.nombre_normalizado LIKE '%??%' THEN 'nombre_ocr_sin_normalizar'
                 WHEN p.rfc IS NULL THEN 'sin_rfc'
                 WHEN r.id IS NULL THEN 'sin_clasificacion'
                 WHEN c.activa = false THEN 'categoria_inactiva'
                 ELSE NULL
               END AS problema
        FROM catalog.proveedores p
        LEFT JOIN LATERAL (
            SELECT rx.* FROM catalog.reglas_clasificacion rx
            WHERE rx.proveedor_id = p.id AND rx.activa
            ORDER BY rx.prioridad, rx.version DESC LIMIT 1
        ) r ON true
        LEFT JOIN catalog.categorias c ON c.id = r.categoria_id
        WHERE p.activo AND (
            p.nombre_normalizado LIKE '%??%' OR p.rfc IS NULL OR r.id IS NULL OR c.activa = false
        )
        ORDER BY problema, p.nombre_normalizado
        """
    ).fetchall()
    branch_pending = conn.execute(
        """
        SELECT count(*)::integer AS cantidad FROM core.facturas f
        JOIN catalog.sucursales s ON s.id = f.sucursal_id
        WHERE s.clave = 'POR-ASIGNAR' AND f.estado NOT IN ('aprobada', 'rechazada')
        """
    ).fetchone()["cantidad"]
    grouped: dict[str, int] = {}
    for issue in issues:
        grouped[issue["problema"]] = grouped.get(issue["problema"], 0) + 1
    return {
        "resumen": grouped,
        "sucursales_pendientes": branch_pending,
        "problemas": issues,
    }


def training_summary(conn: Connection) -> dict[str, Any]:
    totals = conn.execute(
        """
        SELECT count(*)::integer AS ejemplos_aprobados,
               count(*) FILTER (WHERE tuvo_correcciones)::integer AS con_correcciones
        FROM analytics.dataset_entrenamiento
        """
    ).fetchone()
    fields = conn.execute(
        """
        SELECT campo, count(*)::integer AS correcciones
        FROM audit.correcciones GROUP BY campo ORDER BY correcciones DESC, campo
        """
    ).fetchall()
    learnings = conn.execute(
        """
        SELECT tipo, count(*)::integer AS cantidad
        FROM audit.aprendizajes GROUP BY tipo ORDER BY tipo
        """
    ).fetchall()
    return {**totals, "correcciones_por_campo": fields, "aprendizajes": learnings}


def _read_csv(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    return [dict(row) for row in csv.DictReader(io.StringIO(text), dialect=dialect)]


def _read_xlsx(data: bytes) -> list[dict[str, str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    doc_ns = {"d": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", ns):
                shared.append("".join(node.text or "" for node in item.iterfind(".//m:t", ns)))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("r:Relationship", rel_ns)}
        sheets = workbook.find("m:sheets", ns)
        selected = next(
            (sheet for sheet in sheets if sheet.attrib.get("name", "").lower() == "proveedores"),
            sheets[0],
        )
        rel_id = selected.attrib[f"{{{doc_ns['d']}}}id"]
        target = targets[rel_id].lstrip("/")
        sheet_path = target if target.startswith("xl/") else f"xl/{target}"
        root = ET.fromstring(archive.read(sheet_path))
        matrix: list[list[str]] = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            values: dict[int, str] = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "A1")
                letters = re.match(r"[A-Z]+", ref).group(0)
                index = 0
                for char in letters:
                    index = index * 26 + ord(char) - 64
                index -= 1
                cell_type = cell.attrib.get("t")
                value = cell.find("m:v", ns)
                inline = cell.find("m:is/m:t", ns)
                raw = inline.text if inline is not None else (value.text if value is not None else "")
                if cell_type == "s" and raw:
                    raw = shared[int(raw)]
                values[index] = raw or ""
            if values:
                matrix.append([values.get(i, "") for i in range(max(values) + 1)])
        if not matrix:
            return []
        headers = matrix[0]
        return [
            {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
            for row in matrix[1:] if any(str(value).strip() for value in row)
        ]


def parse_provider_file(filename: str, data: bytes) -> list[dict[str, str]]:
    suffix = filename.lower().rsplit(".", 1)[-1]
    try:
        rows = _read_xlsx(data) if suffix == "xlsx" else _read_csv(data)
    except Exception as exc:
        raise DomainError(f"No fue posible leer el catálogo: {exc}", 422) from exc
    normalized_rows = []
    for row in rows:
        normalized = {normalize_alias(key).lower().replace(" ", "_"): str(value or "").strip() for key, value in row.items()}
        normalized_rows.append(normalized)
    return normalized_rows


def preview_provider_import(conn: Connection, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    preview = []
    for number, raw in enumerate(rows, start=2):
        data = {key: raw.get(key, "") for key in EXPECTED_COLUMNS}
        data["aliases"] = [item.strip() for item in re.split(r"[|;]", data["aliases"]) if item.strip()]
        data["activo"] = str(data["activo"] or "SI").upper() not in {"NO", "FALSE", "0", "INACTIVO"}
        errors = []
        if not data["nombre_normalizado"]:
            errors.append("Falta nombre_normalizado")
        if not data["razon_social"]:
            errors.append("Falta razon_social")
        try:
            category_id = _catalog_id(conn, "categorias", data["categoria"] or None, "activa")
            subcategory_id = _catalog_id(conn, "subcategorias", data["subcategoria"] or None, "activa")
            if category_id and _category_key(conn, category_id) == "FIJOS":
                from app.fixed_expenses import require_fixed_provider
                existing_fixed = find_provider(
                    conn, rfc=data["rfc"] or None, proposed_name=data["nombre_normalizado"]
                ) if data["nombre_normalizado"] else None
                require_fixed_provider(conn, existing_fixed["id"] if existing_fixed else None)
            if category_id and subcategory_id and not conn.execute(
                "SELECT 1 FROM catalog.subcategorias WHERE id=%s AND categoria_id=%s",
                (subcategory_id, category_id),
            ).fetchone():
                errors.append("Subcategoría incompatible")
        except DomainError as exc:
            errors.append(exc.message)
        existing = find_provider(
            conn, rfc=data["rfc"] or None, proposed_name=data["nombre_normalizado"]
        ) if data["nombre_normalizado"] else None
        preview.append({
            "fila": number,
            "accion": "error" if errors else ("actualizar" if existing else "crear"),
            "errores": errors,
            "proveedor_id": existing["id"] if existing else None,
            "datos": data,
        })
    return preview


def apply_provider_import(
    conn: Connection, preview: list[dict[str, Any]], actor: str
) -> dict[str, int]:
    if any(row["errores"] for row in preview):
        raise DomainError("Corrija los errores del archivo antes de importarlo.", 422)
    counts = {"creados": 0, "actualizados": 0}
    for item in preview:
        data = dict(item["datos"])
        data["id"] = item["proveedor_id"]
        data["alias_origin"] = "importacion"
        saved = save_provider(conn, data, actor)
        counts["actualizados" if item["accion"] == "actualizar" else "creados"] += 1
        conn.execute(
            """
            INSERT INTO audit.aprendizajes (
                proveedor_id, tipo, entrada, salida, registrado_por
            ) VALUES (%s, 'importacion_catalogo', %s::jsonb, %s::jsonb, %s)
            """,
            (saved["id"], json.dumps(item["datos"]), json.dumps({"accion": item["accion"]}), actor),
        )
    return counts
