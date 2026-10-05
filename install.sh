#!/bin/bash
# ==============================================================================
# Instalador con Docker de JZPass (la instalacion sin Docker es install-native.sh)
# ==============================================================================
#   sudo bash install.sh                                (clona en ./jzpass_erp; si ya existe, la ACTUALIZA)
#   sudo JZPASS_DOMAIN=rrhh.empresa.com bash install.sh  dominio publico: certificado automatico
#
# Instala Docker si falta, trae la ultima version (git pull --ff-only), respalda la base en backups/ antes de
# reconstruir y configura HTTPS con un contenedor de Caddy (perfil "https" del compose). Sin HTTPS no se guarda
# la sesion desde otra PC ni el celular da la ubicacion para fichar. Nunca borra la carpeta: ahi viven el .env y
# uploads/ (adjuntos del personal).
#
# Variables opcionales: JZPASS_DOMAIN, JZPASS_IP (sin dominio: IP para el certificado local), JZPASS_HTTPS=no,
# JZPASS_HTTPS_PORT, JZPASS_NO_UPDATE=1, JZPASS_RESET_DB=1 (borrar la base de una instalacion anterior cuando
# no hay .env).
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

# 3. .env: se genera solo la primera vez (las claves no se pisan nunca).
SETUP_TOKEN=""
NUEVA=0
if [ -f .env ]; then
  echo "Se encontro un .env: se conserva la configuracion."
else
  NUEVA=1
  # Postgres solo aplica la clave al crear su volumen: un .env nuevo no sirve contra la base de una
  # instalacion anterior. Si ese volumen existe, no se toca nada salvo que se pida explicitamente.
  PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')}"
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
  SETUP_TOKEN=$(openssl rand -hex 24)
  sed -i "s/ingresa_una_cadena_muy_larga_y_segura_aqui/$(openssl rand -hex 32)/g" .env
  sed -i "s/ingresa_tu_password_segura/$(openssl rand -hex 16)/g" .env
  sed -i "s/se_genera_automaticamente_al_instalar/$SETUP_TOKEN/g" .env
  chmod 600 .env
fi

# 4. HTTPS con Caddy (servicio "caddy" del compose, perfil https).
HTTPS="${JZPASS_HTTPS:-$(leer JZPASS_HTTPS)}"; HTTPS="${HTTPS:-si}"
NO_SE_PUDO=0
CADDY_CORRIENDO=0
if compose ps --status running --services 2>/dev/null | grep -qx caddy; then CADDY_CORRIENDO=1; fi
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
if [ -z "$DOMAIN" ] && [ "$NUEVA" = "1" ] && [ -r /dev/tty ]; then
  read -r -p "Dominio publico de JZPass (ej. rrhh.empresa.com; Enter para usar la IP del servidor): " DOMAIN < /dev/tty || DOMAIN=""
fi
if [ "$HTTPS" = "si" ]; then
  IP="${JZPASS_IP:-$(leer JZPASS_IP)}"
  if [ -z "$DOMAIN" ] && [ -z "$IP" ]; then
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if [ -z "$IP" ]; then IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')"; fi
  fi
  if [ -z "$DOMAIN" ] && ! [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "AVISO: no se pudo saber la IP del servidor; no se configura HTTPS (indicarla con JZPASS_IP=192.168.1.10)."
    HTTPS="no"; NO_SE_PUDO=1
  fi
fi
if [ "$HTTPS" = "si" ]; then
  # Un puerto esta "ocupado" si lo usa otro programa (el Caddy de esta instalacion no cuenta).
  ocupado() { [ "$CADDY_CORRIENDO" = "0" ] && command -v ss > /dev/null && [ -n "$(ss -ltnH "( sport = :$1 )" 2>/dev/null)" ]; }
  PUERTO_HTTPS="${JZPASS_HTTPS_PORT:-$(leer CADDY_HTTPS_PORT)}"
  if [ -z "$PUERTO_HTTPS" ]; then
    for P in 443 8443 9443 10443; do
      PUERTO_HTTPS="$P"
      if ! ocupado "$P"; then break; fi
    done
  fi
  if ocupado "$PUERTO_HTTPS"; then
    echo "AVISO: el puerto $PUERTO_HTTPS ya esta en uso; no se configura HTTPS (elegir otro con JZPASS_HTTPS_PORT=...)."
    HTTPS="no"; NO_SE_PUDO=1
  fi
fi
if [ "$HTTPS" = "si" ]; then
  if grep -qE '^CADDY_HTTP_PORT=' .env; then
    PUERTO_HTTP="$(leer CADDY_HTTP_PORT)"; BIND_HTTP="$(leer CADDY_HTTP_BIND)"
  elif [ "$PUERTO_HTTPS" = "443" ] && ! ocupado 80; then
    PUERTO_HTTP=80; BIND_HTTP=0.0.0.0
  else
    PUERTO_HTTP=""; BIND_HTTP=127.0.0.1
  fi
  if [ -n "$DOMAIN" ]; then HOST="$DOMAIN"; else HOST="$IP"; fi
  SITIO="https://$HOST"
  if [ "$PUERTO_HTTPS" != "443" ]; then SITIO="$SITIO:$PUERTO_HTTPS"; fi
  mkdir -p caddy
  {
    # default_sni: por IP el navegador no manda el nombre del sitio (SNI) y Caddy, dentro del contenedor, no ve
    # la IP del servidor: sin esto no sabe que certificado dar y corta la conexion.
    GLOBALES=""
    if [ "$PUERTO_HTTP" != "80" ] || [ "$PUERTO_HTTPS" != "443" ]; then GLOBALES="${GLOBALES}	auto_https disable_redirects
"; fi
    if [ -z "$DOMAIN" ]; then GLOBALES="${GLOBALES}	default_sni $IP
"; fi
    if [ -n "$GLOBALES" ]; then printf '{\n%s}\n\n' "$GLOBALES"; fi
    echo "# Generado por install.sh: se vuelve a escribir en cada corrida (no editar a mano)."
    if [ -n "$DOMAIN" ]; then
      printf '%s {\n\treverse_proxy jzpass-app:8000\n}\n' "$DOMAIN"
    else
      printf 'https://%s, https://localhost {\n\ttls internal\n\treverse_proxy jzpass-app:8000\n}\n' "$IP"
    fi
  } > caddy/Caddyfile
  poner JZPASS_HTTPS si
  poner JZPASS_DOMAIN "$DOMAIN"
  poner JZPASS_IP "$IP"
  poner COMPOSE_PROFILES https
  poner CADDY_HTTPS_PORT "$PUERTO_HTTPS"
  poner CADDY_HTTP_PORT "$PUERTO_HTTP"
  poner CADDY_HTTP_BIND "$BIND_HTTP"
  ORIGENES="$(leer ALLOWED_ORIGINS)"
  case ",$ORIGENES," in *",$SITIO,"*) ;; *) poner ALLOWED_ORIGINS "${ORIGENES:+$ORIGENES,}$SITIO";; esac
  # Instalacion nueva: la app solo en el propio servidor (se entra por Caddy). Las existentes no se cambian.
  if [ "$NUEVA" = "1" ]; then poner APP_BIND 127.0.0.1; fi
