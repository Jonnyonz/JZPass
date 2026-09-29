from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from jztech_core import sessions
from jztech_core.security_headers import SecurityHeadersMiddleware

from database import (
    DB, ORIGINES_PERMITIDOS, csrf_signer, limiter,
    init_db_schema, close_db_pool,
)
from routers import auth, empleado, admin, archivos


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_schema()
    yield
    await close_db_pool()


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
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path not in ["/api/login", "/api/setup/admin"]:
        token = request.headers.get("X-CSRF-Token")
        try: csrf_dni = csrf_signer.loads(token, max_age=604800)
        except Exception: return JSONResponse(status_code=403, content={"msg": "CSRF Token inválido o expirado."})
        # El token CSRF esta firmado con el DNI del usuario: se valida que corresponda a la
        # sesion actual, para que un token de otro usuario no pueda reutilizarse.
        if request.cookies.get(sessions.SESSION_COOKIE_NAME) and DB.pool is not None:
            ses_dni = await sessions.verify_session(DB.pool, request.cookies[sessions.SESSION_COOKIE_NAME])
            if ses_dni is not None and str(csrf_dni) != str(ses_dni):
                return JSONResponse(status_code=403, content={"msg": "CSRF no corresponde a la sesión."})
    response = await call_next(request)
    # HSTS se sigue mandando siempre desde aca (no desde jztech_core, que solo la manda si la app
    # ve https): detras de Caddy uvicorn corre sin --proxy-headers y ve http. Por http plano los
    # navegadores la ignoran, asi que mandarla siempre no tiene efecto negativo.
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Cabeceras de seguridad (jztech_core). Se agrega despues del middleware de CSRF para quedar
# por fuera y cubrir tambien sus 403. 'unsafe-inline' es temporal: index.html y dashboard.html
# tienen <script>, <style> y handlers on*= inline; se quita al separar JS/CSS (seccion 3.7).
# geolocation=(self): el fichaje en index.html usa navigator.geolocation.
app.add_middleware(
    SecurityHeadersMiddleware,
    csp=(
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    hsts=False,
    permissions_policy="geolocation=(self), microphone=(), camera=()",
)


# === REGISTRO DE ROUTERS MODULARES ===
app.include_router(auth.router)
app.include_router(empleado.router)
app.include_router(admin.router)
app.include_router(archivos.router)


@app.get("/", response_class=HTMLResponse)
async def home():
    with open("index.html", "r", encoding="utf-8") as f: return f.read()


@app.get("/panel", response_class=HTMLResponse)
async def panel():
    with open("dashboard.html", "r", encoding="utf-8") as f: return f.read()
