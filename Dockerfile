FROM python:3.11-slim

WORKDIR /app

# Robustez Debian: Instalamos build-essential temporalmente para compilar Bcrypt sin fallos
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias con aislamiento de caché
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Inyectar el código fuente sanitizado
COPY . .

EXPOSE 8000
