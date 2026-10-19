# OpenBao del plano de control (D-025): secretos de la plataforma y claves por cliente.
# Desarrollo: HTTP sólo en 127.0.0.1. Producción: TLS (listener con certificado o detrás
# del proxy con TLS hasta OpenBao) y almacenamiento en el disco cifrado del servidor.
storage "raft" {
  path    = "/openbao/file"
  node_id = "secretos-1"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr      = "http://127.0.0.1:8200"
cluster_addr  = "http://127.0.0.1:8201"
ui            = false
disable_mlock = true

# Bitácora de auditoría de OpenBao: cada uso de una clave o secreto (D-025).
audit "file" "archivo" {
  description = "Auditoría de uso de claves y secretos"
  options {
    file_path = "/openbao/logs/auditoria.log"
  }
}
