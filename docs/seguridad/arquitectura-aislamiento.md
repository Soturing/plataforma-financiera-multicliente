# Arquitectura de aislamiento multi-tenant

Estado: arquitectura objetivo aprobada; todavía no implementada.
Fecha de aprobación: 2026-08-30.

## 1. Diagnóstico del sistema actual

La demo utiliza una sola base PostgreSQL, una sola credencial de aplicación y un directorio local compartido para archivos. Los catálogos, documentos, finanzas y auditoría se almacenan en la misma base. Existen sucursales, pero todavía no existe una entidad de cliente o tenant.

Esta configuración es válida para la demo de un solo cliente, pero no puede utilizarse para incorporar otro grupo restaurantero.

## 2. Decisión

Se adopta como arquitectura objetivo:

> Un plano de control compartido sin información financiera y un data plane aislado por grupo restaurantero, con backend, PostgreSQL, archivos, claves, caché, colas, integraciones y respaldos propios.

Se rechazan como destino final las tablas compartidas con `tenant_id` y los esquemas compartidos dentro de una sola base.

## 3. Recursos por tenant

```text
Grupo restaurantero A
├── Servicio backend A
├── PostgreSQL A
├── Credenciales A
├── Almacenamiento A
├── Clave de cifrado A
├── Caché A
├── Colas y procesos A
├── Integraciones A
└── Respaldos A

Grupo restaurantero B
├── Servicio backend B
├── PostgreSQL B
├── Credenciales B
├── Almacenamiento B
├── Clave de cifrado B
├── Caché B
├── Colas y procesos B
├── Integraciones B
└── Respaldos B
```

Los clientes utilizan la misma versión del producto, pero sus procesos y recursos de datos no se mezclan.

## 4. Plano compartido de control

El plano de control puede almacenar:

- identificador del usuario;
- identificador del proveedor de identidad;
- roles;
- membresías;
- módulos y sucursales asignados;
- estado activo o suspendido;
- registro de tenants;
- dirección interna del data plane correspondiente;
- estado contractual del servicio;
- políticas; y
- auditoría de seguridad basada en metadatos.

No almacena información financiera ni documentos del cliente.

## 5. Información que nunca se comparte

- facturas y archivos originales;
- OCR e interpretaciones;
- proveedores y contactos;
- ventas;
- nómina;
- deuda y ganancias;
- inventarios;
- recetas;
- comprobantes;
- catálogos contables;
- reportes generados;
- caché de resultados;
- credenciales de integración;
- respaldos; y
- claves de cifrado.

## 6. Flujo de petición

```text
1. El usuario se autentica con passkey
                     ↓
2. El plano de control carga sus membresías
                     ↓
3. El usuario selecciona un cliente permitido
                     ↓
4. El servidor crea un contexto firmado
                     ↓
5. El gateway resuelve el data plane correspondiente
                     ↓
6. El backend del cliente verifica:
   - token válido
   - tenant esperado
   - membresía vigente
   - rol
   - módulo
   - acción
   - sucursal
                     ↓
7. El backend sólo posee credenciales de su propia base
                     ↓
8. Ejecuta la operación
                     ↓
9. Registra auditoría
```

El backend de un cliente no posee credenciales para los recursos de otro.

## 7. Determinación del tenant

El tenant se deriva exclusivamente de:

```text
sesión autenticada
+ membresía vigente
+ selección validada
```

No se confía directamente en:

- un encabezado enviado por el navegador;
- parámetros de URL;
- campos ocultos;
- identificadores de sucursal;
- tenant indicado dentro de un archivo; ni
- valores enviados por una integración sin validar.

El identificador puede viajar en una petición, pero el servidor siempre lo compara con la identidad, membresía y ruta interna autorizadas.

## 8. Defensa en PostgreSQL

Cada base conserva una identidad única de tenant. Las tablas sensibles incluyen `tenant_id` y cada conexión establece el tenant esperado.

Se utiliza Row-Level Security como defensa adicional:

- `ENABLE ROW LEVEL SECURITY`;
- `FORCE ROW LEVEL SECURITY`;
- política de denegación predeterminada;
- validación para `SELECT`, `INSERT`, `UPDATE` y `DELETE`;
- restricción adicional por sucursal;
- la cuenta de ejecución no es propietaria de las tablas; y
- la cuenta de ejecución no tiene `SUPERUSER` ni `BYPASSRLS`.

