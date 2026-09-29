"""Cabeceras de seguridad via jztech_core.security_headers. No requiere base de datos
(TestClient sin context manager: no entra al lifespan)."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _assert_security_headers(resp):
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = resp.headers["content-security-policy"]
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_home_and_panel_have_security_headers():
    for path in ("/", "/panel"):
        resp = client.get(path)
        _assert_security_headers(resp)
        # HSTS se manda siempre en respuestas normales (ver comentario en main.py).
        assert resp.headers["strict-transport-security"].startswith("max-age=")


def test_csrf_rejection_also_has_security_headers():
    # El middleware de cabeceras va por fuera del de CSRF: sus 403 tambien las llevan.
    resp = client.post("/api/logout")
    assert resp.status_code == 403
    _assert_security_headers(resp)


def test_geolocation_allowed_for_fichaje():
    # El fichaje usa navigator.geolocation; si esto vuelve a "geolocation=()" se rompe.
    assert "geolocation=(self)" in client.get("/").headers["permissions-policy"]
