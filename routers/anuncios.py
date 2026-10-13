import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, Response

from database import ErrorAuth, get_db, get_real_ip, requiere_panel, requiere_sesion

router = APIRouter()

POR_PAGINA = 10
TITULO_MAX, CUERPO_MAX = 150, 5000


def _ahora() -> str: return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def requiere_admin(adm: dict = Depends(requiere_panel)) -> dict:
    # Los anuncios generales los publica y audita solo el administrador (rol 0).
    if adm['rol'] != 0: raise ErrorAuth(403, "Acceso denegado.")
    return adm


# === EMPLEADO: anuncios pendientes de firma, visto y firma de recibido ===

@router.get("/api/anuncios/pendientes")
async def pendientes(user: dict = Depends(requiere_sesion)):
    async with get_db() as db:
        rows = await db.fetch("SELECT a.id, a.titulo, a.cuerpo, a.creado_en, l.visto_en FROM anuncio_lecturas l JOIN anuncios a ON a.id=l.anuncio_id WHERE l.dni=$1 AND l.firmado_en IS NULL AND a.anulado_en IS NULL ORDER BY a.id DESC", user['dni'])
    return {"anuncios": [dict(r) for r in rows]}


@router.post("/api/anuncios/{anuncio_id}/visto")
async def marcar_visto(anuncio_id: int, user: dict = Depends(requiere_sesion)):
    # Solo la primera apertura cuenta (visto_en no se pisa).
    async with get_db() as db:
        await db.execute("UPDATE anuncio_lecturas l SET visto_en=$3 FROM anuncios a WHERE a.id=l.anuncio_id AND l.anuncio_id=$1 AND l.dni=$2 AND l.visto_en IS NULL AND a.anulado_en IS NULL", anuncio_id, user['dni'], _ahora())
    return {"msg": "ok"}


@router.post("/api/anuncios/{anuncio_id}/firmar")
async def firmar(request: Request, anuncio_id: int, user: dict = Depends(requiere_sesion)):
    # Firma de recibido: fecha, hora e IP. Si no se habia abierto antes, cuenta tambien como visto.
    ahora = _ahora()
    async with get_db() as db:
        res = await db.execute("UPDATE anuncio_lecturas l SET firmado_en=$3, firma_ip=$4, visto_en=COALESCE(l.visto_en, $3) FROM anuncios a WHERE a.id=l.anuncio_id AND l.anuncio_id=$1 AND l.dni=$2 AND l.firmado_en IS NULL AND a.anulado_en IS NULL", anuncio_id, user['dni'], ahora, get_real_ip(request))
    if res == "UPDATE 0":
        return JSONResponse(status_code=400, content={"msg": "El anuncio ya fue firmado o no está disponible."})
    return {"msg": "Recibido registrado."}


# === ADMIN: publicar, anular, listar paginado, detalle y reporte ===

@router.post("/api/anuncios/admin/crear")
async def crear(titulo: str = Form(""), cuerpo: str = Form(""), adm: dict = Depends(requiere_admin)):
    titulo, cuerpo = titulo.strip(), cuerpo.strip()
    if not titulo or not cuerpo: return JSONResponse(status_code=400, content={"msg": "El anuncio necesita título y mensaje."})
    if len(titulo) > TITULO_MAX or len(cuerpo) > CUERPO_MAX:
        return JSONResponse(status_code=400, content={"msg": f"Máximo {TITULO_MAX} caracteres de título y {CUERPO_MAX} de mensaje."})
    async with get_db() as db:
        async with db.transaction():
            nuevo_id = await db.fetchval("INSERT INTO anuncios (titulo, cuerpo, creado_por, creado_en) VALUES ($1,$2,$3,$4) RETURNING id", titulo, cuerpo, adm['dni'], _ahora())
            res = await db.execute("INSERT INTO anuncio_lecturas (anuncio_id, dni) SELECT $1, dni FROM usuarios WHERE activo=1", nuevo_id)
    return {"msg": f"Anuncio publicado a {res.split()[-1]} usuarios.", "id": nuevo_id}


