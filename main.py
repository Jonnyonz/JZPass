from fastapi import FastAPI, Form, Request, Response, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from itsdangerous import URLSafeTimedSerializer
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import asyncpg, bcrypt, jwt, math, csv, io, os, uuid, hmac, hashlib, re, asyncio
from datetime import datetime, timedelta, timezone

SECRET_KEY = os.environ.get("JWT_SECRET", "REDACTED_JWT_SECRET")
if len(SECRET_KEY) < 32:
    SECRET_KEY = SECRET_KEY + "_PRODUCCION_BLINDADA_JZPASS_ENTERPRISE"

ORIGINES_PERMITIDOS = os.environ.get("ALLOWED_ORIGINS", "https://midominio.com,http://localhost:8000").split(",")
DUMMY_HASH = "$2b$12$7kBL9RIn.u8V5Nenx6OqfOQCm8vU098S/w29w/vXW7u8i19m1W9m." 
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jzadmin:REDACTED_PASSWORD@jzpass-db:5432/jzpass_db")

def get_real_ip(request: Request):
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else "127.0.0.1").split(",")[0]

limiter = Limiter(key_func=get_real_ip)
csrf_signer = None

def check_magic_bytes(raw_bytes: bytes):
    if raw_bytes.startswith(b'%PDF'): return 'pdf'
    if raw_bytes.startswith(b'\xff\xd8'): return 'jpg'
    if raw_bytes.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global SECRET_KEY, csrf_signer
    csrf_signer = URLSafeTimedSerializer(SECRET_KEY)
    os.makedirs("uploads", exist_ok=True)
    
    for _ in range(15):
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            break
        except Exception:
            await asyncio.sleep(2)
    else:
        conn = await asyncpg.connect(DATABASE_URL)
        
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
        
        # 🛡️ Migraciones Múltiples de Integridad
        try: await conn.execute("ALTER TABLE fichajes ADD COLUMN IF NOT EXISTS motivo_entrada TEXT DEFAULT ''")
        except Exception: pass
        try: await conn.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS fecha_baja TEXT DEFAULT NULL")
        except Exception: pass
        
    await conn.close()
    
    app.state.db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=25)
    yield
    await app.state.db_pool.close()

app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware, 
    allow_origins=ORIGINES_PERMITIDOS, 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.method == "POST" and request.url.path not in ["/api/login"]:
        token = request.headers.get("X-CSRF-Token")
        try: csrf_signer.loads(token, max_age=604800)
        except Exception: return JSONResponse(status_code=403, content={"msg": "CSRF Token inválido o expirado."})
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@asynccontextmanager
async def get_db():
    async with app.state.db_pool.acquire() as conn:
        yield conn

def verify_pw(plain: str, hashed: str) -> bool:
    if not hashed: return False
    try:
        if hashed.startswith('$2b$') or hashed.startswith('$2a$'):
            return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception: pass
    if hashed.startswith('Jz') or len(hashed) < 25:
        return hmac.compare_digest(plain, hashed)
    legacy_sha = hashlib.sha256(plain.encode('utf-8')).hexdigest()
    return hmac.compare_digest(legacy_sha, hashed)

def hash_pw(pw: str) -> str: return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

async def get_current_user(request: Request, allow_req_cambio: bool = False):
    token = request.cookies.get("session_token")
    if not token: return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        async with get_db() as db:
            if await db.fetchval("SELECT 1 FROM token_blacklist WHERE jti=$1", payload.get("jti")): return None
            u = await db.fetchrow("SELECT activo, req_cambio FROM usuarios WHERE dni=$1", payload.get("dni"))
            if not u or u['activo'] == 0 or (u['req_cambio'] == 1 and not allow_req_cambio): return None
        return payload
    except jwt.PyJWTError: return None

