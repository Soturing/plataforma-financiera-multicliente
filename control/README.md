# Plano de control

Este directorio contiene el esquema de metadatos compartidos del producto. Se despliega en una base PostgreSQL distinta de cualquier data plane de clientes.

Puede almacenar identidades, tenants, asignaciones, módulos, sucursales, sesiones y auditoría de seguridad basada en metadatos. No puede almacenar facturas, ventas, nómina, inventarios, recetas, proveedores, archivos ni métricas financieras.

La migración inicial no crea usuarios de base de datos ni secretos. En producción, el aprovisionamiento deberá crear credenciales independientes para migraciones, ejecución y auditoría, mediante el gestor de secretos de la infraestructura.
