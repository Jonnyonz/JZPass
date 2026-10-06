#!/bin/bash
# ==============================================================================
# Instalador nativo (sin Docker) de JZPass
# ==============================================================================
# Para Debian 12/13 y Ubuntu 24.04 (apt, Python 3.11 o mas nuevo). Correr como root desde la raiz de un
# clon del repositorio:
#
#   sudo ./install-native.sh                                   sin dominio (se pregunta en una instalacion nueva)
#   sudo JZPASS_DOMAIN=rrhh.empresa.com ./install-native.sh    dominio publico con el que se va a entrar
#
# Queda asi:
#   /opt/jzpass/src/                 clon de git del que se actualiza (lo usa jzpass-actualizar)
#   /opt/jzpass/releases/<version>/  codigo + su propio venv (una carpeta por version; version = commit)
#   /opt/jzpass/current              enlace a la version en uso (el actualizador lo cambia)
#   /var/lib/jzpass/uploads/         adjuntos de las solicitudes, mapas y logo (fuera del codigo: no se tocan
#                                    al actualizar; cada version tiene un enlace uploads -> aca)
#   /etc/jzpass/jzpass.env           configuracion y secretos (root:jzpass, 0640)
#   servicio systemd "jzpass"        uvicorn por http en 0.0.0.0:8020, un worker
#   base "jzpass_db" propia en el PostgreSQL del servidor (las tablas las crea la app al arrancar)
#   El HTTPS lo da el proxy del servidor, que tiene el 80/443 y saca los certificados: al terminar se
#   muestra donde quedo escuchando (la sesion usa cookies Secure y el fichaje usa el GPS del celular: sin HTTPS
#   no se puede ingresar desde otra PC ni fichar)
#   /usr/local/sbin/jzpass-actualizar  actualizador (respaldo, chequeo y vuelta atras)
#
# Idempotente: se puede volver a correr. Los secretos ya generados no se pisan. Sin compilador: las
# dependencias se instalan solo con paquetes binarios (wheels) verificando los hashes de requirements.txt;
# si hay una carpeta wheelhouse/ al lado, se usa esa (sin internet).
#
# Si encuentra una instalacion nativa anterior (el codigo directo en /opt/jzpass, de las versiones de este
# instalador previas a 2.5.1), la pasa a este esquema: conserva la base, los secretos, el puerto y el
# dominio, y mueve los adjuntos a /var/lib/jzpass/uploads (el codigo viejo queda en /opt/jzpass/anterior-*).
#
# Las versiones 2.6.0 de este instalador ponian Caddy delante (la app solo en 127.0.0.1): ahora la app pasa a
# 0.0.0.0 para que llegue el proxy. Caddy no se desinstala solo (puede usarlo otra app): se avisa como sacarlo.
#
# Es independiente de la instalacion con Docker (install.sh): no se pueden usar las dos en el mismo puerto.
#
# Variables opcionales:
#   JZPASS_DOMAIN=rrhh.empresa.com  dominio publico (lo atiende el proxy; se agrega a los origenes permitidos)
#   JZPASS_BIND=0.0.0.0             interfaz donde escucha el servicio (por defecto 0.0.0.0, para que el proxy llegue)
#   JZPASS_PROXY_IP=192.168.1.5     IP del proxy si esta en otro equipo (se agrega a TRUSTED_PROXIES)
#   JZPASS_PORT=8020                puerto del servicio
#   JZPASS_REPO_URL=...             repositorio del que se actualiza (por defecto, el origin de este clon)
# ==============================================================================

set -euo pipefail

APP_NAME="jzpass"
APP_USER="jzpass"
BASE_DIR="${JZPASS_DIR:-/opt/jzpass}"
RELEASES="$BASE_DIR/releases"
SRC="$BASE_DIR/src"
DATOS="/var/lib/$APP_NAME"
ENV_DIR="/etc/$APP_NAME"
ENV_FILE="$ENV_DIR/$APP_NAME.env"
SERVICE="$APP_NAME"
ACTUALIZADOR="/usr/local/sbin/jzpass-actualizar"
if [ -n "${JZPASS_CADDY:-}${JZPASS_IP:-}" ]; then
  echo "Aviso: JZPASS_CADDY y JZPASS_IP ya no se usan (ya no hay Caddy): se ignoran."
