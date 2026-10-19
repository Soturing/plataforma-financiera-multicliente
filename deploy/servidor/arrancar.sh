#!/usr/bin/env bash
# Arranque tras un reinicio del servidor (D-025). Lo ejecuta una persona, no el sistema:
# OpenBao queda sellado y sólo se abre con 2 de las 3 llaves de desbloqueo.
#   bash /opt/facturas/deploy/servidor/arrancar.sh GRUPO-DEMO [OTRO-CLIENTE ...]
set -euo pipefail
cd /opt/facturas
PY=/opt/facturas/venv/bin/python
export SECRETOS_URL=http://127.0.0.1:8200

echo "1/3 Plano de control"
docker compose -p facturas -f deploy/servidor/control.compose.yaml --env-file /etc/facturas/control.env up -d

echo "2/3 Abrir OpenBao (se piden 2 llaves; no quedan guardadas)"
until "$PY" -m app.plataforma.secretos estado | grep -q "'sellado': False"; do
  "$PY" -m app.plataforma.secretos abrir || sleep 2
done

echo "3/3 Clientes: montar archivos cifrados y levantar app y workers"
for CLAVE in "$@"; do
  "$PY" -m app.plataforma.archivos montar --clave "$CLAVE"
  "$PY" -m app.plataforma.tenants desplegar --clave "$CLAVE" --imagen "${FACTURAS_IMAGEN:-facturas-app:produccion}"
done
echo "Listo."
