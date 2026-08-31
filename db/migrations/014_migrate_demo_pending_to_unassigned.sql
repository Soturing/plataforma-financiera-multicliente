BEGIN;

DO $$
DECLARE
    unassigned_id uuid;
BEGIN
    SELECT id INTO unassigned_id
    FROM catalog.sucursales
    WHERE clave = 'POR-ASIGNAR' AND activa;

    IF unassigned_id IS NULL THEN
        RAISE EXCEPTION 'No existe una sucursal POR-ASIGNAR activa';
    END IF;

    UPDATE core.facturas f
    SET sucursal_id = unassigned_id,
        sucursal_origen = 'migracion_demo_por_asignar',
        sucursal_deteccion = jsonb_build_object(
            'metodo', 'migracion',
            'regla', 'demo-inactiva-a-por-asignar-v1',
            'motivo', 'Sucursal DEMO-01 desactivada; requiere asignacion humana'
        ),
        actualizada_en = now()
    FROM catalog.sucursales previous_branch
    WHERE f.sucursal_id = previous_branch.id
      AND previous_branch.clave = 'DEMO-01'
      AND NOT previous_branch.activa
      AND f.estado = 'requiere_revision';
END $$;

COMMIT;
