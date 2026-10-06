#!/bin/bash
# ==============================================================================
# Instalador con Docker de JZPass (la instalacion sin Docker es install-native.sh)
# ==============================================================================
#   sudo bash install.sh                                (clona en ./jzpass_erp; si ya existe, la ACTUALIZA)
#   sudo JZPASS_DOMAIN=rrhh.empresa.com bash install.sh  dominio publico con el que se va a entrar
#
# Instala Docker si falta, trae la ultima version (git pull --ff-only), respalda la base en backups/ antes de
# reconstruir y deja la app escuchando por http en APP_BIND:APP_PORT (por defecto 0.0.0.0:8000). No instala
# ningun proxy: el HTTPS lo pone el proxy del servidor (sin HTTPS no se guarda la sesion desde otra PC ni el
# celular da la ubicacion para fichar). Nunca borra la carpeta: ahi viven el .env y uploads/ (adjuntos del personal).
#
# Variables opcionales: JZPASS_DOMAIN (en una instalacion nueva, si no esta, se pregunta), JZPASS_BIND
# (interfaz donde escucha la app; por defecto 0.0.0.0 para que llegue el proxy), JZPASS_PROXY_IP (IP del proxy si
# esta en otro equipo: se agrega a TRUSTED_PROXIES), JZPASS_NO_UPDATE=1, JZPASS_RESET_DB=1 (borrar la base de una
# instalacion anterior cuando no hay .env).
#
# Instalaciones anteriores con Caddy (2.6.0): se sacan del .env las claves de Caddy, se borra su contenedor
# (jzpass_caddy) y la app pasa a escuchar en 0.0.0.0. Las variables de entonces (JZPASS_HTTPS, JZPASS_IP,
# JZPASS_HTTPS_PORT) se ignoran con un aviso.
# ==============================================================================
set -e

echo "=================================================="
echo "Instalador de JZPass (Docker)"
echo "=================================================="

# 1. Privilegios y dependencias
if [ "$EUID" -ne 0 ]; then
  echo "Error: correr como root (sudo bash install.sh)."
  exit 1
fi
for pkg in curl git openssl; do
  if ! command -v $pkg &> /dev/null; then
    if ! command -v apt-get &> /dev/null; then
      echo "Error: falta $pkg (instalarlo con el gestor de paquetes del sistema)."
      exit 1
    fi
    echo "Instalando $pkg..."
    apt-get update -qq > /dev/null
    apt-get install -y -qq $pkg > /dev/null
  fi
done
if ! command -v docker &> /dev/null; then
  echo "Docker no encontrado: se instala con el instalador oficial..."
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh > /dev/null 2>&1
  rm get-docker.sh
fi
if ! docker compose version &> /dev/null; then
  echo "Error: falta el plugin 'docker compose' (viene con el Docker oficial)."
  exit 1
fi
compose() { docker compose "$@"; }

# 2. Codigo: se clona la primera vez; si ya existe, se actualiza. NUNCA se borra la carpeta.
REPO_URL="${JZPASS_REPO_URL:-https://github.com/Jonnyonz/JZPass.git}"
if [ ! -f "docker-compose.yml" ] || [ ! -f "main.py" ]; then
  DIR_NAME="jzpass_erp"
  if [ ! -d "$DIR_NAME/.git" ]; then
    echo "Descargando el codigo de JZPass..."
    git clone -q "$REPO_URL" "$DIR_NAME"
  fi
  cd "$DIR_NAME"