def calc_dist(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()

@app.get("/panel", response_class=HTMLResponse)
async def panel():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()

@app.get("/api/csrf-token")
async def get_csrf(request: Request):
    user = await get_current_user(request, allow_req_cambio=True)
    return {"token": csrf_signer.dumps(user['dni']) if user else ""}

@app.post("/api/login")
@limiter.limit("20/minute")
async def login(request: Request, response: Response, dni: str = Form(...), password: str = Form(...)):
    dni = dni.strip()
    password = password.strip()
    try:
        async with get_db() as db:
            cfg = await db.fetchrow("SELECT intentos_login FROM configuracion WHERE id=1")
            max_intentos = cfg['intentos_login'] if cfg else 5

            u = await db.fetchrow("SELECT * FROM usuarios WHERE dni=$1", dni)
            if not u:
                await asyncio.to_thread(bcrypt.checkpw, password.encode('utf-8'), DUMMY_HASH.encode('utf-8'))
                return JSONResponse(status_code=400, content={"msg": "Credenciales inválidas."})
            if u['activo'] == 0: return JSONResponse(status_code=403, content={"msg": "Usuario inactivo."})
            
            bloqueado = u['bloqueado_hasta']
            if bloqueado and str(bloqueado).strip() != "":
                try:
                    if datetime.now() < datetime.strptime(str(bloqueado), "%Y-%m-%d %H:%M:%S"):
                        return JSONResponse(status_code=403, content={"msg": "Cuenta bloqueada temporalmente."})
                except ValueError: pass
                
            if not u['password'] or str(u['password']).strip() == "":
                return JSONResponse(status_code=400, content={"msg": "Cuenta sin clave configurada."})
                
            pw_correcto = await asyncio.to_thread(verify_pw, password, str(u['password']))
            if not pw_correcto:
                intentos_actuales = u['intentos'] if u['intentos'] is not None else 0
                i = intentos_actuales + 1
                if i >= max_intentos:
                    bloqueo_time = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
                    await db.execute("UPDATE usuarios SET intentos=$1, bloqueado_hasta=$2 WHERE dni=$3", i, bloqueo_time, dni)
                    return JSONResponse(status_code=403, content={"msg": "Bloqueo temporal por intentos fallidos."})
                await db.execute("UPDATE usuarios SET intentos=$1 WHERE dni=$2", i, dni)
                return JSONResponse(status_code=400, content={"msg": f"Clave incorrecta. Intentos restantes: {max_intentos-i}"})
                
            if not str(u['password']).startswith('$2b$'):
                nuevo_hash = await asyncio.to_thread(hash_pw, password)
                await db.execute("UPDATE usuarios SET password=$1 WHERE dni=$2", nuevo_hash, dni)

            await db.execute("UPDATE usuarios SET intentos=0, bloqueado_hasta=NULL WHERE dni=$1", dni)
            
            token = jwt.encode({"dni": dni, "exp": datetime.now(timezone.utc) + timedelta(days=7), "jti": str(uuid.uuid4())}, SECRET_KEY, algorithm="HS256")
            if isinstance(token, bytes): token = token.decode('utf-8')
            response.set_cookie(key="session_token", value=token, httponly=True, secure=True, samesite="strict")
            return {"msg": "ok", "req_cambio": u['req_cambio'] or 0, "rol": u['rol'] or 2}
    except Exception as e:
        return JSONResponse(status_code=500, content={"msg": f"Error de consistencia interna: {str(e)}"})

@app.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            async with get_db() as db: 
                await db.execute("INSERT INTO token_blacklist (jti, expires) VALUES ($1,$2) ON CONFLICT DO NOTHING", payload['jti'], str(payload['exp']))
        except jwt.PyJWTError: pass
    response.delete_cookie("session_token")
    return {"msg": "ok"}

@app.post("/api/cambiar_clave")
@limiter.limit("5/minute")
async def cambiar_clave(request: Request, response: Response, nueva: str = Form(...)):
    token = request.cookies.get("session_token")
    if not token: return JSONResponse(status_code=401, content={"msg": "No autorizado"})
    try: payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError: return JSONResponse(status_code=401, content={"msg": "Token inválido."})
    
    nueva = nueva.strip()
    if len(nueva) < 8: return JSONResponse(status_code=400, content={"msg": "Mínimo 8 caracteres."})
    if not re.search(r'[A-Z]', nueva): return JSONResponse(status_code=400, content={"msg": "Mínimo 1 mayúscula."})
    if len(re.findall(r'\d', nueva)) < 2: return JSONResponse(status_code=400, content={"msg": "Mínimo 2 números."})
    if not re.search(r'[^a-zA-Z0-9]', nueva): return JSONResponse(status_code=400, content={"msg": "Mínimo 1 carácter especial."})
        
    async with get_db() as db:
        hashed_pw = await asyncio.to_thread(hash_pw, nueva)
        async with db.transaction():
            await db.execute("UPDATE usuarios SET password=$1, req_cambio=0 WHERE dni=$2", hashed_pw, payload['dni'])
            await db.execute("INSERT INTO token_blacklist (jti, expires) VALUES ($1,$2) ON CONFLICT DO NOTHING", payload['jti'], str(payload['exp']))
        
    new_token = jwt.encode({"dni": payload['dni'], "exp": datetime.now(timezone.utc) + timedelta(days=7), "jti": str(uuid.uuid4())}, SECRET_KEY, algorithm="HS256")
    if isinstance(new_token, bytes): new_token = new_token.decode('utf-8')
    response.set_cookie(key="session_token", value=new_token, httponly=True, secure=True, samesite="strict")
    return {"msg": "ok"}

@app.get("/api/empleado/datos")
async def emp_datos(request: Request):
    user = await get_current_user(request)
    if not user: return JSONResponse(status_code=401, content={})
    async with get_db() as db:
        u = await db.fetchrow("SELECT nombre, rol, sucursal, dias_vacaciones FROM usuarios WHERE dni=$1", user['dni'])
        sol = [dict(r) for r in await db.fetch("SELECT * FROM solicitudes WHERE dni=$1 ORDER BY id DESC", user['dni'])]
        fer = [dict(r) for r in await db.fetch("SELECT fecha, nombre FROM feriados")]
        fran = [dict(r) for r in await db.fetch("SELECT fecha, turno FROM mediofrancos WHERE dni=$1", user['dni'])]
        cfg_row = await db.fetchrow("SELECT * FROM configuracion WHERE id=1")
        cfg = dict(cfg_row) if cfg_row else {}
        tipos = [dict(r) for r in await db.fetch("SELECT * FROM tipos_solicitud")]
        
        mis_emp = []
        mis_conv = []
        mis_francos = []
        mis_solic = []
        
        if u['rol'] == 1:
            mis_emp = [dict(r) for r in await db.fetch("SELECT dni, nombre FROM usuarios WHERE sucursal=$1 AND activo=1", u['sucursal'])]
            mis_conv = [dict(r) for r in await db.fetch("SELECT fc.* FROM feriados_convocados fc JOIN usuarios u ON fc.dni=u.dni WHERE u.sucursal=$1", u['sucursal'])]
            mis_francos = [dict(r) for r in await db.fetch("SELECT m.fecha, m.turno, u.nombre FROM mediofrancos m JOIN usuarios u ON m.dni=u.dni WHERE u.sucursal=$1", u['sucursal'])]
            mis_solic = [dict(r) for r in await db.fetch("SELECT s.fecha_ausencia, s.fecha_fin, s.concepto, u.nombre FROM solicitudes s JOIN usuarios u ON s.dni=u.dni WHERE u.sucursal=$1 AND s.estado='APROBADA'", u['sucursal'])]
            
        return {"nombre": u['nombre'], "rol": u['rol'], "sucursal": u['sucursal'], "dias_vacaciones": u['dias_vacaciones'], "solicitudes": sol, "feriados": fer, "francos": fran, "config": cfg, "tipos_solicitud": tipos, "mis_empleados": mis_emp, "mis_convocatorias": mis_conv, "loc_francos": mis_francos, "loc_solic": mis_solic}

@app.post("/api/fichar")
@limiter.limit("10/minute")
async def fichar(request: Request, lat: float = Form(...), lon: float = Form(...)):
    user = await get_current_user(request)
    if not user: return JSONResponse(status_code=401, content={})
    async with get_db() as db:
        cfg_row = await db.fetchrow("SELECT * FROM configuracion WHERE id=1")
        cfg = dict(cfg_row) if cfg_row else {'distancia_gps': 50, 'anti_rebote_min': 5, 'tolerancia_tarde': 10, 'jornada_minima_hs': 3.0, 'franco_manana_ingreso': '15:00', 'franco_tarde_salida': '12:00', 'gps_estricto': 1}
        hoy = datetime.now().strftime("%Y-%m-%d")
        
        ult_registro = await db.fetchrow("SELECT fecha_hora FROM fichajes WHERE dni=$1 ORDER BY id DESC LIMIT 1", user['dni'])
        if ult_registro:
            tdelta_global = (datetime.now() - datetime.strptime(ult_registro['fecha_hora'], "%Y-%m-%d %H:%M:%S")).total_seconds()
            if tdelta_global < (cfg.get('anti_rebote_min', 5) * 60):
                return JSONResponse(status_code=403, content={"msg": f"Sistema anti-rebote en curso. Aguarde {cfg.get('anti_rebote_min', 5)} minutos."})
        
        lic = await db.fetchrow("SELECT s.concepto FROM solicitudes s JOIN tipos_solicitud ts ON s.concepto=ts.nombre WHERE s.dni=$1 AND ts.tipo='DIAS' AND s.estado='APROBADA' AND $2 BETWEEN s.fecha_ausencia AND s.fecha_fin", user['dni'], hoy)
        if lic: return JSONResponse(status_code=403, content={"msg": f"Usuario bajo concepto: {lic['concepto']}."})

        u = await db.fetchrow("SELECT sucursal, activo, hora_entrada FROM usuarios WHERE dni=$1", user['dni'])
        if u['activo'] == 0: return JSONResponse(status_code=403, content={"msg": "Usuario inactivo."})
        
        ult_hoy = await db.fetchrow("SELECT id, fecha_hora, salida_manual FROM fichajes WHERE dni=$1 AND fecha_hora LIKE $2 ORDER BY id DESC LIMIT 1", user['dni'], f"{hoy}%")
        suc = await db.fetchrow("SELECT lat, lon, hora_apertura_feriado FROM sucursales WHERE nombre=$1", u['sucursal'])
        
        dist = calc_dist(lat, lon, suc['lat'], suc['lon'])
        is_fuera_rango = dist > cfg.get('distancia_gps', 50)
        
        if is_fuera_rango and cfg.get('gps_estricto', 1) == 1: 
            return JSONResponse(status_code=403, content={"msg": f"Fuera de rango establecido ({int(dist)}m. Límite: {int(cfg.get('distancia_gps', 50))}m)"})
        
        fer = await db.fetchrow("SELECT sucs_abren FROM feriados WHERE fecha=$1", hoy)
        es_feriado_abierto = fer and (fer['sucs_abren'] == 'TODAS' or u['sucursal'] in fer['sucs_abren'])
        franco = await db.fetchrow("SELECT turno FROM mediofrancos WHERE dni=$1 AND fecha=$2", user['dni'], hoy)
            
        if ult_hoy:
            if ult_hoy['salida_manual']: return JSONResponse(status_code=403, content={"msg": "Salida previamente registrada."})
            tdelta = (datetime.now() - datetime.strptime(ult_hoy['fecha_hora'], "%Y-%m-%d %H:%M:%S")).total_seconds()
            es_franco_tarde = franco and franco['turno'] == 'TARDE'
            
            if es_franco_tarde:
                if datetime.now().time() < datetime.strptime(cfg.get('franco_tarde_salida', '12:00'), "%H:%M").time(): 
                    return JSONResponse(status_code=403, content={"msg": f"Salida de Franco Tarde se habilita a las {cfg.get('franco_tarde_salida', '12:00')}hs."})
            else:
                limite_minimo_segundos = cfg.get('jornada_minima_hs', 3.0) * 3600
                if tdelta < limite_minimo_segundos: 
                    return JSONResponse(status_code=403, content={"msg": f"Jornada mínima no cumplida ({cfg.get('jornada_minima_hs', 3.0)}hs)."})
            
            motivo_sal = f"App JZ PASS [GPS {int(dist)}m]" if is_fuera_rango else "App JZ PASS"
            await db.execute("UPDATE fichajes SET salida_manual=$1, motivo_salida=$2 WHERE id=$3", datetime.now().strftime("%H:%M"), motivo_sal, ult_hoy['id'])
            return {"msg": f"Salida registrada con éxito ({int(dist)}m)"}
        else:
            if es_feriado_abierto: h_ent = datetime.strptime(suc['hora_apertura_feriado'], "%H:%M")
            else:
                h_ent = datetime.strptime(u['hora_entrada'], "%H:%M")
                if franco and franco['turno'] == 'MAÑANA': h_ent = datetime.strptime(cfg.get('franco_manana_ingreso', '15:00'), "%H:%M")
            
            h_ent = h_ent + timedelta(minutes=cfg.get('tolerancia_tarde', 10))
            
            if franco:
                tarde = 0
            else:
                tarde = 1 if datetime.strptime(datetime.now().strftime("%H:%M"), "%H:%M") > h_ent else 0
            
            motivo_ent = f"[GPS {int(dist)}m - Auditoría]" if is_fuera_rango else ""
            await db.execute("INSERT INTO fichajes (dni, sucursal, fecha_hora, lat, lon, distancia, tarde, motivo_entrada) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)", user['dni'], u['sucursal'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), float(lat), float(lon), float(dist), tarde, motivo_ent)
            return {"msg": f"Ingreso registrado con éxito ({int(dist)}m)"}

@app.post("/api/solicitud/crear")
@limiter.limit("10/minute")
async def crear_solicitud(request: Request, concepto: str = Form(...), fecha_ausencia: str = Form(...), fecha_fin: str = Form(""), hora_inicio: str = Form(""), hora_fin: str = Form(""), motivo: str = Form(...), comprobante: UploadFile = File(None)):
    user = await get_current_user(request)
    if not user: return JSONResponse(status_code=401, content={})
    filename = ""
    
    async with get_db() as db:
        duplicado = await db.fetchrow("SELECT id FROM solicitudes WHERE dni=$1 AND concepto=$2 AND fecha_ausencia=$3 AND estado='PENDIENTE'", user['dni'], concepto, fecha_ausencia)
        if duplicado:
            return JSONResponse(status_code=400, content={"msg": "Solicitud duplicada en curso."})

        tipo_sol = await db.fetchrow("SELECT * FROM tipos_solicitud WHERE nombre=$1", concepto)
        cfg_row = await db.fetchrow("SELECT * FROM configuracion WHERE id=1")
        cfg = dict(cfg_row) if cfg_row else {'vac_anticipo_dias': 14}
        
        if not tipo_sol: return JSONResponse(status_code=400, content={"msg": "Concepto inválido."})
        if tipo_sol['requiere_foto'] == 1 and (not comprobante or not comprobante.filename):
            return JSONResponse(status_code=400, content={"msg": "El documento adjunto es obligatorio."})

        if comprobante and hasattr(comprobante, 'filename') and comprobante.filename:
            raw = await comprobante.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024: return JSONResponse(status_code=413, content={"msg": "El archivo excede los 5MB."})
            ext = check_magic_bytes(raw)
            if not ext: return JSONResponse(status_code=400, content={"msg": "Formato de archivo no admitido."})
            filename = f"{uuid.uuid4().hex}.{ext}"
            with open(os.path.join("uploads", filename), "wb") as f: f.write(raw)
        
        if tipo_sol['tipo'] == 'DIAS':
            try:
                d_inicio = datetime.strptime(fecha_ausencia, "%Y-%m-%d")
                d_fin = datetime.strptime(fecha_fin, "%Y-%m-%d")
            except ValueError: return JSONResponse(status_code=400, content={"msg": "Estructura de fecha inválida."})
            if d_fin < d_inicio: return JSONResponse(status_code=400, content={"msg": "La fecha de fin es menor a la de inicio."})
            dias_solicitados = (d_fin - d_inicio).days + 1
            
            async with db.transaction():
                if tipo_sol['descuenta_dias'] == 1:
                    if (d_inicio - datetime.now()).days < cfg.get('vac_anticipo_dias', 14):
                        return JSONResponse(status_code=400, content={"msg": f"El aviso previo debe ser de {cfg.get('vac_anticipo_dias', 14)} días mínimo."})
                    u = await db.fetchrow("SELECT dias_vacaciones FROM usuarios WHERE dni=$1", user['dni'])
                    p_row = await db.fetchrow("SELECT SUM(horas) as pendientes FROM solicitudes s JOIN tipos_solicitud ts ON s.concepto=ts.nombre WHERE s.dni=$1 AND ts.descuenta_dias=1 AND s.estado='PENDIENTE'", user['dni'])
                    h_pend = p_row['pendientes'] if p_row and p_row['pendientes'] else 0
                    if (dias_solicitados + h_pend) > u['dias_vacaciones']:
                        return JSONResponse(status_code=400, content={"msg": "Saldo de vacaciones insuficiente."})
                        
                horas_guardadas = dias_solicitados * float(tipo_sol['horas_por_dia'] if tipo_sol['horas_por_dia'] > 0 else 1)
                f_carga = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                nuevo_id = await db.fetchval("INSERT INTO solicitudes (dni, concepto, fecha_ausencia, fecha_fin, hora_inicio, hora_fin, horas, motivo, archivo, fecha_carga) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id", user['dni'], concepto, fecha_ausencia, fecha_fin, "", "", horas_guardadas, motivo, filename, f_carga)
            return {"msg": f"Solicitud registrada bajo el ID #{nuevo_id}."}
        else:
            try:
                h_in = datetime.strptime(hora_inicio, "%H:%M")
                h_out = datetime.strptime(hora_fin, "%H:%M")
            except ValueError: return JSONResponse(status_code=400, content={"msg": "Datos de horario incompletos."})
            horas_totales = (h_out - h_in).total_seconds() / 3600
            if horas_totales < 0: horas_totales += 24
            
            f_carga = datetime.now().strftime("%Y-%m-%d %H:%M")
            nuevo_id = await db.fetchval("INSERT INTO solicitudes (dni, concepto, fecha_ausencia, fecha_fin, hora_inicio, hora_fin, horas, motivo, archivo, fecha_carga) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id", user['dni'], concepto, fecha_ausencia, "", h_in.strftime("%H:%M"), h_out.strftime("%H:%M"), round(horas_totales,2), motivo, filename, f_carga)
            return {"msg": f"Solicitud registrada bajo el ID #{nuevo_id}."}

@app.post("/api/solicitud/adjuntar")
@limiter.limit("10/minute")
async def adjuntar_comprobante(request: Request, solicitud_id: int = Form(...), comprobante: UploadFile = File(...)):
    user = await get_current_user(request)
    if not user: return JSONResponse(status_code=410, content={})
    raw = await comprobante.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024: return JSONResponse(status_code=413, content={"msg": "El archivo excede los 5MB."})
    ext = check_magic_bytes(raw)
    if not ext: return JSONResponse(status_code=400, content={"msg": "Formato no autorizado."})
    filename = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join("uploads", filename), "wb") as f: f.write(raw)
    async with get_db() as db:
        sol = await db.fetchrow("SELECT s.dni, ts.requiere_foto FROM solicitudes s JOIN tipos_solicitud ts ON s.concepto=ts.nombre WHERE s.id=$1", int(solicitud_id))
        if not sol or sol['dni'] != user['dni']: return JSONResponse(status_code=403, content={"msg": "Acceso denegado."})
        await db.execute("UPDATE solicitudes SET archivo=$1 WHERE id=$2", filename, int(solicitud_id))
    return {"msg": "ok"}

