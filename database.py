import os
import asyncio
import secrets
import ipaddress
import jwt
import asyncpg
from contextlib import asynccontextmanager
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from itsdangerous import URLSafeTimedSerializer
from jztech_core.passwords import hash_password, needs_rehash, verify_legacy_password, verify_password
from slowapi import Limiter


def _requerir_env(nombre: str) -> str:
    valor = os.environ.get(nombre)
    if not valor:
        raise RuntimeError(
            f"Falta la variable de entorno obligatoria '{nombre}'. "
            f"Configurala en tu archivo .env antes de levantar el servicio (ver .env.example)."
        )
    return valor


SECRET_KEY = _requerir_env("JWT_SECRET")
if len(SECRET_KEY) < 32:
    raise RuntimeError("JWT_SECRET debe tener al menos 32 caracteres. Generá uno con: openssl rand -hex 32")

ORIGINES_PERMITIDOS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:8000").split(",")
SETUP_TOKEN = os.environ.get("SETUP_TOKEN", "")
# Hash de relleno para usuarios inexistentes en el login: se verifica igual para que el tiempo
# de respuesta no revele si el DNI existe. Argon2id, como las claves reales.
DUMMY_HASH = hash_password(secrets.token_hex(16))
DATABASE_URL = _requerir_env("DATABASE_URL")

# X-Forwarded-For solo se cree si la conexion viene de un proxy de confianza. Antes se tomaba
# el primer valor de XFF sin validar (falsificable), lo que permitia evadir el rate limit.
def _parse_networks(raw):
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if not part: continue
        try: nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError: print(f"[JZPass] TRUSTED_PROXIES: valor invalido ignorado: {part}")
    return nets

TRUSTED_PROXIES = _parse_networks(os.environ.get("TRUSTED_PROXIES", "127.0.0.1/32,::1/128,172.16.0.0/12"))

def _is_trusted_proxy(ip):
    try: addr = ipaddress.ip_address(ip)
    except ValueError: return False
    return any(addr in net for net in TRUSTED_PROXIES)

def get_real_ip(request: Request):
    peer = request.client.host if request.client else "127.0.0.1"
    if not _is_trusted_proxy(peer):
        return peer
    forwarded = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
    for hop in reversed(forwarded):
        if not _is_trusted_proxy(hop):
            return hop
    return forwarded[0] if forwarded else peer

limiter = Limiter(key_func=get_real_ip)

# Se asigna en el lifespan de main.py (necesita SECRET_KEY, que ya esta disponible aca).
csrf_signer = URLSafeTimedSerializer(SECRET_KEY)


def check_magic_bytes(raw_bytes: bytes):
    if raw_bytes.startswith(b'%PDF'): return 'pdf'
    if raw_bytes.startswith(b'\xff\xd8'): return 'jpg'
    if raw_bytes.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    return None


# === CONEXION A LA BASE ===
class DB:
    pool = None