fi
PROXIES_DEFECTO="127.0.0.1/32,::1/128,172.16.0.0/12"   # loopback y redes de Docker (un proxy en este servidor)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /   # psql como postgres no puede entrar a la carpeta desde la que se corre (por ejemplo /root)

valor_env() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1 || true; }

echo "=================================================="
echo "Instalador nativo de JZPass"
echo "=================================================="

# 1. Privilegios, sistema y ubicacion
if [ "$EUID" -ne 0 ]; then
  echo "Error: correr como root (sudo ./install-native.sh)." >&2
  exit 1
fi
if [ ! -f /etc/debian_version ]; then
  echo "Error: este instalador es para Debian/Ubuntu (apt)." >&2
  exit 1
fi
if [ ! -f "$SCRIPT_DIR/main.py" ] || [ ! -f "$SCRIPT_DIR/requirements.txt" ] || [ ! -f "$SCRIPT_DIR/dashboard.html" ]; then
  echo "Error: correr el script desde la raiz del repo (faltan main.py, requirements.txt o dashboard.html)." >&2
  exit 1
fi

# Instalacion nativa anterior: el codigo estaba directo en $BASE_DIR (sin releases/ ni current).
ANTERIOR=0
if [ -f "$BASE_DIR/main.py" ] && [ ! -L "$BASE_DIR/current" ]; then
  ANTERIOR=1
  echo "Se encontro una instalacion nativa anterior en $BASE_DIR: se pasa al esquema nuevo."
fi

# Configuracion: lo pedido, lo de la instalacion anterior o el valor por defecto.
APP_PORT="${JZPASS_PORT:-$(valor_env APP_PORT)}"; APP_PORT="${APP_PORT:-8020}"
DOMAIN="${JZPASS_DOMAIN:-$(valor_env JZPASS_DOMAIN)}"
if [ "$ANTERIOR" = "1" ] && [ -z "$DOMAIN" ]; then
  # El instalador anterior no guardaba el dominio: se toma de ALLOWED_ORIGINS (https://dominio).
  DOMAIN="$(valor_env ALLOWED_ORIGINS | cut -d, -f1 | sed -e 's#^https\?://##' -e 's#[:/].*$##')"
  if [[ "$DOMAIN" =~ ^[0-9.]+$ ]] || [ "$DOMAIN" = "localhost" ]; then DOMAIN=""; fi
fi
if [ -z "$DOMAIN" ] && [ ! -f "$ENV_FILE" ] && { : < /dev/tty; } 2> /dev/null; then
  read -r -p "Dominio publico de JZPass (ej. rrhh.empresa.com; Enter para entrar por la IP del servidor): " DOMAIN < /dev/tty || DOMAIN=""
