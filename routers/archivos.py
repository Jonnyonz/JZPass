import os

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse

from database import get_db, get_current_user

router = APIRouter()


@router.get("/api/archivo/{filename}")
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
