#!/bin/bash

# ==============================================================================
# Instalador nativo (sin Docker) para JZ PASS
# ==============================================================================
# Para Debian/Ubuntu (apt). Correr como root desde la raiz del repo clonado
# (tiene que estar main.py al lado de este script).
#
# Idempotente: se puede correr de nuevo para actualizar codigo y servicio.
# Los secretos ya generados (clave de Postgres, JWT_SECRET, SETUP_TOKEN) no
# se pisan en corridas siguientes, para no romper el acceso a la base ni las
# sesiones existentes.
#
# No probado todavia en una VM limpia (ver seccion 6 de
# JZTech_Estado_y_Hoja_de_Ruta.md). Antes de usarlo en produccion, probarlo
# en una VM descartable de punta a punta, login desde navegador incluido.
# ==============================================================================

set -euo pipefail

# ---- Configuracion (se puede pisar con variables de entorno antes de correr) ----
APP_NAME="jzpass"
APP_USER="${JZPASS_USER:-jzpass}"
APP_GROUP="$APP_USER"
APP_DIR="${JZPASS_DIR:-/opt/jzpass}"
ENV_DIR="/etc/$APP_NAME"
ENV_FILE="$ENV_DIR/$APP_NAME.env"
SERVICE_NAME="$APP_NAME"
DB_NAME="${JZPASS_DB_NAME:-jzpass_db}"
DB_USER="${JZPASS_DB_USER:-jzadmin}"
APP_PORT="${JZPASS_PORT:-8000}"
APP_BIND="127.0.0.1"   # uvicorn solo escucha en localhost; Caddy expone HTTPS al exterior
DOMAIN="${JZPASS_DOMAIN:-jzpass.local}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=================================================="
echo "Instalador nativo de JZ PASS (sin Docker)"
echo "=================================================="

# 1. Privilegios, sistema operativo y ubicacion del script
if [ "$EUID" -ne 0 ]; then
  echo "Error: correr como root (sudo ./install-native.sh)." >&2
  exit 1
fi
if [ ! -f /etc/debian_version ]; then
  echo "Error: este instalador es para Debian/Ubuntu (apt). No se detecto /etc/debian_version." >&2
  exit 1
fi
if [ ! -f "$SCRIPT_DIR/main.py" ]; then
  echo "Error: correr el script desde la raiz del repo clonado (falta main.py junto a install-native.sh)." >&2
  exit 1
fi

echo "Privilegios y sistema operativo confirmados."

# 2. Paquetes del sistema
echo "Actualizando lista de paquetes..."
apt-get update -qq

echo "Instalando dependencias del sistema..."
apt-get install -y -qq \
  python3 python3-venv python3-dev python3-pip \
  postgresql postgresql-contrib \
  build-essential openssl git curl rsync ca-certificates gnupg \
  debian-keyring debian-archive-keyring apt-transport-https \
  > /dev/null

if ! command -v caddy &> /dev/null; then
  echo "Instalando Caddy (proxy inverso HTTPS)..."
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
  apt-get update -qq
  apt-get install -y -qq caddy > /dev/null
else
  echo "Caddy ya esta instalado."
fi

# 3. Usuario de sistema sin login
if ! id "$APP_USER" &> /dev/null; then
  echo "Creando usuario de sistema $APP_USER..."
  useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
else
  echo "Usuario $APP_USER ya existe."
fi

# 4. Codigo de la aplicacion (uploads/ y venv/ no se tocan si ya existen)
echo "Copiando codigo a $APP_DIR..."
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude '.git' --exclude '.gitignore' --exclude 'uploads' --exclude 'venv' \
  --exclude 'install-native.sh' \
  "$SCRIPT_DIR"/ "$APP_DIR"/
mkdir -p "$APP_DIR/uploads"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"

# 5. Entorno virtual
echo "Preparando entorno virtual..."
if [ ! -d "$APP_DIR/venv" ]; then
  sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
fi
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# 6. PostgreSQL: rol y base de datos
echo "Verificando servicio de PostgreSQL..."
systemctl enable --now postgresql > /dev/null

DB_ROLE_EXISTE=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")
DB_EXISTE=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")