fi
DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
if [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "Error: dominio invalido: $DOMAIN" >&2
  exit 1
fi
if ! [[ "$APP_PORT" =~ ^[0-9]+$ ]]; then
  echo "Error: puerto invalido: $APP_PORT" >&2
  exit 1
fi
# Las instalaciones con Caddy escuchaban solo en 127.0.0.1 (la 2.6.0 no guardaba APP_BIND; la anterior a la
# 2.5.1 guardaba 127.0.0.1): pasan a 0.0.0.0. Un JZPASS_BIND elegido en una instalacion nueva se respeta.
APP_BIND="${JZPASS_BIND:-$(valor_env APP_BIND)}"
if [ -z "${JZPASS_BIND:-}" ] && [ "$ANTERIOR" = "1" ]; then APP_BIND=""; fi
APP_BIND="${APP_BIND:-0.0.0.0}"
if ! [[ "$APP_BIND" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: JZPASS_BIND tiene que ser una IPv4 (ej. 0.0.0.0): $APP_BIND" >&2
  exit 1
fi
if [ -n "${JZPASS_PROXY_IP:-}" ] && ! [[ "$JZPASS_PROXY_IP" =~ ^[0-9A-Fa-f.:]+(/[0-9]+)?$ ]]; then
  echo "Error: JZPASS_PROXY_IP invalida: $JZPASS_PROXY_IP" >&2
  exit 1
fi
if [ "$APP_BIND" = "0.0.0.0" ]; then LOCAL="127.0.0.1"; else LOCAL="$APP_BIND"; fi

# 2. Paquetes del sistema (sin compilador ni cabeceras de Python)
echo "Instalando paquetes del sistema..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv postgresql postgresql-client openssl curl rsync git ca-certificates \
  iproute2 > /dev/null
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Error: hace falta Python 3.11 o mas nuevo (este sistema tiene $(python3 --version 2>&1))." >&2
  echo "Sistemas soportados: Debian 12, Debian 13, Ubuntu 24.04." >&2
  exit 1
fi
IP="$(hostname -I 2> /dev/null | awk '{print $1}')"
if [ -z "$IP" ]; then IP="$(ip -4 route get 1.1.1.1 2> /dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')"; fi
IP="${IP:-<IP del servidor>}"

# El puerto local tiene que estar libre (por ejemplo, ocupado por la instalacion con Docker).
OCUPANTE="$(ss -ltnpH "( sport = :$APP_PORT )" 2>/dev/null || true)"
if [ -n "$OCUPANTE" ] && ! systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  echo "Error: el puerto $APP_PORT ya esta en uso:" >&2
  echo "$OCUPANTE" >&2
  echo "Si es JZPass con Docker (install.sh), no se pueden usar las dos instalaciones en el mismo puerto." >&2
  echo "Usar otro puerto con JZPASS_PORT=8021 o detener la de Docker (docker compose down)." >&2
  exit 1
fi

# 3. Usuario de sistema sin login (no es dueno del codigo: solo lo lee; escribe solo en $DATOS/uploads)
if ! id "$APP_USER" &> /dev/null; then
  echo "Creando usuario de sistema $APP_USER..."
  useradd --system --no-create-home --home-dir "$DATOS" --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -m 0750 -o "$APP_USER" -g "$APP_USER" "$DATOS" "$DATOS/uploads"

# 4. Version (commit de git) y clon del que se actualiza
GIT="git -c safe.directory=*"
if $GIT -C "$SCRIPT_DIR" rev-parse --git-dir > /dev/null 2>&1; then
  VERSION="$($GIT -C "$SCRIPT_DIR" rev-parse --short=12 HEAD)"
  if [ -n "$($GIT -C "$SCRIPT_DIR" status --porcelain --untracked-files=no)" ]; then
    VERSION="$VERSION-local"   # con cambios sin commit: se instala igual, pero se marca
  fi
  REPO_URL="${JZPASS_REPO_URL:-$($GIT -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || true)}"
else
  VERSION="local-$(date +%Y%m%d%H%M%S)"
  REPO_URL="${JZPASS_REPO_URL:-}"
fi
REPO_URL="${REPO_URL:-$(valor_env JZPASS_REPO_URL)}"
REPO_URL="${REPO_URL:-https://github.com/Jonnyonz/JZPass.git}"
echo "Version a instalar: $VERSION"

# 4b. Instalacion anterior: se detiene, se copian los adjuntos y el codigo viejo se aparta.
if [ "$ANTERIOR" = "1" ]; then
  systemctl stop "$SERVICE" 2>/dev/null || true
  if [ -d "$BASE_DIR/uploads" ]; then
    echo "Copiando los adjuntos a $DATOS/uploads..."
    cp -a "$BASE_DIR/uploads/." "$DATOS/uploads/"
    chown -R "$APP_USER:$APP_USER" "$DATOS/uploads"
    N_VIEJO=$(find "$BASE_DIR/uploads" -type f | wc -l); N_NUEVO=$(find "$DATOS/uploads" -type f | wc -l)
    if [ "$N_NUEVO" -lt "$N_VIEJO" ]; then
      echo "Error: se copiaron $N_NUEVO de $N_VIEJO adjuntos. No se sigue (la instalacion anterior quedo como estaba)." >&2
      exit 1
    fi
  fi
  VIEJO="$BASE_DIR/anterior-$(date +%Y%m%d%H%M%S)"
  mkdir -p "$VIEJO"
  find "$BASE_DIR" -mindepth 1 -maxdepth 1 ! -name 'anterior-*' ! -name src ! -name releases -exec mv -t "$VIEJO" {} +
  echo "El codigo de la instalacion anterior quedo en $VIEJO (se puede borrar cuando ande la nueva)."
fi

mkdir -p "$BASE_DIR"
if [ ! -d "$SRC/.git" ]; then
  echo "Clonando $REPO_URL en $SRC (de ahi se actualiza)..."
  if ! $GIT clone --quiet "$REPO_URL" "$SRC"; then
    echo "Aviso: no se pudo clonar $REPO_URL; jzpass-actualizar no va a funcionar hasta que exista $SRC." >&2
  fi
fi

# 5. Codigo y entorno virtual de esta version
DEST="$RELEASES/$VERSION"
echo "Instalando la version $VERSION en $DEST..."
mkdir -p "$RELEASES"
rsync -a --delete --exclude '.git' --exclude 'venv' --exclude '.venv' --exclude 'wheelhouse' --exclude 'backups' \
  --exclude '__pycache__' --exclude '.env' --exclude 'uploads' --exclude 'tests' "$SCRIPT_DIR"/ "$DEST"/
ln -sfn "$DATOS/uploads" "$DEST/uploads"
echo "$VERSION" > "$DEST/.jzpass-version"
if [ ! -x "$DEST/venv/bin/python" ]; then
  python3 -m venv "$DEST/venv"
fi
PIP_ORIGEN=()
if [ -d "$SCRIPT_DIR/wheelhouse" ]; then
  echo "Usando wheelhouse/ (sin internet)."
  PIP_ORIGEN=(--no-index --find-links "$SCRIPT_DIR/wheelhouse")
fi
"$DEST/venv/bin/pip" install --quiet --disable-pip-version-check --require-hashes --only-binary=:all: \
  "${PIP_ORIGEN[@]}" -r "$DEST/requirements.txt"
chown -R root:root "$DEST"
chown -h root:root "$DEST/uploads"
chmod -R a+rX,go-w "$DEST"

# 6. PostgreSQL: rol y base propios en el cluster del servidor
echo "Verificando PostgreSQL..."
systemctl enable --now postgresql > /dev/null
DB_NAME="$(valor_env DB_NAME)"; DB_NAME="${DB_NAME:-jzpass_db}"
DB_USER="$(valor_env DB_USER)"; DB_USER="${DB_USER:-jzpass}"
ROL_EXISTE=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")
BASE_EXISTE=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")
if [ -f "$ENV_FILE" ]; then
  echo "Ya existe $ENV_FILE: se reutilizan los secretos (no se pisan)."
  DB_PASSWORD="$(valor_env DB_PASSWORD)"
  JWT_SECRET="$(valor_env JWT_SECRET)"
  SETUP_TOKEN="$(valor_env SETUP_TOKEN)"
  if [ "$ROL_EXISTE" != "1" ]; then
    echo "Error: $ENV_FILE existe pero el rol $DB_USER no existe en PostgreSQL. Revisar a mano." >&2
    exit 1
  fi
else
  if [ "$ROL_EXISTE" = "1" ]; then
    echo "Error: el rol $DB_USER ya existe en PostgreSQL pero no hay $ENV_FILE con su clave." >&2
    echo "No se genera una clave nueva porque romperia el acceso existente. Revisar a mano." >&2
    exit 1
  fi
  echo "Generando secretos..."
  DB_PASSWORD="$(openssl rand -hex 24)"
  JWT_SECRET="$(openssl rand -hex 32)"
  SETUP_TOKEN="$(openssl rand -hex 24)"
fi
if [ "$ROL_EXISTE" != "1" ]; then
  echo "Creando rol $DB_USER..."
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';"
fi
if [ "$BASE_EXISTE" != "1" ]; then
  echo "Creando base $DB_NAME..."
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
fi
# La clave del env tiene que ser la que acepta la base (si no, el servicio arranca pero responde 503).
if ! PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT 1" > /dev/null 2>&1; then
  echo "Error: PostgreSQL no acepta la clave de $DB_USER que esta en $ENV_FILE. Revisar a mano." >&2
  exit 1
fi

# 7. Configuracion (se reescribe con los mismos secretos; root:jzpass 0640)
echo "Escribiendo $ENV_FILE..."
mkdir -p "$ENV_DIR"
ADICIONALES=""
if [ -f "$ENV_FILE" ]; then
  # Lo que el administrador agrego a mano se conserva (TRUSTED_PROXIES incluido: puede haber otro proxy).
  ADICIONALES="$(grep -Ev '^(#|$|DB_(USER|PASSWORD|NAME)=|DATABASE_URL=|JWT_SECRET=|SETUP_TOKEN=|ALLOWED_ORIGINS=|APP_(PORT|BIND)=|JZPASS_(DOMAIN|IP|INSTALACION|REPO_URL)=|PYTHONDONTWRITEBYTECODE=|TZ=)' "$ENV_FILE" || true)"
fi
PROXIES="$(printf '%s\n' "$ADICIONALES" | sed -n 's/^TRUSTED_PROXIES=//p' | tail -n1)"
# El default de las versiones anteriores (solo loopback) no cubre a el proxy en un contenedor de este servidor.
if [ -z "$PROXIES" ] || [ "$PROXIES" = "127.0.0.1/32,::1/128" ]; then PROXIES="$PROXIES_DEFECTO"; fi
if [ -n "${JZPASS_PROXY_IP:-}" ]; then
  case ",$PROXIES," in
    *",$JZPASS_PROXY_IP,"*|*",$JZPASS_PROXY_IP/32,"*) ;;
    *) PROXIES="$PROXIES,$JZPASS_PROXY_IP";;
  esac
fi
ADICIONALES="$(printf '%s\n' "$ADICIONALES" | grep -v '^TRUSTED_PROXIES=' || true)"
ADICIONALES="TRUSTED_PROXIES=$PROXIES${ADICIONALES:+
$ADICIONALES}"
# Origenes permitidos (CORS): los que ya estaban (o localhost) y, con dominio, https://<dominio> una sola vez.
ORIGENES="$(valor_env ALLOWED_ORIGINS)"; ORIGENES="${ORIGENES:-http://localhost:$APP_PORT}"
if [ -n "$DOMAIN" ]; then
  case ",$ORIGENES," in *",https://$DOMAIN,"*) ;; *) ORIGENES="$ORIGENES,https://$DOMAIN";; esac
