#!/usr/bin/env bash
# Preparación de un VPS Ubuntu 24.04 LTS para la plataforma (D-019, D-025).
# Ejecutar UNA vez como root, tras crear el usuario de operación con su llave SSH:
#   sudo bash deploy/servidor/preparar-servidor.sh facturas-op
#
# Qué hace (y qué NO): endurece el acceso, instala Docker, gocryptfs y un entorno Python
# mínimo para operar. No crea secretos, no inicializa OpenBao ni levanta servicios.
set -euo pipefail

USUARIO="${1:-facturas-op}"   # mismo usuario que usan los temporizadores de deploy/servidor/systemd
id "$USUARIO" >/dev/null 2>&1 || { echo "El usuario $USUARIO no existe"; exit 1; }
[ -s "/home/$USUARIO/.ssh/authorized_keys" ] || { echo "Antes agregue la llave SSH de $USUARIO (si no, quedaría fuera)"; exit 1; }

echo "1/7 Actualizaciones de seguridad automáticas"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get -y -q upgrade
DEBIAN_FRONTEND=noninteractive apt-get -y -q install unattended-upgrades ufw fail2ban gocryptfs fuse3 \
  python3-venv ca-certificates curl gnupg
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "2/7 SSH sólo con llave, sin root"
install -m 600 /dev/null /etc/ssh/sshd_config.d/10-facturas.conf
cat > /etc/ssh/sshd_config.d/10-facturas.conf <<CONF
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers $USUARIO
CONF
systemctl reload ssh

echo "3/7 Cortafuegos: sólo SSH (limitado), HTTP y HTTPS"
ufw default deny incoming
ufw default allow outgoing
ufw limit OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "4/7 Docker Engine (repositorio oficial)"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get -y -q install docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker "$USUARIO"
# Docker publica puertos saltándose ufw: el plano de control sólo publica 80/443 hacia fuera
# y el resto en 127.0.0.1 (deploy/servidor/control.compose.yaml).

echo "5/7 FUSE: la app (uid 10001 en su contenedor) debe leer la vista descifrada de gocryptfs"
grep -q '^user_allow_other' /etc/fuse.conf || echo user_allow_other >> /etc/fuse.conf

echo "6/7 Carpetas de la plataforma"
install -d -m 750 -o "$USUARIO" -g "$USUARIO" /opt/facturas /srv/facturas /etc/facturas
install -d -m 700 -o "$USUARIO" -g "$USUARIO" /opt/facturas/config

echo "7/7 Entorno Python de operación"
sudo -u "$USUARIO" python3 -m venv /opt/facturas/venv
echo "Instale las dependencias tras copiar el código: /opt/facturas/venv/bin/pip install -r /opt/facturas/requirements-operacion.txt"

echo "Listo. Siguiente paso: docs/seguridad/despliegue-servidor.md §4."