@app.post("/api/solicitud/cancelar")
@limiter.limit("10/minute")
async def cancelar_solicitud(request: Request, solicitud_id: int = Form(...)):
    user = await get_current_user(request)
    if not user: return JSONResponse(status_code=401, content={})
    async with get_db() as db:
        sol = await db.fetchrow("SELECT id, archivo FROM solicitudes WHERE id=$1 AND dni=$2 AND estado='PENDIENTE'", solicitud_id, user['dni'])
        if not sol: 
            return JSONResponse(status_code=400, content={"msg": "La solicitud no se encuentra o ya fue procesada."})
        
        if sol['archivo'] and sol['archivo'] != "null":
            path = os.path.join("uploads", sol['archivo'])
            if os.path.isfile(path):
                os.remove(path)
                
        await db.execute("DELETE FROM solicitudes WHERE id=$1", solicitud_id)
    return {"msg": "Solicitud cancelada de manera exitosa."}

async def check_admin(request: Request, check_encargado=False):
    user = await get_current_user(request)
    if not user: return None, JSONResponse(status_code=401, content={"msg": "No autorizado"})
    async with get_db() as db:
        adm = await db.fetchrow("SELECT * FROM usuarios WHERE dni=$1", user['dni'])
        if not adm or (adm['rol'] != 0 and not (check_encargado and adm['rol'] == 1)): return None, JSONResponse(status_code=403, content={"msg": "Privilegios insuficientes"})
        return dict(adm), None

