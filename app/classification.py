import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import Connection


RULES_VERSION = "0.3"
EXPENSE_DOCUMENT_TYPES = frozenset(
    {"factura_fiscal", "ticket_compra", "nota_venta", "remision", "recibo"}
)


def is_expense_document(document_type: str | None) -> bool:
    return document_type in EXPENSE_DOCUMENT_TYPES


@dataclass(frozen=True)
class Classification:
    type: str
    confidence: float
    matched_rules: list[str]
    signals: dict[str, bool]


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.upper())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).strip()


def classify_document(text: str) -> Classification:
    value = normalize(text)
    signals = {
        "factura": bool(
            re.search(
                r"\bFACTURA\b|TIPO (?:DE )?COMPROBANTE\s*:?-?\s*(?:I|INGRESO)\b|\bI\s*-\s*INGRESO\b",
                value,
            )
        ),
        "uuid": bool(re.search(r"\bUUID\b|FOLIO FISCAL|[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", value)),
        "subtotal": "SUBTOTAL" in value,
        "iva": bool(re.search(r"\bI\.?V\.?A\.?\b|IMPUESTO AL VALOR AGREGADO", value)),
        "nota_credito": "NOTA DE CREDITO" in value or "EGRESO" in value and "CFDI" in value,
        "sipare": "SIPARE" in value or ("IMSS" in value and "INFONAVIT" in value),
        "transferencia": "RECIBO DE LA TRANSFERENCIA" in value or "TRANSFERENCIA SPEI" in value or "CUENTA DESTINO" in value,
        "rastreo": "CLAVE DE RASTREO" in value or "FOLIO DE TRANSACCION" in value or "VERIFICADOR" in value,
        "banco": any(bank in value for bank in ("BANREGIO", "BBVA", "BANORTE", "SANTANDER", "HSBC", "SCOTIABANK", "CITIBANAMEX")),
        "servicio": "TU RECIBO DE PAGO" in value or "PAGO DE SERVICIO" in value or "SERVICIO GAS NATURAL" in value,
        "comprobante_pago": "COMPROBANTE DE PAGO" in value or "RECIBO DE PAGO" in value,
        "recibo": bool(re.search(r"\bRECIBO\b", value)),
        "ticket": bool(re.search(r"\bTICKET\b|#\s*DE\s*TICKET|\bTC\s*#|\bTDA\s*#.+\bTR\s*#", value)),
        "nota_venta": bool(re.search(r"\bNOTA\s+DE\s+VENTA\b", value)),
        "remision": bool(re.search(r"\bREMISI[O0]N\b", value)),
        "complemento_pago": bool(
            re.search(
                r"COMPLEMENTO (?:PARA (?:LA )?)?RECEPCION DE PAGOS?"
                r"|COMPLEMENTO DE PAGO"
                r"|RECIBO ELECTRONICO DE PAGO"
                r"|TIPO (?:DE )?COMPROBANTE\s*:?-?\s*(?:P|PAGO)\b",
                value,
            )
        ) or (
            bool(re.search(r"DOCUMENTOS? RELACIONADOS?", value))
            and any(
                signal in value
                for signal in ("IMPORTE PAGADO", "SALDO INSOLUTO", "NUM PARCIALIDAD")
            )
        ),
        "estado_cuenta": "ESTADO DE CUENTA" in value
        or ("SALDO PENDIENTE" in value and "VENCIDO" in value),
        "datos_bancarios": bool(
            re.search(r"NUM\.? DE CUENTA|CLABE\s*:|CUENTA CLABE|SWIFT", value)
        ) and "BANCO" in value,
    }

    if signals["nota_credito"]:
        return Classification("nota_credito", 0.99, ["nota_credito_explicita"], signals)
    if signals["nota_venta"]:
        return Classification("nota_venta", 0.93, ["nota_venta_explicita"], signals)
    if signals["remision"]:
        return Classification("remision", 0.91, ["remision_explicita"], signals)
    if signals["ticket"]:
        return Classification("ticket_compra", 0.94, ["ticket_compra"], signals)
    if signals["sipare"]:
        rules = [name for name in ("sipare", "comprobante_pago") if signals[name]]
        return Classification("sipare_imss", 0.99, rules, signals)
    if signals["estado_cuenta"] or signals["datos_bancarios"]:
        rules = [name for name in ("estado_cuenta", "datos_bancarios") if signals[name]]
        return Classification("desconocido", 0.98, rules, signals)
    if signals["complemento_pago"]:
        rules = [
            name
            for name in ("complemento_pago", "comprobante_pago", "uuid", "recibo")
            if signals[name]
        ]
        return Classification("comprobante_pago", 0.99, rules, signals)
    if signals["factura"] and sum(signals[name] for name in ("uuid", "subtotal", "iva")) >= 1:
        rules = [name for name in ("factura", "uuid", "subtotal", "iva") if signals[name]]
        return Classification("factura_fiscal", min(0.99, 0.72 + 0.08 * len(rules)), rules, signals)
    if signals["servicio"]:
        rules = [name for name in ("servicio", "banco", "comprobante_pago") if signals[name]]
        return Classification("pago_servicio", min(0.97, 0.78 + 0.06 * len(rules)), rules, signals)
    if signals["transferencia"] or (signals["banco"] and signals["rastreo"]):
        rules = [name for name in ("transferencia", "rastreo", "banco") if signals[name]]
        return Classification("transferencia_bancaria", min(0.98, 0.75 + 0.07 * len(rules)), rules, signals)
    if signals["comprobante_pago"]:
        return Classification("comprobante_pago", 0.82, ["comprobante_pago"], signals)
    if signals["recibo"]:
        return Classification("recibo", 0.72, ["recibo_generico"], signals)
    return Classification("desconocido", 0.35, ["sin_senales_suficientes"], signals)


