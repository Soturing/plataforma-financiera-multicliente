from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class FacturaCreada(BaseModel):
    id: UUID
    estado: str
    archivo_nombre: str


class ProcesamientoSimulado(BaseModel):
    proveedor: str = Field(min_length=1, max_length=250)
    folio: str | None = Field(default=None, max_length=100)
    fecha_emision: date
    subtotal: Decimal = Field(ge=0, decimal_places=2)
    iva: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    descuento: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    otros_impuestos: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)
    total: Decimal = Field(gt=0, decimal_places=2)
    categoria_clave: str = "VARIABLES_OPERATIVOS"
    subcategoria_clave: str | None = None
    rfc_emisor: str | None = None
    uuid_fiscal: UUID | None = None
    confianza_ocr: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)
    confianza_ia: Decimal = Field(default=Decimal("0.95"), ge=0, le=1)


class ProcesamientoResultado(BaseModel):
    factura_id: UUID
    estado: str
    interpretacion_id: UUID
    requiere_revision: bool
    validaciones_fallidas: int


class PeriodificacionRequest(BaseModel):
    tipo: Literal["una_semana", "mensual", "bimestral", "personalizado"]
    periodo_desde: date
    periodo_hasta: date


class AprobarRequest(BaseModel):
    revisada_por: str = Field(min_length=1, max_length=200)
    comentario: str | None = Field(default=None, max_length=2000)
    forzar_como_gasto: bool = False
    recordar_alias: bool = False
    recordar_clasificacion: bool = False
    periodificacion: PeriodificacionRequest | None = None
    recordar_periodificacion: bool = False


class RechazarRequest(AprobarRequest):
    comentario: str = Field(min_length=3, max_length=2000)


class CorreccionCampo(BaseModel):
    campo: Literal[
        "proveedor_id", "proveedor_nombre", "sucursal_id", "folio", "fecha_emision", "subtotal", "descuento", "iva",
        "otros_impuestos", "total", "categoria_id", "subcategoria_id",
        "rfc_emisor", "uuid_fiscal", "observaciones"
    ]
    valor: Any
    motivo: str | None = Field(default=None, max_length=500)


class CorregirRequest(AprobarRequest):
    correcciones: list[CorreccionCampo] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def campos_sin_repetir(self):
        campos = [item.campo for item in self.correcciones]
        if len(campos) != len(set(campos)):
            raise ValueError("No se puede corregir el mismo campo dos veces")
        return self


class EditarFacturaRequest(AprobarRequest):
    correcciones: list[CorreccionCampo] = Field(default_factory=list, max_length=20)
    genera_gasto: bool | None = None

    @model_validator(mode="after")
    def campos_sin_repetir(self):
        campos = [item.campo for item in self.correcciones]
        if len(campos) != len(set(campos)):
            raise ValueError("No se puede corregir el mismo campo dos veces")
        return self


class DecisionResultado(BaseModel):
    factura_id: UUID
    estado: str
    factura_final_id: UUID | None = None


class FacturaRevision(BaseModel):
    id: UUID
    estado: str
    recibida_en: datetime
    archivo_nombre: str
    archivo_url: str
    sucursal: str
    restaurante: str
    interpretacion_id: UUID | None = None
    proveedor: str | None = None
    folio: str | None = None
    folio_origen: str | None = None
    fecha_emision: date | None = None
    subtotal: Decimal | None = None
    iva: Decimal | None = None
    total: Decimal | None = None
    categoria: str | None = None
    subcategoria: str | None = None
    confianza: Decimal | None = None
    validaciones_fallidas: int = 0
    tipo_documento: str | None = None
    confianza_clasificacion: Decimal | None = None


class HealthResponse(BaseModel):
    status: str
    database: str


class LoteCreado(BaseModel):
    id: UUID
    estado: str
    total_paginas: int
    facturas_creadas: int


class LoteResumen(BaseModel):
    id: UUID
    estado: str
    archivo_original_nombre: str
    total_paginas: int
    creado_por: str
    creado_en: datetime
    sucursal: str
    restaurante: str
    recibidas: int
    procesando: int
    revision: int
    aprobadas: int
    rechazadas: int
    errores: int


class EliminarDocumentosRequest(BaseModel):
    factura_ids: list[UUID] = Field(min_length=1, max_length=200)
    eliminado_por: str = Field(min_length=1, max_length=200)


class CancelarLoteRequest(BaseModel):
    cancelado_por: str = Field(min_length=1, max_length=200)


class EliminarLoteRequest(BaseModel):
    eliminado_por: str = Field(min_length=1, max_length=200)


class AprobarComprobanteRequest(BaseModel):
    autorizada_por: str = Field(min_length=1, max_length=200)
    comentario: str | None = Field(default=None, max_length=2000)


class RechazarComprobanteRequest(BaseModel):
    rechazada_por: str = Field(min_length=1, max_length=200)
    motivo: str = Field(min_length=3, max_length=2000)


class SustituirComprobanteRequest(BaseModel):
    factura_final_id: UUID