@app.get("/api/datos_panel")
async def get_datos(request: Request):
    adm, err = await check_admin(request, check_encargado=True)
    if err: return err
    
    async with get_db() as db:
        cfg_row = await db.fetchrow("SELECT * FROM configuracion WHERE id=1")
        cfg = dict(cfg_row) if cfg_row else {}
        tipos = [dict(r) for r in await db.fetch("SELECT * FROM tipos_solicitud")]
        
        if adm['rol'] == 0:
            usuarios = [dict(r) for r in await db.fetch("SELECT dni, nombre, rol, sucursal, bloqueado_hasta, activo, hora_entrada, hora_salida, dias_vacaciones, calle, altura, depto, cp, mail, telefono, mapa, fecha_baja FROM usuarios")]
            sol = [dict(r) for r in await db.fetch("SELECT s.*, u.nombre, u.sucursal FROM solicitudes s JOIN usuarios u ON s.dni=u.dni ORDER BY s.id DESC")]
            fr = [dict(r) for r in await db.fetch("SELECT m.*, u.nombre, u.sucursal FROM mediofrancos m JOIN usuarios u ON m.dni=u.dni ORDER BY m.fecha DESC")]
            conv = [dict(r) for r in await db.fetch("SELECT fc.dni, fc.fecha, u.nombre, u.sucursal FROM feriados_convocados fc JOIN usuarios u ON fc.dni=u.dni")]
            fichajes = [dict(r) for r in await db.fetch("SELECT f.*, u.nombre, u.hora_entrada, u.hora_salida FROM fichajes f JOIN usuarios u ON f.dni=u.dni ORDER BY f.fecha_hora DESC LIMIT 1500")]
        else:
            suc = adm['sucursal']
            usuarios = [dict(r) for r in await db.fetch("SELECT dni, nombre, rol, sucursal, bloqueado_hasta, activo, hora_entrada, hora_salida, dias_vacaciones, calle, altura, depto, cp, mail, telefono, mapa, fecha_baja FROM usuarios WHERE sucursal=$1", suc)]
            sol = [dict(r) for r in await db.fetch("SELECT s.*, u.nombre, u.sucursal FROM solicitudes s JOIN usuarios u ON s.dni=u.dni WHERE u.sucursal=$1 ORDER BY s.id DESC", suc)]
            fr = [dict(r) for r in await db.fetch("SELECT m.*, u.nombre, u.sucursal FROM mediofrancos m JOIN usuarios u ON m.dni=u.dni WHERE u.sucursal=$1 ORDER BY m.fecha DESC", suc)]
            conv = [dict(r) for r in await db.fetch("SELECT fc.dni, fc.fecha, u.nombre, u.sucursal FROM feriados_convocados fc JOIN usuarios u ON fc.dni=u.dni WHERE u.sucursal=$1", suc)]
            fichajes = [dict(r) for r in await db.fetch("SELECT f.*, u.nombre, u.hora_entrada, u.hora_salida FROM fichajes f JOIN usuarios u ON f.dni=u.dni WHERE u.sucursal=$1 ORDER BY f.fecha_hora DESC LIMIT 1500", suc)]
            
        sucs = [dict(r) for r in await db.fetch("SELECT * FROM sucursales")]
        fer = [dict(r) for r in await db.fetch("SELECT * FROM feriados ORDER BY fecha DESC")]
        
        return {"rol": adm['rol'], "sucursal": adm['sucursal'], "usuarios": usuarios, "fichajes": fichajes, "sucursales": sucs, "francos": fr, "feriados": fer, "solicitudes": sol, "convocados": conv, "config": cfg, "tipos_solicitud": tipos}