async def init_db_schema():
    """Crea las tablas (idempotente) y el pool de conexiones. Reintenta la conexion
    inicial; si Postgres sigue sin responder despues de los reintentos, sigue con
    DB.pool=None en vez de crashear el arranque completo (get_db() devuelve 503
    mientras tanto). Esto tambien permite correr el smoke test de arquitectura
    (test_architecture.py) sin una Postgres real."""
    os.makedirs("uploads", exist_ok=True)

    conn = None
    for _ in range(15):
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            break
        except Exception as e:
            print(f"[JZPass] Intento de conexion a PostgreSQL fallido: {e!r}")
            await asyncio.sleep(2)

    if conn is None:
        print("[JZPass] No se pudo conectar a PostgreSQL: la API respondera 503 hasta reiniciar el servicio.")
        return

    async with conn.transaction():
        await conn.execute('''CREATE TABLE IF NOT EXISTS configuracion (id INTEGER PRIMARY KEY, empresa_nombre TEXT, color_primario TEXT, distancia_gps REAL, tolerancia_tarde INTEGER, anti_rebote_min INTEGER, vac_anticipo_dias INTEGER, intentos_login INTEGER)''')
        await conn.execute("INSERT INTO configuracion (id, empresa_nombre, color_primario, distancia_gps, tolerancia_tarde, anti_rebote_min, vac_anticipo_dias, intentos_login) VALUES (1, 'JZ PASS', '#007bff', 50.0, 10, 5, 14, 5) ON CONFLICT (id) DO NOTHING")

        nuevas_columnas = {
            "jornada_minima_hs": "REAL DEFAULT 3.0",
            "franco_manana_ingreso": "TEXT DEFAULT '15:00'",
            "franco_tarde_salida": "TEXT DEFAULT '12:00'",
            "vacaciones_base": "INTEGER DEFAULT 14",
            "gps_estricto": "INTEGER DEFAULT 1",
            "encargados_aprueban": "INTEGER DEFAULT 0",
            "pw_prefijo": "TEXT DEFAULT 'Jz'",
            "pw_sufijo": "TEXT DEFAULT '*'"
        }
        for col, tipo in nuevas_columnas.items():
            try: await conn.execute(f"ALTER TABLE configuracion ADD COLUMN IF NOT EXISTS {col} {tipo}")
            except Exception: pass

        await conn.execute('''CREATE TABLE IF NOT EXISTS tipos_solicitud (nombre TEXT PRIMARY KEY, tipo TEXT, requiere_foto INTEGER, descuenta_dias INTEGER, horas_por_dia REAL)''')
        await conn.execute("INSERT INTO tipos_solicitud VALUES ('TRAMITE', 'HORAS', 0, 0, 0) ON CONFLICT (nombre) DO NOTHING")
        await conn.execute("INSERT INTO tipos_solicitud VALUES ('MEDICO', 'HORAS', 1, 0, 0) ON CONFLICT (nombre) DO NOTHING")
        await conn.execute("INSERT INTO tipos_solicitud VALUES ('VACACIONES', 'DIAS', 0, 1, 0) ON CONFLICT (nombre) DO NOTHING")
        await conn.execute("INSERT INTO tipos_solicitud VALUES ('LICENCIA MEDICA', 'DIAS', 1, 0, 10) ON CONFLICT (nombre) DO NOTHING")

        await conn.execute('''CREATE TABLE IF NOT EXISTS sucursales (nombre TEXT PRIMARY KEY, lat REAL, lon REAL, hora_cierre TEXT DEFAULT '20:00', hora_apertura_feriado TEXT DEFAULT '10:00', hora_cierre_feriado TEXT DEFAULT '14:00')''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS usuarios (dni TEXT PRIMARY KEY, nombre TEXT, rol INTEGER, sucursal TEXT, password TEXT, req_cambio INTEGER DEFAULT 1, intentos INTEGER DEFAULT 0, bloqueado_hasta TEXT, activo INTEGER DEFAULT 1, hora_entrada TEXT DEFAULT '09:00', hora_salida TEXT DEFAULT '18:00', dias_vacaciones INTEGER DEFAULT 14, calle TEXT DEFAULT '', altura TEXT DEFAULT '', depto TEXT DEFAULT '', cp TEXT DEFAULT '', mail TEXT DEFAULT '', telefono TEXT DEFAULT '', mapa TEXT DEFAULT '')''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS fichajes (id SERIAL PRIMARY KEY, dni TEXT, sucursal TEXT, fecha_hora TEXT, lat REAL, lon REAL, distancia REAL, tarde INTEGER DEFAULT 0, salida_manual TEXT, motivo_salida TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS mediofrancos (id SERIAL PRIMARY KEY, dni TEXT, fecha TEXT, asignado_por TEXT, turno TEXT DEFAULT 'MAÑANA')''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS feriados (fecha TEXT PRIMARY KEY, nombre TEXT, sucs_abren TEXT DEFAULT 'TODAS')''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS feriados_convocados (dni TEXT, fecha TEXT, PRIMARY KEY(dni, fecha))''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS token_blacklist (jti TEXT PRIMARY KEY, expires TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS solicitudes (id SERIAL PRIMARY KEY, dni TEXT, fecha_ausencia TEXT, horas REAL, motivo TEXT, estado TEXT DEFAULT 'PENDIENTE', archivo TEXT, fecha_carga TEXT, hora_inicio TEXT DEFAULT '', hora_fin TEXT DEFAULT '', concepto TEXT DEFAULT 'TRAMITE', fecha_fin TEXT DEFAULT '')''')

        # Migraciones Múltiples de Integridad
        try: await conn.execute("ALTER TABLE fichajes ADD COLUMN IF NOT EXISTS motivo_entrada TEXT DEFAULT ''")
        except Exception: pass
        try: await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS fecha_baja TEXT DEFAULT NULL")
        except Exception: pass
        # Epoca de sesion: va en el JWT y se compara en cada request; al cambiar/resetear la
        # clave se incrementa, invalidando TODAS las sesiones activas del usuario (no solo una).
        try: await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS sess_epoch INTEGER DEFAULT 0")
        except Exception: pass

    await conn.close()

    DB.pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=25)