fi
ZONA="$(valor_env TZ)"; ZONA="${ZONA:-${TZ:-America/Argentina/Buenos_Aires}}"
TMP_ENV="$(mktemp "$ENV_DIR/.env.XXXXXX")"
cat > "$TMP_ENV" <<EOF
# Generado por install-native.sh (se vuelve a escribir en cada instalacion; las lineas agregadas a mano
# al final se conservan). No versionar ni copiar a otro servidor tal cual.
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@127.0.0.1:5432/$DB_NAME
JWT_SECRET=$JWT_SECRET
SETUP_TOKEN=$SETUP_TOKEN
ALLOWED_ORIGINS=$ORIGENES
APP_PORT=$APP_PORT
APP_BIND=$APP_BIND
JZPASS_DOMAIN=$DOMAIN
JZPASS_INSTALACION=nativa
JZPASS_REPO_URL=$REPO_URL
TZ=$ZONA
PYTHONDONTWRITEBYTECODE=1
EOF
printf '%s\n' "$ADICIONALES" >> "$TMP_ENV"
chown root:"$APP_USER" "$TMP_ENV"
chmod 640 "$TMP_ENV"
mv -f "$TMP_ENV" "$ENV_FILE"

# 8. Version en uso y servicio systemd
ln -sfn "$DEST" "$BASE_DIR/current.tmp"
mv -Tf "$BASE_DIR/current.tmp" "$BASE_DIR/current"