@app.post("/api/admin/{action}")
async def admin_actions(request: Request, action: str):
    adm, err = await check_admin(request, check_encargado=True)
    if err: return err
    form = await request.form()
    
    async with get_db() as db:
        if adm['rol'] == 0:
            if action == "guardar_suc": 
                await db.execute("INSERT INTO sucursales (nombre,lat,lon,hora_cierre,hora_apertura_feriado,hora_cierre_feriado) VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (nombre) DO UPDATE SET lat=EXCLUDED.lat, lon=EXCLUDED.lon, hora_cierre=EXCLUDED.hora_cierre, hora_apertura_feriado=EXCLUDED.hora_apertura_feriado, hora_cierre_feriado=EXCLUDED.hora_cierre_feriado", str(form.get('d1')), float(form.get('d2')), float(form.get('d3')), str(form.get('d4')), str(form.get('d6')), str(form.get('d7')))
            elif action == "editar_suc": 
                await db.execute("UPDATE sucursales SET nombre=$1, lat=$2, lon=$3, hora_cierre=$4, hora_apertura_feriado=$5, hora_cierre_feriado=$6 WHERE nombre=$7", str(form.get('d2')), float(form.get('d3')), float(form.get('d4')), str(form.get('d5')), str(form.get('d6')), str(form.get('d7')), str(form.get('d1')))
            elif action == "borrar_suc": 
                await db.execute("DELETE FROM sucursales WHERE nombre=$1", str(form.get('d1')))
            elif action == "guardar_feriado": 
                await db.execute("INSERT INTO feriados (fecha, nombre, sucs_abren) VALUES ($1,$2,$3) ON CONFLICT (fecha) DO UPDATE SET nombre=EXCLUDED.nombre, sucs_abren=EXCLUDED.sucs_abren", str(form.get('d1')), str(form.get('d2')), str(form.get('d3')))
            elif action == "borrar_feriado": 
                await db.execute("DELETE FROM feriados WHERE fecha=$1", str(form.get('d1')))
            elif action == "editar_franco": 
                await db.execute("UPDATE mediofrancos SET fecha=$1, turno=$2 WHERE id=$3", str(form.get('d2')), str(form.get('d3')), int(form.get('d1')))
            elif action == "borrar_franco": 
                await db.execute("DELETE FROM mediofrancos WHERE id=$1", int(form.get('d1')))
            elif action == "guardar_concepto":
                await db.execute("INSERT INTO tipos_solicitud (nombre, tipo, requiere_foto, descuenta_dias, horas_por_dia) VALUES ($1,$2,$3,$4,$5) ON CONFLICT (nombre) DO UPDATE SET tipo=EXCLUDED.tipo, requiere_foto=EXCLUDED.requiere_foto, descuenta_dias=EXCLUDED.descuenta_dias, horas_por_dia=EXCLUDED.horas_por_dia", str(form.get('nombre')).strip(), str(form.get('tipo')), int(form.get('foto')), int(form.get('desc')), float(form.get('horas')))
            elif action == "borrar_concepto":
                await db.execute("DELETE FROM tipos_solicitud WHERE nombre=$1", str(form.get('nombre')))
            elif action == "guardar_config":
                await db.execute("UPDATE configuracion SET empresa_nombre=$1, color_primario=$2, distancia_gps=$3, tolerancia_tarde=$4, anti_rebote_min=$5, vac_anticipo_dias=$6, intentos_login=$7, jornada_minima_hs=$8, franco_manana_ingreso=$9, franco_tarde_salida=$10, gps_estricto=$11, encargados_aprueban=$12, pw_prefijo=$13, pw_sufijo=$14, vacaciones_base=$15 WHERE id=1", str(form.get('empresa')), str(form.get('color')), float(form.get('gps')), int(form.get('tol')), int(form.get('anti')), int(form.get('vac_ant')), int(form.get('intentos')), float(form.get('jornada')), str(form.get('f_manana')), str(form.get('f_tarde')), int(form.get('gps_est')), int(form.get('enc_aprueba')), str(form.get('pw_pre')), str(form.get('pw_suf')), int(form.get('vac_base')))
            
            elif action == "guardar_logo":
                logo = form.get("logo")
                if logo and hasattr(logo, 'filename') and logo.filename:
                    raw = await logo.read(5 * 1024 * 1024)
                    ext = check_magic_bytes(raw)
                    if ext in ['png', 'jpg']:
                        with open(os.path.join("uploads", "favicon.png"), "wb") as f: f.write(raw)
                        return {"msg": "Logo corporativo actualizado de manera correcta."}
                return JSONResponse(status_code=400, content={"msg": "Archivo no admitido."})
                
            elif action == "importar_csv":
                archivo = form.get("archivo_csv")
                if not archivo or not hasattr(archivo, 'filename'): return JSONResponse(status_code=400, content={"msg": "Archivo requerido."})
                raw = await archivo.read(2 * 1024 * 1024)
                try:
                    cfg = await db.fetchrow("SELECT pw_prefijo, pw_sufijo, vacaciones_base FROM configuracion WHERE id=1")
                    pre = cfg['pw_prefijo'] if cfg and cfg['pw_prefijo'] else "Jz"
                    suf = cfg['pw_sufijo'] if cfg and cfg['pw_sufijo'] else "*"
                    v_base = cfg['vacaciones_base'] if cfg and cfg['vacaciones_base'] else 14
                    
                    text = raw.decode('utf-8-sig')
                    reader = csv.DictReader(io.StringIO(text), delimiter=';')
                    async with db.transaction():
                        for i, row in enumerate(reader, start=2):
                            if 'dni' not in row or 'nombre' not in row: raise Exception(f"Fila {i}: Falta DNI o Nombre.")
                            dni = str(row['dni']).strip()
                            if not dni: continue
                            temp_pw = f"{pre}{dni}{suf}"
                            hashed = await asyncio.to_thread(hash_pw, temp_pw)
                            await db.execute("INSERT INTO usuarios (dni,nombre,rol,sucursal,hora_entrada,hora_salida,password,activo,dias_vacaciones,fecha_baja) VALUES ($1,$2,$3,$4,$5,$6,$7,1,$8,NULL) ON CONFLICT (dni) DO UPDATE SET nombre=EXCLUDED.nombre, rol=EXCLUDED.rol, sucursal=EXCLUDED.sucursal, hora_entrada=EXCLUDED.hora_entrada, hora_salida=EXCLUDED.hora_salida, password=EXCLUDED.password, dias_vacaciones=EXCLUDED.dias_vacaciones, activo=1, fecha_baja=NULL", dni, row['nombre'].strip(), int(row.get('rol', 2)), row.get('sucursal','').strip(), row.get('hora_entrada','09:00'), row.get('hora_salida','18:00'), hashed, int(row.get('dias_vacaciones', v_base)))
                    return {"msg": "Importación completada."}
                except Exception as e:
                    return JSONResponse(status_code=400, content={"msg": f"Error en la lectura del CSV: {str(e)}"})

        if action == "guardar_convocados":
            fecha = form.get('d2')
            suc_target = form.get('d3')
            dnis_str = form.get('d1')
            dnis = dnis_str.split(',') if dnis_str else []
            if adm['rol'] == 1: suc_target = adm['sucursal']
            limite = datetime.strptime(fecha, "%Y-%m-%d").replace(hour=18, minute=0, second=0) - timedelta(days=1)
            if datetime.now() > limite: return JSONResponse(status_code=400, content={"msg": "Tiempo límite operativo excedido."})
            
            valid_dnis = []
            for d in dnis:
                if not d: continue
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", str(d))
                if tgt and tgt['sucursal'] == suc_target: valid_dnis.append(d)
            
            async with db.transaction():
                await db.execute("DELETE FROM feriados_convocados WHERE fecha=$1 AND dni IN (SELECT dni FROM usuarios WHERE sucursal=$2)", str(fecha), str(suc_target))
                for d in valid_dnis: 
                    await db.execute("INSERT INTO feriados_convocados (dni, fecha) VALUES ($1,$2) ON CONFLICT DO NOTHING", str(d), str(fecha))

        elif action == "crear_user":
            if adm['rol'] != 0: return JSONResponse(status_code=403, content={"msg": "Acceso denegado."})
            cfg = await db.fetchrow("SELECT pw_prefijo, pw_sufijo, vacaciones_base FROM configuracion WHERE id=1")
            pre = cfg['pw_prefijo'] if cfg and cfg['pw_prefijo'] else "Jz"
            suf = cfg['pw_sufijo'] if cfg and cfg['pw_sufijo'] else "*"
            v_base = cfg['vacaciones_base'] if cfg and cfg['vacaciones_base'] else 14
            
            d1, d2, d3, d4, d5, d6 = form.get('d1').strip(), form.get('d2'), int(form.get('d3','2')), form.get('d4'), form.get('d5'), form.get('d6')
            d9 = int(form.get('d9', v_base))
            
            temp_pw = f"{pre}{d1}{suf}"
            hashed = await asyncio.to_thread(hash_pw, temp_pw)
            await db.execute("INSERT INTO usuarios (dni,nombre,rol,sucursal,hora_entrada,hora_salida,password,activo,dias_vacaciones) VALUES ($1,$2,$3,$4,$5,$6,$7,1,$8) ON CONFLICT (dni) DO NOTHING", str(d1), str(d2), int(d3), str(d4), str(d5), str(d6), hashed, int(d9))
            return {"msg": f"Registro creado. Credencial provisoria: {temp_pw}"}

        elif action == "editar_user":
            if adm['rol'] == 1:
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", str(form.get('d1')))
                if not tgt or tgt['sucursal'] != adm['sucursal']: return JSONResponse(status_code=403, content={"msg": "Usuario no correspondiente a la jurisdicción."})
            
            d1, d2, d3, d4, d5, d6, d8, d9 = form.get('d1').strip(), form.get('d2'), int(form.get('d3','2')), form.get('d4'), form.get('d5'), form.get('d6'), int(form.get('d8','1')), int(form.get('d9','14'))
            d_new = str(form.get('d_new', d1)).strip()
            calle, altura, depto, cp, mail, tel = form.get('calle',''), form.get('altura',''), form.get('depto',''), form.get('cp',''), form.get('mail',''), form.get('tel','')
            mapa_file = form.get("mapa")
            filename_mapa = None
            
            curr_u = await db.fetchrow("SELECT activo, fecha_baja FROM usuarios WHERE dni=$1", str(d1))
            f_baja = curr_u['fecha_baja'] if curr_u else None
            
            # 🛡️ Lógica transaccional de estado (Asignación de Fecha de Baja)
            if curr_u and curr_u['activo'] == 1 and d8 == 0:
                f_baja = datetime.now().strftime("%Y-%m-%d")
            elif d8 == 1:
                f_baja = None
            
            if mapa_file and hasattr(mapa_file, 'filename') and mapa_file.filename:
                raw = await mapa_file.read(5 * 1024 * 1024 + 1)
                ext = check_magic_bytes(raw)
                if ext:
                    filename_mapa = f"map_{uuid.uuid4().hex}.{ext}"
                    with open(os.path.join("uploads", filename_mapa), "wb") as f: f.write(raw)
                
            if filename_mapa: 
                await db.execute("UPDATE usuarios SET dni=$1, nombre=$2, rol=$3, sucursal=$4, hora_entrada=$5, hora_salida=$6, activo=$7, dias_vacaciones=$8, calle=$9, altura=$10, depto=$11, cp=$12, mail=$13, telefono=$14, mapa=$15, fecha_baja=$17 WHERE dni=$16", d_new, str(d2), int(d3), str(d4), str(d5), str(d6), d8, int(d9), str(calle), str(altura), str(depto), str(cp), str(mail), str(tel), filename_mapa, str(d1), f_baja)
            else: 
                await db.execute("UPDATE usuarios SET dni=$1, nombre=$2, rol=$3, sucursal=$4, hora_entrada=$5, hora_salida=$6, activo=$7, dias_vacaciones=$8, calle=$9, altura=$10, depto=$11, cp=$12, mail=$13, telefono=$14, fecha_baja=$16 WHERE dni=$15", d_new, str(d2), int(d3), str(d4), str(d5), str(d6), d8, int(d9), str(calle), str(altura), str(depto), str(cp), str(mail), str(tel), str(d1), f_baja)
                                     
        elif action == "reset_pass":
            dni_target = form.get('d1').strip()
            if adm['rol'] == 1:
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", dni_target)
                if not tgt or tgt['sucursal'] != adm['sucursal']: return JSONResponse(status_code=403, content={"msg": "Jurisdicción denegada."})
            
            cfg = await db.fetchrow("SELECT pw_prefijo, pw_sufijo FROM configuracion WHERE id=1")
            pre = cfg['pw_prefijo'] if cfg and cfg['pw_prefijo'] else "Jz"
            suf = cfg['pw_sufijo'] if cfg and cfg['pw_sufijo'] else "*"
            
            temp_pw = f"{pre}{dni_target}{suf}"
            hashed = await asyncio.to_thread(hash_pw, temp_pw)
            await db.execute("UPDATE usuarios SET password=$1, req_cambio=1, intentos=0, bloqueado_hasta=NULL WHERE dni=$2", hashed, dni_target)
            return {"msg": f"Clave reseteada. Nueva credencial: {temp_pw}"}

        elif action == "desbloquear_user":
            if adm['rol'] != 0: return JSONResponse(status_code=403, content={"msg": "Acceso denegado."})
            dni_target = form.get('d1').strip()
            await db.execute("UPDATE usuarios SET intentos=0, bloqueado_hasta=NULL WHERE dni=$1", dni_target)
            return {"msg": "ok"}

        elif action == "salida_manual":
            fich_id = int(form.get('d1'))
            d2 = form.get('d2')
            if not re.match(r'^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$', d2): return JSONResponse(status_code=400, content={"msg": "Formato de hora incorrecto."})
            
            fich = await db.fetchrow("SELECT dni FROM fichajes WHERE id=$1", fich_id)
            if not fich: return JSONResponse(status_code=404, content={"msg": "Registro inexistente."})
            
            if adm['rol'] == 1:
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", fich['dni'])
                if not tgt or tgt['sucursal'] != adm['sucursal']: return JSONResponse(status_code=403, content={"msg": "Empleado fuera de jurisdicción."})
                
            await db.execute("UPDATE fichajes SET salida_manual=$1, motivo_salida=$2 WHERE id=$3", str(d2), str(form.get('d3')), fich_id)

        elif action == "corregir_entrada":
            fich_id = int(form.get('d1'))
            nueva_hora = form.get('d2')
            justificante = form.get('d3')
            if not re.match(r'^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$', nueva_hora) or not justificante or str(justificante).strip() == "":
                return JSONResponse(status_code=400, content={"msg": "Información requerida faltante."})
            
            fich = await db.fetchrow("SELECT dni, fecha_hora FROM fichajes WHERE id=$1", fich_id)
            if not fich: return JSONResponse(status_code=404, content={"msg": "Registro inexistente."})
            
            if adm['rol'] == 1:
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", fich['dni'])
                if not tgt or tgt['sucursal'] != adm['sucursal']: return JSONResponse(status_code=403, content={"msg": "Fuera de jurisdicción."})

            fecha_base = fich['fecha_hora'].split(' ')[0]
            nueva_fecha_hora = f"{fecha_base} {nueva_hora}:00"
            usr = await db.fetchrow("SELECT hora_entrada FROM usuarios WHERE dni=$1", fich['dni'])
            cfg = await db.fetchrow("SELECT tolerancia_tarde, franco_manana_ingreso FROM configuracion WHERE id=1")
            
            franco_corr = await db.fetchrow("SELECT turno FROM mediofrancos WHERE dni=$1 AND fecha=$2", fich['dni'], fecha_base)
            
            tol = cfg['tolerancia_tarde'] if cfg else 10
            h_ent_str = usr['hora_entrada'] if usr else "09:00"
            t_limite = datetime.strptime(h_ent_str, "%H:%M") + timedelta(minutes=tol)
            t_nueva = datetime.strptime(nueva_hora, "%H:%M")
            
            if franco_corr:
                tarde = 0
            else:
                tarde = 1 if t_nueva > t_limite else 0
                
            await db.execute("UPDATE fichajes SET fecha_hora=$1, tarde=$2, motivo_entrada=$3 WHERE id=$4", nueva_fecha_hora, tarde, justificante.strip(), fich_id)
            
        elif action == "asignar_franco":
            d1_raw = form.get('d1')
            d1 = d1_raw.split(' - ')[-1].strip() if ' - ' in d1_raw else d1_raw.strip()
            
            d2, d3 = form.get('d2'), form.get('d3')
            f_dt = datetime.strptime(d2, "%Y-%m-%d")
            dias_para_restar = f_dt.weekday() + 2 
            limite = (f_dt - timedelta(days=dias_para_restar)).replace(hour=12, minute=0, second=0)
            if adm['rol'] == 1 and datetime.now() > limite: return JSONResponse(status_code=400, content={"msg": "El límite de tiempo para esta acción ha expirado."})
            
            tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", str(d1))
            if tgt and (adm['rol'] == 0 or tgt['sucursal'] == adm['sucursal']): 
                await db.execute("INSERT INTO mediofrancos (dni, fecha, turno, asignado_por) VALUES ($1,$2,$3,$4)", str(d1), str(d2), str(d3), str(adm['nombre']))
            else: return JSONResponse(status_code=400, content={"msg": "La asignación no es válida."})
        
        elif action == "estado_solicitud":
            cfg = await db.fetchrow("SELECT encargados_aprueban FROM configuracion WHERE id=1")
            puede_aprobar = True if adm['rol'] == 0 else (cfg and cfg['encargados_aprueban'] == 1)
            
            if not puede_aprobar: 
                return JSONResponse(status_code=403, content={"msg": "Permisos insuficientes para esta operación."}) 
                
            d1, d2, d3, d4 = form.get('d1'), form.get('d2'), form.get('d3'), form.get('d4')
            sol = await db.fetchrow("SELECT s.dni, s.concepto, s.horas, s.estado, s.fecha_ausencia, s.fecha_fin, ts.tipo, ts.descuenta_dias, ts.horas_por_dia FROM solicitudes s JOIN tipos_solicitud ts ON s.concepto=ts.nombre WHERE s.id=$1", int(d1))
            if sol:
                async with db.transaction():
                    if sol['tipo'] == 'DIAS' and d2 == 'APROBADA':
                        try:
                            n_in = datetime.strptime(d3, "%Y-%m-%d") if d3 else datetime.strptime(sol['fecha_ausencia'], "%Y-%m-%d")
                            n_fi = datetime.strptime(d4, "%Y-%m-%d") if d4 else datetime.strptime(sol['fecha_fin'], "%Y-%m-%d")
                            if n_fi < n_in: return JSONResponse(status_code=400, content={"msg": "Inconsistencia en las fechas proporcionadas."})
                            n_d = (n_fi - n_in).days + 1
                            if sol['descuenta_dias'] == 1 and sol['estado'] != 'APROBADA': 
                                await db.execute("UPDATE usuarios SET dias_vacaciones = dias_vacaciones - $1 WHERE dni=$2", int(n_d), sol['dni'])
                            await db.execute("UPDATE solicitudes SET estado=$1, fecha_ausencia=$2, fecha_fin=$3, horas=$4 WHERE id=$5", str(d2), n_in.strftime("%Y-%m-%d"), n_fi.strftime("%Y-%m-%d"), float(n_d * float(sol['horas_por_dia'] if sol['horas_por_dia']>0 else 1)), int(d1))
                        except ValueError: return JSONResponse(status_code=400, content={"msg": "Formato de fecha no válido."})
                    else:
                        if sol['descuenta_dias'] == 1 and sol['estado'] == 'APROBADA' and d2 != 'APROBADA': 
                            await db.execute("UPDATE usuarios SET dias_vacaciones = dias_vacaciones + $1 WHERE dni=$2", int(sol['horas']), sol['dni'])
                        await db.execute("UPDATE solicitudes SET estado=$1 WHERE id=$2", str(d2), int(d1))
    return {"msg": "ok"}