Roles de base por tenant:

```text
tenant_runtime
├── Lectura y escritura ordinaria
├── No crea tablas
├── No cambia políticas
└── No omite RLS

tenant_reports
├── Sólo vistas aprobadas
└── Sólo lectura

tenant_migrations
├── Uso exclusivo durante despliegue
└── No utilizado por la aplicación

tenant_backup
├── Uso automatizado
└── Sin acceso interactivo
```

Las credenciales se almacenan en un gestor de secretos y nunca en el repositorio.

## 9. Archivos

Cada tenant tiene un contenedor o bucket propio.

Reglas:

- nombres internos aleatorios;
- sin acceso público;
- cifrado con clave del tenant;
- enlaces firmados para un solo archivo;
- caducidad inicial máxima de cinco minutos;
- autorización antes de generar el enlace;
- descarga auditada; y
- exportaciones temporales eliminadas en 24 horas.

El directorio local compartido de la demo no se utiliza en producción.

## 10. Claves de cifrado

Cada cliente tiene:

- clave envolvente independiente;
- claves separadas para datos y respaldos cuando sea posible;
- política de acceso propia;
- rotación;
- auditoría de uso;
- procedimiento de recuperación; y
- destrucción únicamente al finalizar la baja y retención.

Perder o destruir una clave no debe afectar a otros clientes.

## 11. Caché, colas y procesos

- no se comparten claves de caché sin aislamiento;
- se prefiere instancia o credencial de caché por tenant;
- cada clave incluye tenant y versión;
- cada trabajo lleva contexto firmado;
- un worker sólo accede a sus recursos;
- un mensaje sin tenant válido se descarta;
- reintentar un trabajo no cambia su tenant; y
- las colas de exportación y OCR se separan por cliente.

## 12. Reportes globales

No se crea una base central con todos los datos.

```text
Director solicita consolidado
        ↓
Reautenticación C3
        ↓
Selecciona clientes y periodo
        ↓
Servicio de consolidación
        ↓
Consulta APIs internas de sólo lectura
        ↓
Cada data plane devuelve métricas agregadas autorizadas
        ↓
El servicio combina resultados
        ↓
El resultado temporal queda auditado
```

El consolidador:

- no accede directamente a tablas;
- no recibe nóminas individuales;
- no recibe recetas;
- no conserva una copia permanente;
- sólo utiliza métricas aprobadas;
- utiliza credenciales internas de corta duración;
- no permite escrituras; y
- registra los clientes consultados.

## 13. Alta de cliente

La activación requiere:

1. crear tenant;
2. crear data plane;
3. crear PostgreSQL aislado;
4. aplicar migraciones;
5. crear roles de mínimos privilegios;
6. crear almacenamiento;
7. crear claves;
8. crear colas y caché;
9. crear respaldo;
10. configurar auditoría;
11. crear catálogos iniciales;
12. ejecutar pruebas de aislamiento;
13. intentar acceso desde otro tenant;
14. intentar conexión con credenciales equivocadas; y
15. activar únicamente si todas las pruebas pasan.

## 14. Baja de cliente

```text
ACTIVO
  ↓
SUSPENDIDO
  ↓
SOLO LECTURA O EXPORTACIÓN CONTRACTUAL
  ↓
RETENCIÓN
  ↓
ELIMINACIÓN PROGRAMADA
  ↓
DESTRUCCIÓN DE CLAVE
  ↓
EVIDENCIA DE CIERRE
```

Suspender el servicio no elimina datos inmediatamente.

## 15. Migración de la demo

Cuando se autorice la construcción:

1. registrar el grupo actual como primer tenant;
2. crear el plano de control;
3. crear su data plane aislado;
4. migrar la base actual completa;
5. sustituir actores de texto por identidades;
6. migrar archivos locales al almacenamiento del tenant;
7. incorporar el router;
8. aplicar RLS;
9. añadir pruebas con dos tenants ficticios; y
10. incorporar un segundo cliente sólo después de superar las pruebas.

## 16. Referencias de arquitectura

- [OWASP Multi-Tenant Security](https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html)
- [AWS PostgreSQL silo model](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-managed-postgresql/silo.html)
- [AWS PostgreSQL partitioning decision matrix](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-managed-postgresql/matrix.html)
- [AWS Multi-Tenant API Access Authorization](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-api-access-authorization/introduction.html)
- [PostgreSQL Row Security Policies](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)