def save_classification(
    conn: Connection,
    invoice_id: UUID,
    classification: Classification,
) -> dict[str, Any]:
    version = conn.execute(
        """
        SELECT COALESCE(max(version), 0) + 1 AS version
        FROM core.clasificaciones_documentales WHERE factura_id = %s
        """,
        (invoice_id,),
    ).fetchone()["version"]
    evidence = {
        "matched_rules": classification.matched_rules,
        "signals": classification.signals,
    }
    row = conn.execute(
        """
        INSERT INTO core.clasificaciones_documentales (
            factura_id, version, tipo, confianza, clasificador,
            reglas_version, evidencia
        ) VALUES (%s, %s, %s, %s, 'reglas-deterministicas', %s, %s::jsonb)
        RETURNING id, version, tipo::text, confianza, evidencia, clasificada_en
        """,
        (
            invoice_id, version, classification.type, classification.confidence,
            RULES_VERSION, json.dumps(evidence),
        ),
    ).fetchone()
    return row


def classify_saved_ocr(conn: Connection, invoice_id: UUID) -> dict[str, Any]:
    ocr = conn.execute(
        """
        SELECT texto_raw FROM ocr.resultados
        WHERE factura_id = %s ORDER BY version DESC LIMIT 1
        """,
        (invoice_id,),
    ).fetchone()
    if not ocr:
        raise ValueError("La factura no tiene resultado OCR")
    return save_classification(conn, invoice_id, classify_document(ocr["texto_raw"]))


def reclassify_batch(conn: Connection, batch_id: UUID) -> list[dict[str, Any]]:
    invoices = conn.execute(
        """
        SELECT f.id, o.texto_raw
        FROM core.facturas f
        JOIN LATERAL (
            SELECT texto_raw FROM ocr.resultados ox
            WHERE ox.factura_id = f.id ORDER BY version DESC LIMIT 1
        ) o ON true
        WHERE f.lote_id = %s ORDER BY f.pagina_origen
        """,
        (batch_id,),
    ).fetchall()
    results = []
    for invoice in invoices:
        result = save_classification(
            conn, invoice["id"], classify_document(invoice["texto_raw"])
        )
        conn.execute(
            """
            UPDATE core.facturas_finales
            SET tipo_documento = %s,
                estado_fiscal = CASE WHEN %s = 'factura_fiscal'
                    THEN 'con_cfdi' ELSE 'no_deducible' END
            WHERE factura_id = %s AND vigente
            """,
            (result["tipo"], result["tipo"], invoice["id"]),
        )
        results.append(result)
    return results