@app.get("/api/archivo/{filename}")
async def descargar_archivo(request: Request, filename: str):
    safe_name = os.path.basename(filename)
    path = os.path.join("uploads", safe_name)
    
    if safe_name == "favicon.png":
        if os.path.isfile(path): return FileResponse(path)
        return Response(status_code=404)
        
    user = await get_current_user(request)
    if not user: return Response(status_code=401)
    if not os.path.isfile(path): return Response(status_code=404)
    async with get_db() as db:
        u = await db.fetchrow("SELECT rol, sucursal FROM usuarios WHERE dni=$1", user['dni'])
        sol = await db.fetchrow("SELECT s.dni, us.sucursal FROM solicitudes s JOIN usuarios us ON s.dni=us.dni WHERE s.archivo=$1", safe_name)
        if safe_name.startswith("map_"):
            target = await db.fetchrow("SELECT sucursal FROM usuarios WHERE mapa=$1", safe_name)
            if u['rol'] == 2: return Response(status_code=403)
            if u['rol'] == 1 and target['sucursal'] != u['sucursal']: return Response(status_code=403)
        elif not sol: return Response(status_code=404)
        else:
            if u['rol'] == 2 and sol['dni'] != user['dni']: return Response(status_code=403)
            if u['rol'] == 1 and sol['sucursal'] != u['sucursal']: return Response(status_code=403)
    return FileResponse(path)

