from fastapi.testclient import TestClient

from main import app


def test_modular_architecture_compiles():
    # Al pedir el esquema OpenAPI, FastAPI compila internamente todos los routers.
    # Si hay un error de importacion en algun router, esto lanza una excepcion y el test falla.
    with TestClient(app) as c:
        response = c.get("/openapi.json")
    assert response.status_code == 200, "El servidor no pudo compilar el arbol de rutas."

    schema_str = str(response.json())
    rutas_esperadas = ["/api/login", "/api/empleado/datos", "/api/datos_panel", "/api/archivo/{filename}"]
    for ruta in rutas_esperadas:
        assert ruta in schema_str, f"Fallo arquitectonico: la ruta '{ruta}' no se registro en main.py"


def test_home_sirve_html():
    with TestClient(app) as c:
        response = c.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
