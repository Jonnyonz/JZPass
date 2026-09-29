"""Denegar por defecto: toda ruta exige sesion (depende de database.sesion_valida, directa o
indirectamente) salvo las listadas aca. Agregar una ruta publica obliga a sumarla a proposito;
olvidarse de proteger una ruta hace fallar el test."""

from jztech_core.deny_by_default import assert_all_routes_protected

from database import sesion_valida
from main import app

PUBLIC_PATHS = [
    # Autenticacion y configuracion inicial.
    "/api/login",
    "/api/logout",
    "/api/setup/status",
    "/api/setup/admin",
    # La pide el frontend antes de iniciar sesion; sin sesion devuelve un token vacio.
    "/api/csrf-token",
    # Paginas HTML (los datos que muestran vienen de rutas protegidas).
    "/",
    "/panel",
    # Documentacion autogenerada de FastAPI.
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
]


def test_all_routes_require_session_unless_public():
    assert_all_routes_protected(app, public_paths=PUBLIC_PATHS, auth_dependency=sesion_valida)