@app.get("/api/reporte_excel")
async def reporte_excel(request: Request, d_desde: str, d_hasta: str, suc: str="", dni: str=""):
    adm, err = await check_admin(request, check_encargado=True)
    if err: return err
    if adm['rol'] == 1:
        suc = adm['sucursal'] 
        
    desde = datetime.strptime(d_desde, "%Y-%m-%d")
    hasta = datetime.strptime(d_hasta, "%Y-%m-%d")
    async with get_db() as db:
        p = []
        q = "SELECT * FROM usuarios WHERE 1=1"
        if suc: 
            p.append(suc)
            q += f" AND sucursal=${len(p)}"
        if dni: 
            p.append(dni)
            q += f" AND dni=${len(p)}"
            
        empleados_raw = [dict(r) for r in await db.fetch(q, *p)]
        empleados = []
        
        # Filtro de inclusión inteligente basado en fecha de corte
        for e in empleados_raw:
            if e['activo'] == 1:
                empleados.append(e)
            elif e['fecha_baja'] and e['fecha_baja'] >= d_desde:
                empleados.append(e)
                
        sucs_db = {row['nombre']: dict(row) for row in await db.fetch("SELECT * FROM sucursales")}
        
        fich_map = {}
        for r in await db.fetch("SELECT * FROM fichajes WHERE fecha_hora BETWEEN $1 AND $2", d_desde, d_hasta+' 23:59:59'):
            fich_map.setdefault(r['dni'], {})[r['fecha_hora'][:10]] = dict(r)
            
        fran_map = {(r['dni'], r['fecha']): r['turno'] for r in await db.fetch("SELECT dni, fecha, turno FROM mediofrancos WHERE fecha BETWEEN $1 AND $2", d_desde, d_hasta)}
        fer_map = {r['fecha']: r['sucs_abren'] for r in await db.fetch("SELECT fecha, sucs_abren FROM feriados WHERE fecha BETWEEN $1 AND $2", d_desde, d_hasta)}
        convocados_set = {(r['dni'], r['fecha']) for r in await db.fetch("SELECT dni, fecha FROM feriados_convocados WHERE fecha BETWEEN $1 AND $2", d_desde, d_hasta)}
        multidias_db = [dict(r) for r in await db.fetch("SELECT s.dni, s.concepto, s.fecha_ausencia, s.fecha_fin, ts.descuenta_dias, ts.horas_por_dia FROM solicitudes s JOIN tipos_solicitud ts ON s.concepto=ts.nombre WHERE ts.tipo='DIAS' AND s.estado='APROBADA'")]

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quotechar='"')
    
    writer.writerow(['DNI', 'Nombre', 'Sucursal', 'Días Trabajados', 'Llegadas Tarde', 'Cantidad Faltas Totales', 'Fechas de Faltas', 'Horas Totales', 'Días Vacaciones Tomados'])
    def scsv(v): return "'" + str(v) if str(v).startswith(('=','+','-','@')) else str(v)
    
    for e in empleados:
        curr = desde
        total_hs, tardes, faltas, dias_trabajados, dias_vacaciones = 0, 0, 0, 0, 0
        fechas_faltas = []
        
        while curr <= hasta:
            f_str = curr.strftime("%Y-%m-%d")
            
            # 🛡️ Aplicación de regla de negocio: Omisión contable post-baja
            if e['activo'] == 0 and e['fecha_baja'] and f_str > e['fecha_baja']:
                curr += timedelta(days=1)
                continue
                
            fer_abren = fer_map.get(f_str)
            es_feriado_abierto = fer_abren and (fer_abren == 'TODAS' or e['sucursal'] in fer_abren)
            permiso_multidia = next((v for v in multidias_db if v['dni'] == e['dni'] and v['fecha_ausencia'] <= f_str <= v['fecha_fin']), None)
            
            if permiso_multidia:
                if curr.weekday() != 6:
                    if permiso_multidia['descuenta_dias'] == 1: dias_vacaciones += 1
                    if permiso_multidia['horas_por_dia'] > 0:
                        total_hs += permiso_multidia['horas_por_dia']
            elif curr.weekday() != 6:
                fich = fich_map.get(e['dni'], {}).get(f_str)
                if fich:
                    dias_trabajados += 1
                    franco = fran_map.get((e['dni'], f_str))
                    if fich['tarde'] and not franco: tardes += 1
                    
                    h_in = datetime.strptime(fich['fecha_hora'], "%Y-%m-%d %H:%M:%S").time()
                    if fich['salida_manual']: h_out = datetime.strptime(fich['salida_manual'], "%H:%M").time()
                    else:
                        if es_feriado_abierto:
                            cierre_suc = sucs_db[e['sucursal']]['hora_cierre_feriado']
                            h_out = min(datetime.strptime(cierre_suc, "%H:%M") + timedelta(minutes=30), datetime.strptime(cierre_suc, "%H:%M")).time()
                        else:
                            cierre_suc = sucs_db[e['sucursal']]['hora_cierre']
                            h_out_limit = min(datetime.strptime(cierre_suc, "%H:%M") + timedelta(minutes=30), datetime.strptime(e['hora_salida'], "%H:%M"))
                            if franco == 'TARDE': h_out_limit = min(h_out_limit, datetime.strptime("12:00", "%H:%M")) 
                            h_out = h_out_limit.time()
                    hs = (h_out.hour * 60 + h_out.minute - h_in.hour * 60 - h_in.minute) / 60
                    total_hs += max(0, hs)
                else:
                    if es_feriado_abierto and ((e['dni'], f_str) in convocados_set):
                        faltas += 1
                        fechas_faltas.append(f_str)
                    elif not fer_abren:
                        faltas += 1
                        fechas_faltas.append(f_str)
            curr += timedelta(days=1)
            
        faltas_str = " | ".join(fechas_faltas) if fechas_faltas else "-"
        writer.writerow([scsv(e['dni']), scsv(e['nombre']), scsv(e['sucursal']), dias_trabajados, tardes, faltas, scsv(faltas_str), round(total_hs, 2), dias_vacaciones])
        
    r = Response(content=output.getvalue().encode('utf-8-sig'), media_type="text/csv")
    r.headers["Content-Disposition"] = 'attachment; filename="Reporte_Consolidated.csv"'
    return r