fi
if [ -d .git ] && [ "${JZPASS_NO_UPDATE:-}" != "1" ]; then
  GIT="git -c safe.directory=$PWD"
  ANTES=$($GIT rev-parse --short HEAD)
  echo "Buscando actualizaciones..."
  if ! $GIT pull -q --ff-only; then
    echo "Error: no se pudo traer la version nueva (cambios locales en $PWD o sin conexion)."
    echo "No se toco nada: la version instalada sigue funcionando ($ANTES)."
    exit 1
  fi
  DESPUES=$($GIT rev-parse --short HEAD)
  if [ "$ANTES" = "$DESPUES" ]; then
    echo "Ya esta en la ultima version ($DESPUES)."
  else
    echo "Codigo actualizado: $ANTES -> $DESPUES (los cambios estan en CHANGELOG.md)."
    # bash sigue leyendo el install.sh que arranco: se relanza el recien bajado.
    exec env JZPASS_NO_UPDATE=1 bash ./install.sh "$@"
  fi
fi

leer() { grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '\r'; }
poner() { if grep -qE "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else printf '%s=%s\n' "$1" "$2" >> .env; fi; }

# Nombre del proyecto de compose: prefijo de los volumenes (pgdata y, en instalaciones con Caddy, caddy_*).
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')}"

# 3. .env: se genera solo la primera vez (las claves no se pisan nunca).
SETUP_TOKEN=""
NUEVA=0
if [ -f .env ]; then
  echo "Se encontro un .env: se conserva la configuracion."
else
  NUEVA=1
  # Postgres solo aplica la clave al crear su volumen: un .env nuevo no sirve contra la base de una
  # instalacion anterior. Si ese volumen existe, no se toca nada salvo que se pida explicitamente.
  VOLUME="${PROJECT}_pgdata"
  if docker volume inspect "$VOLUME" > /dev/null 2>&1; then
    if [ "${JZPASS_RESET_DB:-}" = "1" ]; then
      echo "JZPASS_RESET_DB=1: se BORRA la base de la instalacion anterior (volumen $VOLUME)."
      compose down -v > /dev/null 2>&1 || true
    else
      echo "Error: hay una base de una instalacion anterior (volumen $VOLUME) pero no hay .env."
      echo "No se borro nada. Opciones:"
      echo "  - Restaurar el .env de esa instalacion en $PWD y volver a correr el instalador"
      echo "  - Empezar de cero BORRANDO esos datos: sudo JZPASS_RESET_DB=1 bash install.sh"
      exit 1
    fi
  fi
  echo "Generando claves..."
  cp .env.example .env
  sed -i 's/\r$//' .env   # un .env.example con finales CRLF (copiado desde Windows) dejaria \r en las claves
  SETUP_TOKEN=$(openssl rand -hex 24)
  sed -i "s/ingresa_una_cadena_muy_larga_y_segura_aqui/$(openssl rand -hex 32)/g" .env
  sed -i "s/ingresa_tu_password_segura/$(openssl rand -hex 16)/g" .env
  sed -i "s/se_genera_automaticamente_al_instalar/$SETUP_TOKEN/g" .env
  chmod 600 .env
fi


# 4. Red: la app escucha por http en APP_BIND:APP_PORT; el proxy del servidor le pasa el trafico de
#    https://<dominio>.
if [ -n "${JZPASS_HTTPS:-}${JZPASS_IP:-}${JZPASS_HTTPS_PORT:-}" ]; then
  echo "Aviso: JZPASS_HTTPS, JZPASS_IP y JZPASS_HTTPS_PORT ya no se usan (ya no hay Caddy): se ignoran."
fi
# Instalaciones anteriores con Caddy (perfil "https" del compose): se sacan sus claves del .env y sus archivos.
CADDY_ANTERIOR=0
if grep -qE '^(CADDY_[A-Z_]+|JZPASS_HTTPS)=' .env || [ "$(leer COMPOSE_PROFILES)" = "https" ] \
    || docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx jzpass_caddy; then
  CADDY_ANTERIOR=1
fi
case "$(leer COMPOSE_PROFILES)" in https|"") sed -i '/^COMPOSE_PROFILES=/d' .env;; esac
sed -i -E '/^(CADDY_[A-Z_]+|JZPASS_HTTPS|JZPASS_IP)=/d' .env
rm -f caddy/Caddyfile caddy/ca-local.crt
rmdir caddy 2> /dev/null || true

