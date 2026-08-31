BEGIN;

ALTER TABLE core.facturas_finales
    ALTER COLUMN subtotal DROP NOT NULL,
    ALTER COLUMN descuento DROP NOT NULL,
    ALTER COLUMN iva DROP NOT NULL,
    ALTER COLUMN otros_impuestos DROP NOT NULL;

ALTER TABLE ai.interpretaciones
    ALTER COLUMN descuento DROP NOT NULL,
    ALTER COLUMN iva DROP NOT NULL,
    ALTER COLUMN otros_impuestos DROP NOT NULL;

UPDATE core.validaciones
SET severidad = 'advertencia',
    mensaje = CASE
        WHEN aprobada THEN 'Los importes cuadran'
        ELSE 'El desglose no cuadra; puede aprobarse verificando el total'
    END
WHERE codigo = 'CUADRE_TOTAL';

UPDATE catalog.categorias
SET activa = false
WHERE clave NOT IN ('FIJOS', 'VARIABLES', 'BARRA', 'RESTAURANTE');

UPDATE catalog.subcategorias sc
SET activa = false
FROM catalog.categorias c
WHERE c.id = sc.categoria_id
  AND NOT (
      (c.clave = 'FIJOS' AND sc.clave = 'RENTA')
      OR (c.clave = 'VARIABLES' AND sc.clave = 'MANTENIMIENTO')
  );

INSERT INTO catalog.categorias (clave, nombre, activa, orden)
VALUES
    ('FIJOS', 'Fijos', true, 10),
    ('VARIABLES', 'Variables', true, 20),
    ('BARRA', 'Barra', true, 30),
    ('RESTAURANTE', 'Restaurante', true, 40)
ON CONFLICT (clave) DO UPDATE
SET nombre = EXCLUDED.nombre,
    activa = true,
    orden = EXCLUDED.orden;

INSERT INTO catalog.subcategorias (categoria_id, clave, nombre, activa)
SELECT id, 'RENTA', 'Renta', true
FROM catalog.categorias WHERE clave = 'FIJOS'
ON CONFLICT (categoria_id, clave) DO UPDATE
SET nombre = EXCLUDED.nombre, activa = true;

INSERT INTO catalog.subcategorias (categoria_id, clave, nombre, activa)
SELECT id, 'MANTENIMIENTO', 'Mantenimiento', true
FROM catalog.categorias WHERE clave = 'VARIABLES'
ON CONFLICT (categoria_id, clave) DO UPDATE
SET nombre = EXCLUDED.nombre, activa = true;

COMMIT;
