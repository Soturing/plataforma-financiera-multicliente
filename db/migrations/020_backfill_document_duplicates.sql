BEGIN;

WITH latest_interpretations AS (
    SELECT DISTINCT ON (i.factura_id)
        i.factura_id, i.uuid_fiscal
    FROM ai.interpretaciones i
    WHERE i.uuid_fiscal IS NOT NULL
    ORDER BY i.factura_id, i.version DESC
), ranked AS (
    SELECT f.id, f.archivo_url, f.archivo_nombre, f.archivo_sha256,
           li.uuid_fiscal,
           row_number() OVER (
               PARTITION BY li.uuid_fiscal
               ORDER BY
                   EXISTS (
                       SELECT 1 FROM core.facturas_finales ff
                       WHERE ff.factura_id = f.id AND ff.vigente
                   ) DESC,
                   (f.archivo_mime IN ('application/xml', 'text/xml')) DESC,
                   f.recibida_en ASC, f.id ASC
           ) AS posicion
    FROM core.facturas f
    JOIN latest_interpretations li ON li.factura_id = f.id
    WHERE f.estado <> 'rechazada'
), originals AS (
    SELECT uuid_fiscal, id FROM ranked WHERE posicion = 1
)
INSERT INTO core.documentos_duplicados (
    factura_original_id, factura_duplicada_id, archivo_url, archivo_nombre,
    archivo_sha256, criterio, valor_coincidente
)
SELECT o.id, r.id, r.archivo_url, r.archivo_nombre, r.archivo_sha256,
       'uuid_fiscal', r.uuid_fiscal::text
FROM ranked r
JOIN originals o USING (uuid_fiscal)
WHERE r.posicion > 1
  AND NOT EXISTS (
      SELECT 1 FROM core.facturas_finales ff
      WHERE ff.factura_id = r.id AND ff.vigente
  )
  AND NOT EXISTS (
      SELECT 1 FROM core.documentos_duplicados d
      WHERE d.factura_duplicada_id = r.id
        AND d.criterio = 'uuid_fiscal' AND d.estado = 'pendiente'
  );

COMMIT;
