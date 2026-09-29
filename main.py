from contextlib import asynccontextmanager

import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from database import (
    ORIGINES_PERMITIDOS, SECRET_KEY, csrf_signer, limiter,
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
        session_cookie = request.cookies.get("session_token")
        if session_cookie:
            try: ses_dni = jwt.decode(session_cookie, SECRET_KEY, algorithms=["HS256"]).get("dni")
            except jwt.PyJWTError: ses_dni = None
            if ses_dni is not None and str(csrf_dni) != str(ses_dni):
                return JSONResponse(status_code=403, content={"msg": "CSRF no corresponde a la sesión."})
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


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
