"""Integraciones: claves de API (Ajustes del Sistema > Integraciones, solo administrador) y la API /api/v1 que
las usa (n8n, planillas, un informe por WhatsApp). Solo lectura, "Authorization: Bearer jzp_...", sin sesion ni
CSRF. Misma forma que Flex (flx_) y Tracker360 (tch_): errores con {"detail": ...}."""

import secrets
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from database import ErrorAuth, get_db, hash_clave_api, requiere_clave_api, requiere_panel
from routers.admin import DIAS_SEMANA, calcular_asistencia, csv_asistencia, nombre_reporte, respuesta_csv, resumen_asistencia

claves = APIRouter(prefix="/api/claves")
v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(requiere_clave_api)])


# ---------- Claves (administrador, con sesion; el panel las maneja con {"msg": ...}) ----------

async def requiere_admin(adm: dict = Depends(requiere_panel)) -> dict:
    if adm['rol'] != 0:
        raise ErrorAuth(403, "Privilegios insuficientes")
    return adm


def _fila(f) -> dict:
    return {"id": f["id"], "nombre": f["nombre"], "pista": f["pista"], "creada_en": f["creada_en"], "ultimo_uso": f["ultimo_uso"]}


@claves.get("")
async def listar(_: dict = Depends(requiere_admin)):
    async with get_db() as db:
        filas = await db.fetch("SELECT id, nombre, pista, creada_en, ultimo_uso FROM claves_api WHERE revocada_en IS NULL ORDER BY id")
    return [_fila(f) for f in filas]


@claves.post("", status_code=201)
async def generar(request: Request, adm: dict = Depends(requiere_admin)):
    form = await request.form()
    nombre = str(form.get("nombre") or "").strip()[:60]
    if not nombre:
        return JSONResponse(status_code=400, content={"msg": "Poné para qué es la clave (por ejemplo, n8n)."})
    clave = "jzp_" + secrets.token_urlsafe(32)
    async with get_db() as db:
        f = await db.fetchrow(
            "INSERT INTO claves_api (nombre, clave_hash, pista, creada_por) VALUES ($1, $2, $3, $4) "
            "RETURNING id, nombre, pista, creada_en, ultimo_uso",
            nombre, hash_clave_api(clave), clave[:8] + "…", adm['dni'])
    return {**_fila(f), "clave": clave, "msg": "ok"}   # la clave entera sale solo aca


@claves.post("/{clave_id}/revocar")
async def revocar(clave_id: int, _: dict = Depends(requiere_admin)):
    async with get_db() as db:
        n = await db.execute("UPDATE claves_api SET revocada_en = now() WHERE id = $1 AND revocada_en IS NULL", clave_id)
    if n == "UPDATE 0":
        return JSONResponse(status_code=404, content={"msg": "La clave no existe o ya estaba revocada."})
    return {"msg": "ok"}


# ---------- API v1 (con clave) ----------

@v1.get("/reportes/asistencia")
async def asistencia(desde: date, hasta: date, sucursal: str = "", dni: str = "", tipo: str = "resumido", formato: str = "json"):
    """El reporte de asistencia del panel (resumido o detallado) para un rango, en JSON o en el mismo CSV.
    Incluye a los dados de baja cuyo ultimo dia cae en el rango."""
    if tipo not in ("resumido", "detallado"):
        raise HTTPException(status_code=400, detail="tipo: resumido o detallado.")
    if formato not in ("json", "csv"):
        raise HTTPException(status_code=400, detail="formato: json o csv.")
    if hasta < desde:
        raise HTTPException(status_code=400, detail="hasta es anterior a desde.")
    if (hasta - desde).days > 366:
        raise HTTPException(status_code=400, detail="El rango no puede superar un año.")
    empleados = await calcular_asistencia(desde.isoformat(), hasta.isoformat(), sucursal, dni)
    if formato == "csv":
        return respuesta_csv(csv_asistencia(empleados, tipo), nombre_reporte(tipo, dni, empleados))
    if tipo == "resumido":
        filas = [{"dni": e["dni"], "nombre": e["nombre"], "sucursal": e["sucursal"], **resumen_asistencia(e)} for e in empleados]
    else:
        filas = [{**e, "jornadas": [{"dia": DIAS_SEMANA[date.fromisoformat(d["fecha"]).weekday()], **d} for d in e["jornadas"]]}
                 for e in empleados]
    return {"desde": desde, "hasta": hasta, "sucursal": sucursal, "dni": dni, "tipo": tipo,
            "generado_en": datetime.now().isoformat(timespec="seconds"), "empleados": filas}


@v1.get("/empleados")
async def empleados(sucursal: str = "", activos: bool = True):
    """Personal (sin datos de contacto ni claves). activos=false: tambien los dados de baja, con su fecha."""
    p, q = [], "SELECT dni, nombre, rol, sucursal, activo, fecha_baja, hora_entrada, hora_salida, dias_vacaciones FROM usuarios WHERE 1=1"
    if activos:
        q += " AND activo=1"
    if sucursal:
        p.append(sucursal)
        q += f" AND sucursal=${len(p)}"
    async with get_db() as db:
        return [dict(r) for r in await db.fetch(q + " ORDER BY nombre, dni", *p)]


@v1.get("/sucursales")
async def sucursales():
    async with get_db() as db:
        return [dict(r) for r in await db.fetch("SELECT nombre, hora_cierre, hora_apertura_feriado, hora_cierre_feriado, activa FROM sucursales ORDER BY nombre")]