else
  # "no" queda guardado solo si lo eligio el usuario; si no se pudo (puertos o IP), se reintenta la proxima vez.
  if [ "$NO_SE_PUDO" != "1" ]; then poner JZPASS_HTTPS no; fi
  poner COMPOSE_PROFILES ""
  if [ "$CADDY_CORRIENDO" = "1" ]; then compose --profile https stop caddy > /dev/null 2>&1 || true; fi
fi

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

# 6. Construir y levantar
echo "Construyendo y levantando los contenedores (la primera vez tarda unos minutos)..."
compose up -d --build --quiet-pull

APP_PORT_SHOWN="$(leer APP_PORT)"; APP_PORT_SHOWN="${APP_PORT_SHOWN:-8000}"
HTTPS_OK=0
if [ "$HTTPS" = "si" ]; then
  for _ in $(seq 1 45); do
    if curl -fsSk --max-time 5 --resolve "$HOST:$PUERTO_HTTPS:127.0.0.1" "https://$HOST:$PUERTO_HTTPS/api/setup/status" > /dev/null 2>&1; then
      HTTPS_OK=1; break
    fi
    sleep 2
  done
  if [ -z "$DOMAIN" ]; then
    compose cp caddy:/data/caddy/pki/authorities/local/root.crt caddy/ca-local.crt > /dev/null 2>&1 || true
  fi
fi

echo ""
echo "================================================================="
echo "INSTALACION COMPLETADA"
echo "================================================================="
if [ "$HTTPS" = "si" ]; then
  echo "Entrar desde el navegador: $SITIO"
else
  echo "Entrar desde el navegador: http://localhost:${APP_PORT_SHOWN} (en este servidor)"
fi
if [ -n "$SETUP_TOKEN" ]; then
  echo ""
  echo "Token de configuracion inicial: $SETUP_TOKEN"
  echo "La pagina lo pide para crear el usuario administrador (sirve una sola vez)."
  echo "IMPORTANTE: guardar el .env de $PWD en un lugar seguro (sin el no se puede reinstalar sobre esta base)."
fi
echo "Para actualizar mas adelante: volver a correr este instalador (conserva datos, adjuntos y configuracion)."
echo ""
echo "------------------------------ AVISO HTTPS ------------------------------"
if [ "$HTTPS" = "si" ]; then
  echo "Se configuro HTTPS con Caddy (contenedor jzpass_caddy): $SITIO"
  if [ "$HTTPS_OK" != "1" ]; then
    echo "ATENCION: el HTTPS todavia no responde. Ver: docker compose logs caddy"
  fi
  if [ -n "$DOMAIN" ]; then
    echo "- El certificado lo saca Caddy solo: $DOMAIN tiene que apuntar a este servidor y los puertos 80 y"
    echo "  443 tienen que llegar desde internet."
  else
    echo "- Sin dominio, el certificado es de la CA local de Caddy: el navegador avisa que la conexion no es"
    echo "  privada hasta que se instala en cada PC y celular el certificado raiz:"
    echo "  $PWD/caddy/ca-local.crt (o aceptar la excepcion del navegador para probar)."
    echo "- Para usar un dominio: sudo JZPASS_DOMAIN=rrhh.empresa.com bash install.sh"
  fi
  if [ "$PUERTO_HTTPS" != "443" ]; then
    echo "- El puerto 443 lo usa otro programa de este servidor: HTTPS quedo en el $PUERTO_HTTPS."
  fi
  echo "- Para no usar HTTPS: sudo JZPASS_HTTPS=no bash install.sh"
else
  echo "HTTPS desactivado: se entra por http en el puerto ${APP_PORT_SHOWN}."
  echo "Desde otra PC o el celular no se puede iniciar sesion ni fichar por http (cookie Secure y GPS)."
  echo "Para activarlo: sudo JZPASS_HTTPS=si bash install.sh"
fi
echo "================================================================="
