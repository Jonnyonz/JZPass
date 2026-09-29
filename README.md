# JZPass

Sistema de recursos humanos y control de asistencia: fichaje de entrada y salida con
validación por GPS contra la sucursal, solicitudes del personal (licencias, vacaciones,
permisos) con adjuntos, medio francos, feriados y convocatorias, y un panel para
administradores y encargados con reportes en Excel. Parte de **JZTech Suite**. Software libre,
pensado para correr en una PC de oficina común.

- [Funcionalidades](#funcionalidades)
- [Detalle técnico](#detalle-técnico)
- [Instalación rápida con Docker](#instalación-rápida-con-docker)
- [Instalación nativa (sin Docker)](#instalación-nativa-sin-docker)
- [Acceso desde la red (HTTPS)](#acceso-desde-la-red-https)
- [Configuración](#configuración)
- [Operación](#operación)
- [Tests](#tests)
- [Contribuir y licencia](#contribuir-y-licencia)

---

## Funcionalidades

El ingreso es con **DNI (o legajo) y clave**. Hay tres roles (`usuarios.rol`):

| Rol | Valor | Qué puede hacer |
|---|---|---|
| Administrador | `0` | Todo, en todas las sucursales: personal, sucursales, feriados, conceptos de solicitud, configuración, logo, importación de personal por CSV, reportes. |
| Encargado | `1` | Lo mismo pero limitado a **su sucursal**: fichajes, correcciones, medio francos, convocatorias. Puede aprobar solicitudes solo si la configuración lo habilita. |
| Empleado | `2` | Fichar, ver su historial y saldo de vacaciones, crear y cancelar solicitudes. |

**Empleado** (`/`, pantalla principal):
- **Fichaje con GPS:** el navegador toma la ubicación y el servidor calcula la distancia a la
  sucursal del empleado. Si supera el límite configurado (50 m por defecto), el fichaje se
  rechaza, salvo que el "GPS estricto" esté desactivado. Marca las llegadas tarde según la
  tolerancia, evita fichajes duplicados (anti-rebote) y no deja fichar la salida antes de la
  jornada mínima.
- **Solicitudes** según los conceptos definidos por el admin (algunos exigen foto o documento
  adjunto, algunos descuentan días de vacaciones). Las vacaciones se piden con un aviso previo
  mínimo configurable.

**Panel** (`/panel`, admin y encargado), en siete secciones: Inicio, Asistencias (con salida
manual y corrección de entradas), Gestión de Solicitudes, Calendario General (feriados y
convocatorias), Medios Francos, Estructura Organizacional (identidad, sucursales, personal) y
Ajustes del Sistema (parámetros, conceptos, importación). Reporte consolidado en Excel por rango
de fechas y sucursal.

**Altas de personal:** al crear un usuario (a mano o por CSV) se genera una clave temporal que
el empleado tiene que cambiar en su primer ingreso.

---

## Detalle técnico

### Stack

| Componente | Versión |
|---|---|
| Python | 3.11 en la imagen (`python:3.11-slim`); también probado en 3.13 |
| FastAPI / Starlette | 0.141.1 / 1.7.0 |
| Uvicorn | 0.54.0 |
| asyncpg | 0.31.0 (SQL directo, sin ORM) |
| itsdangerous | 2.2.0 (tokens CSRF firmados) |
| slowapi | 0.1.10 (rate limit) |
| PostgreSQL | 15 (imagen `postgres:15-alpine`) |
| [jztech-core](https://github.com/Jonnyonz/jztech-core) | 0.1.4 (librería de seguridad común de JZTech) |

Dependencias fijadas con hash: `requirements.in` (directas) → `requirements.txt` (lockfile,
se instala con `pip install --require-hashes`).

### Estructura

```
JZPass/
├── main.py              # App: lifespan, CORS, CSRF, cabeceras, routers, index/panel
├── database.py          # Variables, pool, esquema, sesiones, claves, rate limit, utilidades
├── routers/
│   ├── auth.py          # login, logout, CSRF, cambio de clave, configuración inicial
│   ├── empleado.py      # datos del empleado, fichaje, solicitudes
│   ├── admin.py         # datos del panel, acciones de administración, reporte Excel
│   └── archivos.py      # descarga de adjuntos
├── index.html           # login + vista de empleado
├── dashboard.html       # panel de admin/encargado
├── uploads/             # adjuntos y logo (volumen en Docker)
├── install.sh           # instalador con Docker
├── install-native.sh    # instalador sin Docker (Debian/Ubuntu + systemd + Caddy)
├── docker-compose.yml, Dockerfile, .dockerignore
├── requirements.in, requirements.txt
└── conftest.py, test_*.py
```

### Modelo de datos

La app crea el esquema sola al arrancar (y agrega columnas nuevas si faltan):

| Tabla | Contenido |
|---|---|
| `usuarios` | Personal (clave: `dni`): rol, sucursal, horario, saldo de vacaciones, hash de clave, bloqueo, datos de contacto |
| `sucursales` | Nombre, coordenadas (para el GPS) y horarios, incluidos los de feriado |
| `fichajes` | Entradas y salidas con ubicación, distancia a la sucursal y llegada tarde |
| `solicitudes`, `tipos_solicitud` | Solicitudes del personal y los conceptos que las definen |
| `mediofrancos`, `feriados`, `feriados_convocados` | Medio francos, feriados (y qué sucursales abren) y personal convocado |
| `configuracion` | Una sola fila (`id=1`) con los parámetros del sistema |
| `jztech_sessions` | Sesiones abiertas: hash del token, DNI y vencimiento |

### Seguridad

- **Sesiones opacas en base:** la cookie `HttpOnly` + `Secure` + `SameSite=Strict` lleva un
  token aleatorio (7 días); en la base se guarda solo su hash SHA-256, así que una copia de la
  base no permite robar sesiones. El logout la borra, y el cambio de clave o el reset por un
  admin cierran todas las sesiones del usuario.
- **Claves con Argon2id** (parámetros mínimos de OWASP). Las claves bcrypt de versiones
  anteriores se migran solas en el primer login correcto. Política: 8+ caracteres, una
  mayúscula, dos números y un carácter especial.
- **CSRF:** cada acción (`POST`/`PUT`/`DELETE`) lleva un token firmado que se pide a
  `/api/csrf-token` y está atado al DNI de la sesión.
- **Fuerza bruta:** rate limit por IP (login 20/min; configuración inicial y cambio de clave
  5/min) y bloqueo de la cuenta tras N intentos fallidos (configurable). La IP real se toma de
  `X-Forwarded-For` solo desde los proxies de `TRUSTED_PROXIES`. Un DNI inexistente tarda lo
  mismo que uno real (no revela qué DNI existen).
- **Adjuntos:** se valida el tipo real del archivo (magic bytes), no la extensión.
- **Cabeceras:** CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`,
  HSTS y `Permissions-Policy` (geolocalización habilitada solo para el propio sitio, por el
  fichaje; cámara y micrófono bloqueados).
- **Configuración inicial con token:** el primer administrador solo se crea con el
  `SETUP_TOKEN`, y una sola vez.
- La imagen de Docker no incluye el `.env`, `.git`, el entorno virtual ni `uploads/`.

---

## Instalación rápida con Docker

Requisitos: Linux con Docker y el plugin `docker compose`, `git` y `openssl`.

### Opción A: a mano (recomendada)

```bash
git clone https://github.com/Jonnyonz/JZPass.git
cd JZPass
cp .env.example .env
# Completar en .env:
#   JWT_SECRET   -> openssl rand -hex 32   (mínimo 32 caracteres)
#   DB_PASSWORD  -> openssl rand -hex 16
#   SETUP_TOKEN  -> openssl rand -hex 24
#   ALLOWED_ORIGINS -> la URL exacta con la que se va a entrar (con puerto)
docker compose up -d --build
```

### Opción B: instalador

`install.sh` (como root) instala Docker si falta, clona el repo en `./jzpass_erp`, genera el
`.env` con secretos aleatorios y levanta los contenedores.

> **Cuidado:** `install.sh` es solo para la **primera** instalación. Cada vez que corre borra
> la carpeta `jzpass_erp` y ejecuta `docker compose down -v`, que **elimina la base de datos**.
> Para actualizar, ver [Operación](#operación).

### Primer ingreso

1. Abrir `http://localhost:8000` (o el puerto de `APP_PORT`).
2. La pantalla detecta que no hay usuarios y pide el `SETUP_TOKEN` del `.env`.
3. Crear el administrador con su DNI, nombre y clave. El token deja de servir después.
4. En el panel: cargar sucursales (con sus coordenadas: son el centro del radio de fichaje),
   conceptos de solicitud, feriados y el personal (a mano o por CSV).

> La cookie de sesión es `Secure`: por `http://` el login solo funciona entrando por
> `localhost`, y el navegador solo da la ubicación GPS en sitios seguros. Para usarlo desde
> celulares u otras PCs hace falta HTTPS (ver [Acceso desde la red](#acceso-desde-la-red-https)).

---

## Instalación nativa (sin Docker)

### Opción A: `install-native.sh` (Debian/Ubuntu)

Deja todo listo para producción en un servidor: paquetes, usuario de sistema sin login,
Postgres con clave aleatoria, entorno virtual, `/etc/jzpass/jzpass.env` (permisos `0640`),
servicio `systemd` endurecido y Caddy con HTTPS. Es idempotente (se puede volver a correr para
actualizar) y no pisa los secretos ya generados.

```bash
git clone https://github.com/Jonnyonz/JZPass.git
cd JZPass
sudo ./install-native.sh
```

Se puede ajustar con variables antes de correrlo: `JZPASS_DOMAIN` (default `jzpass.local`),
`JZPASS_PORT` (8000), `JZPASS_DIR` (`/opt/jzpass`), `JZPASS_USER`, `JZPASS_DB_NAME`,
`JZPASS_DB_USER`. Al terminar muestra el `SETUP_TOKEN`. Probado en una VM Debian 13 limpia,
login desde el navegador incluido.

Con el dominio por defecto (`jzpass.local`), Caddy usa una CA local (`tls internal`): en cada
equipo cliente hay que resolver ese nombre (DNS interno o archivo `hosts`) y confiar en la CA.

### Opción B: a mano (desarrollo)

```bash
sudo apt install -y python3 python3-venv postgresql git openssl
sudo -u postgres psql -c "CREATE USER jzadmin WITH PASSWORD 'CLAVE';"
sudo -u postgres psql -c "CREATE DATABASE jzpass_db OWNER jzadmin;"

git clone https://github.com/Jonnyonz/JZPass.git
cd JZPass
python3 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.txt

# La app no lee el .env sola: exportar las variables
export DATABASE_URL=postgresql://jzadmin:CLAVE@127.0.0.1:5432/jzpass_db
export JWT_SECRET=$(openssl rand -hex 32)
export SETUP_TOKEN=$(openssl rand -hex 24); echo "SETUP_TOKEN: $SETUP_TOKEN"
export ALLOWED_ORIGINS=http://localhost:8000

# Desde la raíz del repo (usa uploads/ y los HTML con rutas relativas)
uvicorn main:app --host 127.0.0.1 --port 8000
```

---

## Acceso desde la red (HTTPS)

`install-native.sh` ya configura Caddy. Con Docker, poner un proxy adelante; por ejemplo con
[Caddy](https://caddyserver.com/) en el mismo servidor:

```
# /etc/caddy/Caddyfile
jzpass.miempresa.com {
    reverse_proxy 127.0.0.1:8000
}
```

Y en el `.env`: `APP_BIND=127.0.0.1` (la app solo escucha en el propio servidor) y
`ALLOWED_ORIGINS=https://jzpass.miempresa.com`.

---

## Configuración

### Variables de entorno (`.env`)

| Variable | Obligatoria | Default | Para qué sirve |
|---|---|---|---|
| `JWT_SECRET` | Sí | — | Firma de los tokens CSRF (el nombre quedó de versiones anteriores, que usaban JWT). Mínimo 32 caracteres (`openssl rand -hex 32`). La app no arranca sin ella. |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | Sí (Docker) | `jzadmin` / — / `jzpass_db` | Credenciales de Postgres. Con Docker, el compose arma `DATABASE_URL` con ellas. |
| `DATABASE_URL` | Sí (sin Docker) | — | `postgresql://usuario:clave@host:puerto/base`. La app no arranca sin ella. |
| `SETUP_TOKEN` | Sí (primera vez) | vacío | Crea el primer administrador, una sola vez. Vacío = deshabilitado. |
| `ALLOWED_ORIGINS` | Sí | `http://localhost:8000` | Orígenes permitidos por CORS, separados por coma. Tiene que coincidir exacto con la URL de acceso, puerto incluido. |
| `APP_PORT` | No | `8000` | Puerto donde Docker publica la app. |
| `APP_BIND` | No | `0.0.0.0` | Interfaz donde Docker publica la app. Detrás de un proxy: `127.0.0.1`. |
| `TRUSTED_PROXIES` | No | `127.0.0.1/32,::1/128,172.16.0.0/12` | Proxies de confianza para `X-Forwarded-For` (IP real para el rate limit). |
| `TZ` | No | `America/Argentina/Buenos_Aires` | Zona horaria (afecta la hora de los fichajes). |

### Parámetros del sistema (panel → Ajustes del Sistema)

| Parámetro | Default | Para qué sirve |
|---|---|---|
| Nombre de la empresa y color primario | `JZ PASS`, `#007bff` | Identidad visual. El logo se sube desde Estructura Organizacional. |
| Distancia GPS (m) | 50 | Radio máximo alrededor de la sucursal para poder fichar. |
| GPS estricto | activado | Si se desactiva, se puede fichar fuera del radio. |
| Tolerancia de llegada tarde (min) | 10 | Minutos después del horario antes de marcar "tarde". |
| Anti-rebote (min) | 5 | Tiempo mínimo entre dos fichajes del mismo empleado. |
| Jornada mínima (h) | 3 | No se puede fichar la salida antes de cumplirla. |
| Medio franco | ingreso 15:00 / salida 12:00 | Con franco de mañana, el horario de ingreso pasa a ser las 15:00; con franco de tarde, la salida se habilita desde las 12:00. |
| Vacaciones base (días) | 14 | Saldo inicial de vacaciones de cada empleado nuevo. |
| Aviso previo de vacaciones (días) | 14 | Anticipación mínima para pedir vacaciones. |
| Intentos de login | 5 | Intentos fallidos antes de bloquear la cuenta 15 minutos. |
| Encargados aprueban | no | Si los encargados pueden aprobar solicitudes de su sucursal. |

### Importar personal por CSV

Columnas: `dni` y `nombre` (obligatorias); `rol` (0/1/2, default 2), `sucursal`,
`hora_entrada` (default `09:00`), `hora_salida` (default `18:00`) y `dias_vacaciones`
(default: vacaciones base). Si el DNI ya existe se actualizan sus datos sin tocar la clave; si
es nuevo se genera una clave temporal y el resultado de la importación muestra las credenciales.

---

## Operación

```bash
docker compose ps
docker compose logs -f jzpass-app

# Actualizar a la última versión (NO usar install.sh para esto)
git pull
docker compose up -d --build

# Backup y restauración de la base
docker compose exec -T jzpass-db pg_dump -U jzadmin jzpass_db > backup_$(date +%F).sql
docker compose exec -T jzpass-db psql -U jzadmin -d jzpass_db < backup_AAAA-MM-DD.sql

docker compose down        # detener (la base queda en el volumen pgdata)
```

Incluir también la carpeta `uploads/` (adjuntos y logo) en las copias de seguridad.

---

## Tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.txt
pip install pytest httpx
python -m pytest
```

No necesitan base de datos (`conftest.py` define variables de prueba): cubren la arquitectura
(rutas registradas, páginas servidas), el hash de claves y su migración, y las cabeceras de
seguridad. Tardan unos 2 minutos porque la app reintenta conectarse a Postgres al arrancar.

**Regenerar el lockfile** (al cambiar `requirements.in`): siempre en Linux, dentro de la misma
imagen base del Dockerfile. En Windows `pip-compile` resuelve dependencias propias de Windows y
el build de Docker falla.

```bash
docker run --rm -v "$PWD:/w" -w /w python:3.11-slim sh -c \
  "pip install pip-tools==7.4.1 && pip-compile --allow-unsafe --generate-hashes \
   --output-file=requirements.txt requirements.in"
```

---

## Contribuir y licencia

Las contribuciones son bienvenidas: ver `CONTRIBUTING.md`. Cada commit tiene que llevar `Signed-off-by`
(`git commit -s`, Developer Certificate of Origin), ser un único cambio probado y pasar los
tests. Sin emojis en la interfaz: íconos solo en SVG.

Licencia: **AGPLv3** (GNU Affero General Public License v3). Ver `LICENSE`. Si ofrecés una versión modificada como servicio en red, tenés que publicar su código fuente.