echo "Escribiendo el servicio systemd..."
cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=JZPass (asistencia y RRHH)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
# La app lee index.html/dashboard.html y escribe en uploads/ (enlace a $DATOS/uploads) desde esta carpeta.
WorkingDirectory=$BASE_DIR/current
EnvironmentFile=$ENV_FILE
ExecStart=$BASE_DIR/current/venv/bin/uvicorn main:app --host $APP_BIND --port $APP_PORT --workers 1 --no-proxy-headers
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$DATOS/uploads
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
RestrictNamespaces=yes
LockPersonality=yes
SystemCallArchitectures=native
CapabilityBoundingSet=
AmbientCapabilities=
UMask=0027
MemoryMax=384M

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE" > /dev/null
systemctl restart "$SERVICE"

echo "Esperando que el servicio responda..."
OK=0
for _ in $(seq 1 45); do
  if curl -fsS --max-time 5 "http://$LOCAL:$APP_PORT/api/setup/status" > /dev/null 2>&1; then
    OK=1
    break
  fi
  sleep 2
done
if [ "$OK" != "1" ]; then
  echo "Error: el servicio no responde en http://$LOCAL:$APP_PORT." >&2
  echo "Ver el detalle con: journalctl -u $SERVICE -n 50 --no-pager" >&2
  exit 1