@router.post("/api/anuncios/admin/{anuncio_id}/anular")
async def anular(anuncio_id: int, adm: dict = Depends(requiere_admin)):
    # Se anula, no se borra: deja de mostrarse a los empleados pero el registro de vistos/firmas queda.
    async with get_db() as db:
        res = await db.execute("UPDATE anuncios SET anulado_en=$2, anulado_por=$3 WHERE id=$1 AND anulado_en IS NULL", anuncio_id, _ahora(), adm['dni'])
    if res == "UPDATE 0": return JSONResponse(status_code=400, content={"msg": "El anuncio no existe o ya estaba anulado."})
    return {"msg": "Anuncio anulado."}


@router.get("/api/anuncios/admin")
async def listar(pagina: int = 1, adm: dict = Depends(requiere_admin)):
    pagina = max(1, pagina)
    async with get_db() as db:
        total = await db.fetchval("SELECT COUNT(*) FROM anuncios")
        rows = await db.fetch("SELECT a.id, a.titulo, a.creado_en, a.anulado_en, u.nombre AS creado_por_nombre, COUNT(l.dni) AS destinatarios, COUNT(l.visto_en) AS vistos, COUNT(l.firmado_en) AS firmados FROM anuncios a LEFT JOIN anuncio_lecturas l ON l.anuncio_id=a.id LEFT JOIN usuarios u ON u.dni=a.creado_por GROUP BY a.id, u.nombre ORDER BY a.id DESC LIMIT $1 OFFSET $2", POR_PAGINA, (pagina - 1) * POR_PAGINA)
    return {"anuncios": [dict(r) for r in rows], "pagina": pagina, "paginas": max(1, -(-total // POR_PAGINA)), "total": total}


async def _detalle(db, anuncio_id: int):
    a = await db.fetchrow("SELECT a.*, u.nombre AS creado_por_nombre FROM anuncios a LEFT JOIN usuarios u ON u.dni=a.creado_por WHERE a.id=$1", anuncio_id)
    if not a: return None, []
    filas = await db.fetch("SELECT l.dni, u.nombre, u.sucursal, l.visto_en, l.firmado_en, l.firma_ip FROM anuncio_lecturas l LEFT JOIN usuarios u ON u.dni=l.dni WHERE l.anuncio_id=$1 ORDER BY u.nombre, l.dni", anuncio_id)
    return dict(a), [dict(f) for f in filas]


@router.get("/api/anuncios/admin/{anuncio_id}")
async def detalle(anuncio_id: int, adm: dict = Depends(requiere_admin)):
    async with get_db() as db:
        a, filas = await _detalle(db, anuncio_id)
    if not a: return JSONResponse(status_code=404, content={"msg": "Anuncio inexistente."})
    return {"anuncio": a, "lecturas": filas}


@router.get("/api/anuncios/admin/{anuncio_id}/reporte")
async def reporte(anuncio_id: int, adm: dict = Depends(requiere_admin)):
    async with get_db() as db:
        a, filas = await _detalle(db, anuncio_id)
    if not a: return JSONResponse(status_code=404, content={"msg": "Anuncio inexistente."})

    def scsv(v): return "'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else str(v)
    out = io.StringIO()
    w = csv.writer(out, delimiter=';', quotechar='"')
    w.writerow(['Anuncio', scsv(a['titulo'])])
    w.writerow(['Publicado', a['creado_en'], scsv(a['creado_por_nombre'] or a['creado_por'] or '')])
    w.writerow(['Estado', f"Anulado {a['anulado_en']}" if a['anulado_en'] else 'Vigente'])
    w.writerow(['Vistos', sum(1 for f in filas if f['visto_en']), 'Firmados', sum(1 for f in filas if f['firmado_en']), 'Destinatarios', len(filas)])
    w.writerow([])
    w.writerow(['DNI', 'Nombre', 'Sucursal', 'Visto', 'Fecha visto', 'Firmado', 'Fecha firma', 'IP firma'])
    for f in filas:
        w.writerow([scsv(f['dni']), scsv(f['nombre'] or ''), scsv(f['sucursal'] or ''), 'Sí' if f['visto_en'] else 'No', f['visto_en'] or '',
                    'Sí' if f['firmado_en'] else 'No', f['firmado_en'] or '', f['firma_ip'] or ''])
    r = Response(content=out.getvalue().encode('utf-8-sig'), media_type="text/csv")
    r.headers["Content-Disposition"] = f'attachment; filename="Anuncio_{anuncio_id}_lecturas.csv"'
    return r
