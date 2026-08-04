#!/bin/bash

# ==============================================================================
# Instalador Automatizado SRE para JZ PASS
# ==============================================================================

# Detener la ejecución inmediatamente si un comando falla
set -e

echo "=================================================="
echo "🚀 Iniciando Instalador de JZ PASS ERP..."
echo "=================================================="

# 1. Verificación de privilegios
if [ "$EUID" -ne 0 ]; then
  echo "❌ Error: Este script debe ejecutarse como root o usando sudo."
  echo "Ejemplo: sudo curl -sSL https://raw.githubusercontent.com/... | sudo bash"
  exit 1
fi

echo "✅ Privilegios de administrador confirmados."
echo "📦 Actualizando lista de paquetes locales..."
apt-get update -qq > /dev/null

# 2. Comprobación e instalación de dependencias base
for pkg in curl git openssl; do
  if ! command -v $pkg &> /dev/null; then
    echo "⚙️ Instalando dependencia faltante: $pkg..."
    apt-get install -y -qq $pkg > /dev/null
  else
    echo "✅ Dependencia $pkg ya está instalada."
  fi
done

# 3. Comprobación e instalación de Docker
if ! command -v docker &> /dev/null; then
  echo "🐳 Docker no encontrado. Iniciando instalación oficial de Docker..."
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh > /dev/null 2>&1
  rm get-docker.sh
  echo "✅ Docker instalado exitosamente."
else
  echo "✅ Docker ya está instalado."
fi

# 4. Comprobación e instalación de Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
  echo "🐙 Docker Compose no encontrado. Instalando la última versión..."
  curl -sSL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
  echo "✅ Docker Compose instalado exitosamente."
else
  echo "✅ Docker Compose ya está disponible."
fi

# 5. Clonación del Repositorio
REPO_URL="https://github.com/tu-usuario/tu-repositorio.git"
DIR_NAME="jzpass_erp"

if [ -d "$DIR_NAME" ]; then
  echo "⚠️ El directorio $DIR_NAME ya existe. Eliminándolo para asegurar una instalación limpia..."
  rm -rf "$DIR_NAME"
fi

echo "📥 Descargando código fuente de JZ PASS..."
git clone -q $REPO_URL $DIR_NAME
cd $DIR_NAME

# 6. Configuración del Entorno y Seguridad
echo "🔐 Generando claves criptográficas de alta entropía..."
cp .env.example .env

# Generación de variables aleatorias
RANDOM_JWT=$(openssl rand -hex 32)
RANDOM_DB_PASS=$(openssl rand -base64 16 | tr -d '=+/' | cut -c1-16)

# Inyección segura en el archivo .env
sed -i "s/ingresa_una_cadena_muy_larga_y_segura_aqui/$RANDOM_JWT/g" .env
sed -i "s/ingresa_tu_password_segura/$RANDOM_DB_PASS/g" .env

echo "✅ Secretos inyectados correctamente en .env."

# 7. Despliegue de la Infraestructura
echo "🏗️ Construyendo y levantando contenedores (Esto puede tomar unos minutos)..."

# Compatibilidad con sintaxis antigua y nueva de Docker Compose
if command -v docker-compose &> /dev/null; then
    docker-compose up -d --build --quiet-pull
else
    docker compose up -d --build --quiet-pull
fi

# 8. Mensaje de Finalización
IP_LOCAL=$(hostname -I | awk '{print $1}')
echo ""
echo "================================================================="
echo "🎉 INSTALACIÓN COMPLETADA CON ÉXITO"
echo "================================================================="
echo "🌐 Acceso al sistema: http://$IP_LOCAL:8000"
echo "🛢️ Contraseña generada para la Base de Datos: $RANDOM_DB_PASS"
echo "⚠️ IMPORTANTE: Guarda esta contraseña en un lugar seguro."
echo "================================================================="