class ProveedorCatalogoRequest(BaseModel):
    id: UUID | None = None
    rfc: str | None = Field(default=None, max_length=13)
    razon_social: str = Field(min_length=1, max_length=250)
    nombre_normalizado: str = Field(min_length=1, max_length=250)
    nombre_comercial: str | None = Field(default=None, max_length=250)
    categoria: str | None = Field(default=None, max_length=100)
    subcategoria: str | None = Field(default=None, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    activo: bool = True
    actualizado_por: str = Field(min_length=1, max_length=200)


class SubcategoriaCatalogoRequest(BaseModel):
    id: UUID | None = None
    categoria_id: UUID
    clave: str = Field(min_length=2, max_length=50)
    nombre: str = Field(min_length=2, max_length=150)
    activa: bool = True
    actualizado_por: str = Field(min_length=1, max_length=200)


class EntidadPropiaRequest(BaseModel):
    nombre: str = Field(min_length=4, max_length=250)
    rfc: str | None = Field(default=None, max_length=20)
    activa: bool = True
    actualizado_por: str = Field(min_length=1, max_length=200)


class GastoFijoRequest(BaseModel):
    proveedor_id: UUID
    subcategoria_id: UUID | None = None
    periodicidad: Literal["una_semana", "mensual", "bimestral", "personalizado"] | None = None
    activa: bool = True
    actualizado_por: str = Field(min_length=1, max_length=200)


class ComisionParametroRequest(BaseModel):
    sucursal_clave: str = Field(min_length=1, max_length=50)
    concepto: Literal["VISA", "AMEX", "BANCO", "APPS", "SERVICIOS"]
    canal: Literal["UBER", "RAPPI"] | None = None
    base: Literal["visa", "amex", "credito", "uber", "rappi", "ventas_netas", "monto_mensual"]
    porcentaje: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=6)
    monto_mensual: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    actualizado_por: str = Field(min_length=1, max_length=200)


class ComisionCierreRequest(BaseModel):
    sucursal_clave: str = Field(min_length=1, max_length=50)
    concepto: Literal["VISA", "AMEX", "BANCO", "APPS", "SERVICIOS"]
    anio: int = Field(ge=2000, le=2100)
    mes: int = Field(ge=1, le=12)
    importe_real: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    actualizado_por: str = Field(min_length=1, max_length=200)


class NominaRequest(BaseModel):
    sucursal_clave: str = Field(min_length=1, max_length=50)
    anio_iso: int = Field(ge=2000, le=2100)
    semana_iso: int = Field(ge=1, le=53)
    monto: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    nota: str | None = Field(default=None, max_length=300)
    actualizado_por: str = Field(min_length=1, max_length=200)


class VentaManualRequest(BaseModel):
    sucursal_id: UUID
    fecha: date
    monto_neto: Decimal = Field(gt=0, decimal_places=2)
    referencia: str | None = Field(default=None, max_length=200)
    registrada_por: str = Field(min_length=1, max_length=200)


class VentaDesgloseItem(BaseModel):
    fecha: date
    efectivo: Decimal = Field(default=Decimal("0"), ge=0)
    dolares: Decimal = Field(default=Decimal("0"), ge=0)
    tipo_cambio: Decimal = Field(default=Decimal("0"), ge=0)
    rappi: Decimal = Field(default=Decimal("0"), ge=0)
    uber: Decimal = Field(default=Decimal("0"), ge=0)
    visa: Decimal = Field(default=Decimal("0"), ge=0)
    amex: Decimal = Field(default=Decimal("0"), ge=0)
    venta_otro: Decimal = Field(default=Decimal("0"), ge=0)
    venta_aplicaciones: Decimal = Field(default=Decimal("0"), ge=0)
    venta_alimentos: Decimal = Field(default=Decimal("0"), ge=0)
    venta_bebidas: Decimal = Field(default=Decimal("0"), ge=0)
    visitas: int = Field(default=0, ge=0)
    faltante: Decimal = Field(default=Decimal("0"), ge=0)
    sobrante: Decimal = Field(default=Decimal("0"), ge=0)
    monto_neto: Decimal | None = Field(default=None, ge=0)
    total_capturado_manual: bool = False


class GastoReporteSemanalItem(BaseModel):
    fila_origen: int = Field(ge=1)
    area: Literal["barra", "restaurante"]
    proveedor: str = Field(min_length=1, max_length=250)
    fecha: date
    monto: Decimal = Field(gt=0, le=Decimal("300000"), decimal_places=2)
    pago: str = Field(default="efectivo", max_length=40)
    semana: int = Field(ge=1, le=53)
    numero_factura: str | None = Field(default=None, max_length=100)
    descripcion: str = Field(min_length=1, max_length=1000)
    incluir: bool = True


class VentasDesgloseRequest(BaseModel):
    sucursal_id: UUID
    filas: list[VentaDesgloseItem] = Field(min_length=1, max_length=31)
    gastos: list[GastoReporteSemanalItem] = Field(default_factory=list, max_length=200)
    archivo_origen: str | None = Field(default=None, max_length=300)
    actualizada_por: str = Field(min_length=1, max_length=200)


class DescartarDuplicadosRequest(BaseModel):
    duplicado_ids: list[UUID] = Field(min_length=1, max_length=100)
    descartado_por: str = Field(min_length=1, max_length=200)
