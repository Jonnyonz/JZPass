#!/bin/bash

# ==============================================================================
# Instalador Automatizado SRE para JZ PASS
# ==============================================================================

# Detener la ejecución inmediatamente si un comando falla
set -e

echo "=================================================="
echo "Iniciando Instalador de JZ PASS ERP..."
echo "=================================================="

# 1. Verificación de privilegios
if [ "$EUID" -ne 0 ]; then
  echo "Error: Este script debe ejecutarse como root o usando sudo."
  echo "Ejemplo: sudo curl -sSL https://raw.githubusercontent.com/... | sudo bash"
  exit 1
fi

echo "Privilegios de administrador confirmados."
echo "Actualizando lista de paquetes locales..."
apt-get update -qq > /dev/null

# 2. Comprobación e instalación de dependencias base
for pkg in curl git openssl; do
  if ! command -v $pkg &> /dev/null; then
    echo "Instalando dependencia faltante: $pkg..."
    apt-get install -y -qq $pkg > /dev/null
  else
    echo "Dependencia $pkg ya está instalada."
  fi
done

# 3. Comprobación e instalación de Docker
if ! command -v docker &> /dev/null; then
  echo "Docker no encontrado. Iniciando instalación oficial de Docker..."
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh > /dev/null 2>&1
  rm get-docker.sh
  echo "Docker instalado exitosamente."
else
  echo "Docker ya está instalado."
fi

# 4. Comprobación e instalación de Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
  echo "Docker Compose no encontrado. Instalando la última versión..."
  curl -sSL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
  echo "Docker Compose instalado exitosamente."
else
  echo "Docker Compose ya está disponible."
fi

# 5. Codigo: se clona la primera vez; si ya existe, se actualiza. NUNCA se borra la carpeta:
#    ahi viven el .env y uploads/ (adjuntos de las solicitudes del personal).
REPO_URL="https://github.com/Jonnyonz/JZPass.git"
DIR_NAME="jzpass_erp"

if [ -d "$DIR_NAME/.git" ]; then
  echo "El directorio $DIR_NAME ya existe: se actualiza el codigo (git pull), sin borrar datos."
  git -C "$DIR_NAME" pull -q --ff-only
else
  echo "Descargando código fuente de JZ PASS..."
  git clone -q "$REPO_URL" "$DIR_NAME"
fi
cd "$DIR_NAME"

# Compatibilidad con sintaxis antigua y nueva de Docker Compose
compose() {
  if command -v docker-compose &> /dev/null; then docker-compose "$@"; else docker compose "$@"; fi
}

# 6. Configuracion del entorno. Si ya hay .env, se respeta (actualizacion).
SETUP_TOKEN=""
RANDOM_DB_PASS=""
if [ -f .env ]; then
  echo "Se detectó un archivo .env existente. Manteniendo configuración."
else
  # Postgres solo aplica la clave la primera vez que inicializa su volumen: un .env nuevo no
  # sirve contra la base de una instalacion anterior. Antes se borraba esa base sin preguntar;
  # ahora, si existe, no se toca nada salvo que se pida explicitamente.
  PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')}"
  VOLUME="${PROJECT}_pgdata"
  if docker volume inspect "$VOLUME" > /dev/null 2>&1; then
    if [ "${JZPASS_RESET_DB:-}" = "1" ]; then
      echo "JZPASS_RESET_DB=1: se BORRA la base de datos de la instalación anterior (volumen $VOLUME)."
      compose down -v > /dev/null 2>&1 || true
    else
      echo "ERROR: hay una base de datos de una instalación anterior (volumen $VOLUME) pero no hay .env."
      echo "No se borró nada. Opciones:"
      echo "  - Restaurar el .env de esa instalación en $PWD y volver a correr el instalador"
      echo "  - Empezar de cero BORRANDO esos datos: JZPASS_RESET_DB=1 (ej. sudo JZPASS_RESET_DB=1 bash install.sh)"
      exit 1
    fi
  fi

  echo "Generando claves criptográficas de alta entropía..."
  cp .env.example .env
  RANDOM_JWT=$(openssl rand -hex 32)
  RANDOM_DB_PASS=$(openssl rand -hex 16)
  SETUP_TOKEN=$(openssl rand -hex 24)
  sed -i "s/ingresa_una_cadena_muy_larga_y_segura_aqui/$RANDOM_JWT/g" .env
  sed -i "s/ingresa_tu_password_segura/$RANDOM_DB_PASS/g" .env
  sed -i "s/se_genera_automaticamente_al_instalar/$SETUP_TOKEN/g" .env
  chmod 600 .env
  echo "Secretos inyectados correctamente en .env."
fi

# 7. Despliegue de la Infraestructura
echo "Construyendo y levantando contenedores (Esto puede tomar unos minutos)..."
compose up -d --build --quiet-pull

# 8. Mensaje de Finalización
IP_LOCAL=$(hostname -I 2>/dev/null | awk '{print $1}')
APP_PORT_SHOWN=$(grep -E '^APP_PORT=' .env | cut -d= -f2)
echo ""
echo "================================================================="
echo "INSTALACIÓN COMPLETADA CON ÉXITO"
echo "================================================================="
echo "Acceso al sistema: http://localhost:${APP_PORT_SHOWN:-8000} (desde otras PCs hace falta HTTPS, ver README)"
[ -n "$IP_LOCAL" ] && echo "IP de este servidor: $IP_LOCAL"
if [ -n "$SETUP_TOKEN" ]; then
  echo "Token de configuración inicial: $SETUP_TOKEN"
  echo "Entrá a la URL de arriba: te va a pedir este token para crear el usuario administrador."
  echo "Se usa una sola vez (después de crear el admin, deja de servir)."
  echo "Contraseña generada para la Base de Datos: $RANDOM_DB_PASS"
  echo "IMPORTANTE: guardá el .env de $PWD en un lugar seguro (sin él no se puede reinstalar sobre esta base)."
fi
echo "Para actualizar más adelante: volver a correr este instalador (conserva datos y configuración)."
echo "================================================================="
