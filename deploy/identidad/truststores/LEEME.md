# Raíces de atestación de las llaves físicas

Coloque aquí, en formato PEM, el certificado raíz de atestación del fabricante de las llaves
FIDO2 que usarán los roles globales (p. ej. la raíz de atestación de Yubico). Sin esa raíz,
Keycloak rechaza las llaves reales cuando la lista de AAGUID está configurada
(docs/seguridad/fase1-identidad.md §3–§4). Los certificados públicos sí pueden versionarse.