fi
echo "Servicio en marcha (version $VERSION)."

# 9. Actualizador
install -m 0755 "$DEST/tools/jzpass-actualizar" "$ACTUALIZADOR"

# 10. Caddy de una version anterior de este instalador: no se desinstala (puede usarlo otra app), se avisa.
CADDY_ANTERIOR=0
if command -v caddy > /dev/null 2>&1 && grep -qsE '^# (jzpass|Gestionado por los instaladores nativos de JZTech)' /etc/caddy/Caddyfile; then
  CADDY_ANTERIOR=1
fi

# 11. Resumen
ADMINS=$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT count(*) FROM usuarios WHERE rol = 0" 2>/dev/null || echo 0)
echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA - JZPass $VERSION"
echo "================================================================="
if [ "$APP_BIND" = "0.0.0.0" ]; then ESCUCHA="$IP"; else ESCUCHA="$APP_BIND"; fi
echo "Escuchando en: http://$ESCUCHA:$APP_PORT"
if [ -n "$DOMAIN" ]; then
  echo "Direccion publica: https://$DOMAIN (tiene que llegar a http://$ESCUCHA:$APP_PORT)"
fi
if [ "$ADMINS" = "0" ]; then
  echo ""
  echo "Token de configuracion inicial: $SETUP_TOKEN"
  echo "La pagina lo pide para crear el usuario administrador (sirve una sola vez)."
fi
echo ""
echo "Para actualizar mas adelante: sudo jzpass-actualizar"
if [ "$CADDY_ANTERIOR" = "1" ]; then
  echo ""
  echo "AVISO: sigue instalado el Caddy de una version anterior de este instalador (no se desinstala solo); ocupa"
  echo "los puertos 80 y 443. Si ninguna otra app lo usa (ver /etc/caddy/Caddyfile), sacarlo con:"
  echo "  sudo systemctl disable --now caddy"
  echo "  sudo apt purge caddy"
fi
echo "================================================================="