DOMAIN="${JZPASS_DOMAIN:-$(leer JZPASS_DOMAIN)}"
if [ -z "$DOMAIN" ] && ! grep -qE '^JZPASS_DOMAIN=' .env; then
  # Instalaciones anteriores: el dominio puede estar en ALLOWED_ORIGINS (https://rrhh.empresa.com).
  for O in $(leer ALLOWED_ORIGINS | tr ',' ' '); do
    H="$(echo "$O" | sed -e 's#^https://##' -e 's#[:/].*$##')"
    if [[ "$O" == https://* ]] && [ "$H" != "midominio.com" ] && [ "$H" != "localhost" ] && ! [[ "$H" =~ ^[0-9.]+$ ]]; then
      DOMAIN="$H"; break
    fi
  done
fi
if [ -z "$DOMAIN" ] && [ "$NUEVA" = "1" ] && { : < /dev/tty; } 2> /dev/null; then
  read -r -p "Dominio publico de JZPass (ej. rrhh.empresa.com; Enter para entrar por la IP del servidor): " DOMAIN < /dev/tty || DOMAIN=""
fi
DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
if [ -n "$DOMAIN" ] && ! [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "Error: dominio invalido: $DOMAIN"
  exit 1
fi
poner JZPASS_DOMAIN "$DOMAIN"

# Interfaz: 0.0.0.0 para que llegue el proxy (tambien desde otro equipo). Detras de Caddy la app quedaba solo en
# 127.0.0.1: esa instalacion pasa a 0.0.0.0. Un 127.0.0.1 puesto a mano (sin Caddy) se respeta.
BIND="${JZPASS_BIND:-$(leer APP_BIND)}"
if [ -z "${JZPASS_BIND:-}" ] && { [ -z "$BIND" ] || { [ "$BIND" = "127.0.0.1" ] && [ "$CADDY_ANTERIOR" = "1" ]; }; }; then
  BIND="0.0.0.0"
fi
if ! [[ "$BIND" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: JZPASS_BIND/APP_BIND tiene que ser una IPv4 (ej. 0.0.0.0): $BIND"
  exit 1
fi
poner APP_BIND "$BIND"
PUERTO="$(leer APP_PORT)"; PUERTO="${PUERTO:-8000}"

# Proxy en otro equipo: su IP tiene que estar en TRUSTED_PROXIES para que la app vea la IP real de cada usuario
# (rate limit del login). Un proxy en este mismo servidor ya esta cubierto por las redes de Docker del default.
if [ -n "${JZPASS_PROXY_IP:-}" ]; then
  if ! [[ "$JZPASS_PROXY_IP" =~ ^[0-9A-Fa-f.:]+(/[0-9]+)?$ ]]; then
    echo "Error: JZPASS_PROXY_IP invalida: $JZPASS_PROXY_IP"
    exit 1
  fi
  PROXIES="$(leer TRUSTED_PROXIES)"; PROXIES="${PROXIES:-127.0.0.1/32,::1/128,172.16.0.0/12}"
  case ",$PROXIES," in
    *",$JZPASS_PROXY_IP,"*|*",$JZPASS_PROXY_IP/32,"*) ;;
    *) poner TRUSTED_PROXIES "$PROXIES,$JZPASS_PROXY_IP";;
  esac
fi

# Origenes permitidos (CORS): con dominio, https://<dominio> (una sola vez).
ORIGENES="$(leer ALLOWED_ORIGINS)"
if [ "$NUEVA" = "1" ]; then
  # El .env.example trae un dominio de ejemplo.
  ORIGENES="$(printf '%s' "$ORIGENES" | tr ',' '\n' | grep -vx 'https://midominio.com' | tr '\n' ',' | sed 's/,$//')"
fi
if [ -n "$DOMAIN" ]; then
  case ",$ORIGENES," in *",https://$DOMAIN,"*) ;; *) ORIGENES="${ORIGENES:+$ORIGENES,}https://$DOMAIN";; esac
fi
if [ "$ORIGENES" != "$(leer ALLOWED_ORIGINS)" ]; then poner ALLOWED_ORIGINS "$ORIGENES"; fi

IP="$(hostname -I 2> /dev/null | awk '{print $1}')"
if [ -z "$IP" ]; then IP="$(ip -4 route get 1.1.1.1 2> /dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')"; fi
IP="${IP:-<IP del servidor>}"

# 5. Copia de la base antes de reconstruir (al arrancar, la app agrega lo que falte al esquema).
if compose ps --status running --services 2>/dev/null | grep -qx jzpass-db; then
  mkdir -p backups
  COPIA="backups/antes_de_actualizar_$(date +%Y-%m-%d_%H%M%S).dump"
  # < /dev/null: con "curl ... | bash" el script llega por stdin y exec se comeria el resto.
  if compose exec -T jzpass-db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' < /dev/null > "$COPIA"; then
    chmod 600 "$COPIA"
    echo "Copia de la base de datos: $PWD/$COPIA"
  else
    rm -f "$COPIA"
    echo "Error: no se pudo copiar la base de datos; no se actualizo nada."
    exit 1
  fi
fi


# 6. Construir y levantar (--remove-orphans saca el contenedor de Caddy de las instalaciones anteriores)
echo "Construyendo y levantando los contenedores (la primera vez tarda unos minutos)..."
compose up -d --build --quiet-pull --remove-orphans
if docker ps -a --format '{{.Names}}' | grep -qx jzpass_caddy; then
  docker rm -f jzpass_caddy > /dev/null
fi
if [ "$CADDY_ANTERIOR" = "1" ]; then echo "Se saco el Caddy de la version anterior (contenedor jzpass_caddy): los puertos 80 y 443 quedaron libres."; fi

if [ "$BIND" = "0.0.0.0" ]; then PRUEBA="127.0.0.1"; else PRUEBA="$BIND"; fi
APP_OK=0
for _ in $(seq 1 45); do
  if curl -fsS --max-time 5 "http://$PRUEBA:$PUERTO/api/setup/status" > /dev/null 2>&1; then APP_OK=1; break; fi
  sleep 2
done
VOL_CADDY="$(docker volume ls -q 2> /dev/null | grep -xE "${PROJECT}_caddy_(data|config)" | tr '\n' ' ' | sed 's/ $//' || true)"

if [ "$BIND" = "0.0.0.0" ]; then ESCUCHA="$IP"; else ESCUCHA="$BIND"; fi
echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA"
echo "================================================================="
echo "Escuchando en: http://$ESCUCHA:$PUERTO"
if [ -n "$DOMAIN" ]; then
  echo "Direccion publica: https://$DOMAIN (tiene que llegar a http://$ESCUCHA:$PUERTO)"
fi
if [ "$APP_OK" != "1" ]; then
  echo "ATENCION: la app todavia no responde en http://$PRUEBA:$PUERTO. Ver: docker compose logs jzpass-app"
fi
if [ -n "$SETUP_TOKEN" ]; then
  echo ""
  echo "Token de configuracion inicial: $SETUP_TOKEN"
  echo "La pagina lo pide para crear el usuario administrador (sirve una sola vez)."
  echo "IMPORTANTE: guardar el .env de $PWD en un lugar seguro (sin el no se puede reinstalar sobre esta base)."
fi
echo "Para actualizar mas adelante: volver a correr este instalador (conserva datos, adjuntos y configuracion)."
if [ -n "$VOL_CADDY" ]; then
  echo "Quedaron los volumenes del Caddy anterior (certificados viejos). Si no se usan: docker volume rm $VOL_CADDY"
fi
echo "================================================================="
if [ "$APP_OK" != "1" ]; then exit 1; fi