async def close_db_pool():
    if DB.pool is not None:
        await DB.pool.close()


@asynccontextmanager
async def get_db():
    if DB.pool is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    async with DB.pool.acquire() as connection:
        yield connection


def verify_pw(plain: str, hashed: str) -> bool:
    # Argon2id (actual) o bcrypt (legado, se re-hashea a Argon2id en el login: ver
    # pw_necesita_rehash). Cualquier otro formato no valida: las cuentas heredadas en texto
    # plano o SHA-256 sin sal requieren que un admin resetee la clave.
    if not hashed: return False
    if hashed.startswith("$argon2"):
        return verify_password(plain, hashed)
    try:
        return verify_legacy_password(plain, hashed)
    except ValueError as e:
        # Hash bcrypt malformado en la base: no valida, y queda registrado para revisarlo.
        print(f"[JZPass] Hash de clave con formato invalido: {e!r}")
        return False


def hash_pw(pw: str) -> str: return hash_password(pw)


def pw_necesita_rehash(hashed: str) -> bool:
    # True si el hash es de un esquema viejo (bcrypt) o de Argon2id con parametros desactualizados.
    return not hashed.startswith("$argon2") or needs_rehash(hashed)


# Clave provisoria aleatoria (se muestra una sola vez y siempre con req_cambio=1).
def gen_temp_pw() -> str: return secrets.token_urlsafe(9)


async def get_current_user(request: Request, allow_req_cambio: bool = False):
    token = request.cookies.get("session_token")
    if not token: return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        async with get_db() as db:
            if await db.fetchval("SELECT 1 FROM token_blacklist WHERE jti=$1", payload.get("jti")): return None
            u = await db.fetchrow("SELECT activo, req_cambio, sess_epoch FROM usuarios WHERE dni=$1", payload.get("dni"))
            if not u or u['activo'] == 0 or (u['req_cambio'] == 1 and not allow_req_cambio): return None
            if payload.get("se", 0) != (u['sess_epoch'] or 0): return None
        return payload
    except jwt.PyJWTError: return None


async def check_admin(request: Request, check_encargado=False):
    user = await get_current_user(request)
    if not user: return None, JSONResponse(status_code=401, content={"msg": "No autorizado"})
    async with get_db() as db:
        adm = await db.fetchrow("SELECT * FROM usuarios WHERE dni=$1", user['dni'])
        if not adm or (adm['rol'] != 0 and not (check_encargado and adm['rol'] == 1)): return None, JSONResponse(status_code=403, content={"msg": "Privilegios insuficientes"})
        return dict(adm), None
