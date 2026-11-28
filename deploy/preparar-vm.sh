#!/usr/bin/env bash
# Prepara la VM de producción (Debian) para recibir despliegues. Se ejecuta una vez, a mano, desde
# el botón SSH de Google Cloud:
#
#   curl -fsSLO https://raw.githubusercontent.com/MikelAguilar/Finance-Balance-Backend/main/deploy/preparar-vm.sh
#   less preparar-vm.sh                     # revísalo antes de ejecutarlo
#   sudo DEPLOY_PUBLIC_KEY="ssh-ed25519 AAAA... despliegue" bash preparar-vm.sh
#
# Es idempotente: ejecutarlo otra vez (o tras un fallo a medias) deja la VM igual, sin duplicar nada
# y sin cambiar las claves que ya existan.
#
# Qué deja hecho:
#   1. Docker y Docker Compose desde el repositorio oficial de Docker.
#   2. 1 GB de swap: la e2-micro tiene 1 GB de RAM y cuatro contenedores.
#   3. Actualizaciones de seguridad automáticas del sistema.
#   4. El usuario "deploy", que es con el que entra GitHub Actions (solo con llave, nunca con clave).
#   5. /srv/finance-balance con un .env de claves aleatorias generadas aquí: no salen de la VM.
set -euo pipefail

APP_DIR=/srv/finance-balance
DEPLOY_USER=deploy
SITE_ADDRESS=${SITE_ADDRESS:-api.risteyra.com}
DEPLOY_PUBLIC_KEY=${DEPLOY_PUBLIC_KEY:-}

if [[ $EUID -ne 0 ]]; then
    echo "Ejecuta este script con sudo." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

paso() { printf '\n==> %s\n' "$1"; }

paso "1/5 Docker"
if ! command -v docker >/dev/null 2>&1; then
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    # shellcheck source=/dev/null
    codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $codename stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable --now docker
docker --version
docker compose version

paso "2/5 Swap de 1 GB"
if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
fi
swapon --show=NAME --noheadings | grep -qx /swapfile || swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

paso "3/5 Actualizaciones de seguridad automáticas"
apt-get install -y unattended-upgrades openssl
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

paso "4/5 Usuario $DEPLOY_USER"
id -u "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
# El grupo docker equivale a root en esta máquina; se acepta porque la VM solo sirve a esta API.
usermod -aG docker "$DEPLOY_USER"
ssh_dir="/home/$DEPLOY_USER/.ssh"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ssh_dir"
touch "$ssh_dir/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "$ssh_dir/authorized_keys"
chmod 600 "$ssh_dir/authorized_keys"
if [[ -n $DEPLOY_PUBLIC_KEY ]]; then
    if [[ $DEPLOY_PUBLIC_KEY != ssh-* ]]; then
        echo "DEPLOY_PUBLIC_KEY no parece una llave pública (debe empezar con ssh-)." >&2
        exit 1
    fi
    grep -qxF "$DEPLOY_PUBLIC_KEY" "$ssh_dir/authorized_keys" || echo "$DEPLOY_PUBLIC_KEY" >> "$ssh_dir/authorized_keys"
fi
echo "Llaves autorizadas para $DEPLOY_USER: $(grep -c '^ssh-' "$ssh_dir/authorized_keys" || true)"

paso "5/5 Carpeta de la aplicación y .env"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR/gateway"
if [[ ! -f $APP_DIR/.env ]]; then
    # Hex: sin caracteres que haya que escapar en la URL de la base de datos.
    (
        umask 077
        cat > "$APP_DIR/.env" <<EOF
APP_ENV=production
SITE_ADDRESS=$SITE_ADDRESS
POSTGRES_USER=finance
POSTGRES_PASSWORD=$(openssl rand -hex 32)
POSTGRES_DB=finance_balance
JWT_SECRET=$(openssl rand -hex 32)
EOF
    )
    echo "Se creó $APP_DIR/.env con claves nuevas (no se muestran)."
else
    echo "$APP_DIR/.env ya existía: no se tocó."
fi
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

printf '\nListo. La VM ya puede recibir despliegues en %s (usuario %s).\n' "$APP_DIR" "$DEPLOY_USER"