if [ -f "$ENV_FILE" ]; then
  echo "Ya existe $ENV_FILE: se reutilizan los secretos existentes (no se pisan)."
  DB_PASSWORD=$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
  JWT_SECRET=$(grep -E '^JWT_SECRET=' "$ENV_FILE" | cut -d= -f2-)
  SETUP_TOKEN=$(grep -E '^SETUP_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
  if [ "$DB_ROLE_EXISTE" != "1" ]; then
    echo "Error: $ENV_FILE existe pero el rol $DB_USER no existe en Postgres. Revisar a mano." >&2
    exit 1
  fi
else
  if [ "$DB_ROLE_EXISTE" = "1" ]; then
    echo "Error: el rol $DB_USER ya existe en Postgres pero no hay $ENV_FILE con su clave." >&2
    echo "No se genera una clave nueva porque rompería el acceso existente. Revisar a mano." >&2
    exit 1
  fi
  echo "Generando secretos..."
  DB_PASSWORD=$(openssl rand -base64 16 | tr -d '=+/' | cut -c1-16)
  JWT_SECRET=$(openssl rand -hex 32)
  SETUP_TOKEN=$(openssl rand -hex 12)
fi

if [ "$DB_ROLE_EXISTE" != "1" ]; then
  echo "Creando rol de Postgres $DB_USER..."
  sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';" > /dev/null
fi
if [ "$DB_EXISTE" != "1" ]; then
  echo "Creando base de datos $DB_NAME..."
  sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" > /dev/null
fi

# 7. Archivo de entorno (root:grupo de la app, modo 0640)
echo "Escribiendo $ENV_FILE..."
mkdir -p "$ENV_DIR"
cat > "$ENV_FILE" <<EOF
# Generado por install-native.sh. No versionar ni copiar a otro host tal cual.
APP_PORT=$APP_PORT
APP_BIND=$APP_BIND
ALLOWED_ORIGINS=https://$DOMAIN
TRUSTED_PROXIES=127.0.0.1/32,::1/128
JWT_SECRET=$JWT_SECRET
SETUP_TOKEN=$SETUP_TOKEN
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
PYTHONDONTWRITEBYTECODE=1
EOF
chown root:"$APP_GROUP" "$ENV_FILE"
chmod 640 "$ENV_FILE"

# 8. Servicio systemd
echo "Escribiendo servicio systemd..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=JZPass
After=network.target postgresql.service

[Service]
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host $APP_BIND --port $APP_PORT
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=$APP_DIR/uploads
MemoryMax=384M

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" > /dev/null
systemctl restart "$SERVICE_NAME"

# 9. Proxy inverso HTTPS (Caddy, CA local: sirve para laboratorio/pruebas)
CADDYFILE="/etc/caddy/Caddyfile"
touch "$CADDYFILE"
if ! grep -q "^$DOMAIN {" "$CADDYFILE"; then
  echo "Agregando bloque de $DOMAIN a $CADDYFILE..."
  cat >> "$CADDYFILE" <<EOF

$DOMAIN {
    tls internal
    reverse_proxy $APP_BIND:$APP_PORT
}
EOF
else
  echo "$CADDYFILE ya tiene un bloque para $DOMAIN, no se toca."
fi
systemctl enable --now caddy > /dev/null
systemctl reload caddy 2> /dev/null || systemctl restart caddy

# 10. /etc/hosts, solo para pruebas en esta misma maquina (en produccion usar DNS real)
if ! getent hosts "$DOMAIN" > /dev/null 2>&1; then
  echo "127.0.0.1 $DOMAIN" >> /etc/hosts
  echo "Agregado '$DOMAIN' a /etc/hosts, apuntando a esta misma maquina."
fi

# 11. Mensaje final
echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA"
echo "================================================================="
echo "Acceso: https://$DOMAIN"
echo "El certificado es de la CA local de Caddy (\"tls internal\"): el"
echo "navegador va a avisar que no es de confianza salvo que importes esa"
echo "CA. Para una prueba rapida, aceptá la excepción del navegador."
echo ""
echo "Token de configuración inicial: $SETUP_TOKEN"
echo "Entrá a la URL de arriba: te va a pedir este token para crear el"
echo "usuario administrador. Deja de servir después de crear el primero."
echo "================================================================="
