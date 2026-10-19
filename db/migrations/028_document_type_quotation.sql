-- Tipo de documento "cotizacion": documentos sin valor fiscal que no son un gasto.
ALTER TYPE core.tipo_documento ADD VALUE IF NOT EXISTS 'cotizacion';
