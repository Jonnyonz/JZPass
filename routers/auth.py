import asyncio
import hmac
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import JSONResponse
from jztech_core import sessions

from database import (
    DB, SETUP_TOKEN, DUMMY_HASH,
    csrf_signer, limiter, get_db, get_current_user, abrir_sesion, requiere_sesion_cambio,
    verify_pw, hash_pw, pw_necesita_rehash,
)

router = APIRouter()


@router.get("/api/csrf-token")
async def get_csrf(request: Request):
    user = await get_current_user(request, allow_req_cambio=True)
    return {"token": csrf_signer.dumps(user['dni']) if user else ""}


@router.post("/api/login")
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
                await asyncio.to_thread(verify_pw, password, DUMMY_HASH)
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

            await db.execute("UPDATE usuarios SET intentos=0, bloqueado_hasta=NULL WHERE dni=$1", dni)
            # Migracion transparente a Argon2id: si el hash guardado es bcrypt (o Argon2id con
            # parametros viejos), se re-hashea con la clave que se acaba de validar. Sin reset masivo.
            if await asyncio.to_thread(pw_necesita_rehash, str(u['password'])):
                nuevo_hash = await asyncio.to_thread(hash_pw, password)
                await db.execute("UPDATE usuarios SET password=$1 WHERE dni=$2", nuevo_hash, dni)

            await abrir_sesion(response, dni)
            return {"msg": "ok", "req_cambio": u['req_cambio'] or 0, "rol": u['rol'] or 2}
    except Exception as e:
        return JSONResponse(status_code=500, content={"msg": f"Error de consistencia interna: {str(e)}"})


@router.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(sessions.SESSION_COOKIE_NAME)
    if token and DB.pool is not None:
        await sessions.revoke_session(DB.pool, token)
    sessions.clear_session_cookie(response)
    return {"msg": "ok"}


@router.post("/api/cambiar_clave")
@limiter.limit("5/minute")
async def cambiar_clave(request: Request, response: Response, nueva: str = Form(...), user: dict = Depends(requiere_sesion_cambio)):
    # requiere_sesion_cambio: admite la clave provisoria (es la pantalla a la que llega quien la tiene).

    nueva = nueva.strip()
    if len(nueva) < 8: return JSONResponse(status_code=400, content={"msg": "Mínimo 8 caracteres."})
    if not re.search(r'[A-Z]', nueva): return JSONResponse(status_code=400, content={"msg": "Mínimo 1 mayúscula."})
    if len(re.findall(r'\d', nueva)) < 2: return JSONResponse(status_code=400, content={"msg": "Mínimo 2 números."})
    if not re.search(r'[^a-zA-Z0-9]', nueva): return JSONResponse(status_code=400, content={"msg": "Mínimo 1 carácter especial."})

    async with get_db() as db:
        hashed_pw = await asyncio.to_thread(hash_pw, nueva)
        await db.execute("UPDATE usuarios SET password=$1, req_cambio=0 WHERE dni=$2", hashed_pw, user['dni'])

    # Cierra todas las sesiones del usuario (incluida esta) y abre una nueva para este dispositivo.
    await sessions.revoke_all_sessions_for_user(DB.pool, user['dni'])
    await abrir_sesion(response, user['dni'])
    return {"msg": "ok"}


@router.get("/api/setup/status")
async def setup_status():
    async with get_db() as db:
        count = await db.fetchval("SELECT COUNT(*) FROM usuarios")
    return {"needs_setup": (count or 0) == 0}


@router.post("/api/setup/admin")
@limiter.limit("5/minute")
async def setup_admin(request: Request, response: Response, token: str = Form(...), dni: str = Form(...), nombre: str = Form(...), password: str = Form(...)):
    if not SETUP_TOKEN or not hmac.compare_digest(token.strip(), SETUP_TOKEN):
        return JSONResponse(status_code=403, content={"msg": "Token de instalación inválido."})

    async with get_db() as db:
        count = await db.fetchval("SELECT COUNT(*) FROM usuarios")
        if (count or 0) > 0:
            return JSONResponse(status_code=403, content={"msg": "La configuración inicial ya fue completada."})

        dni, nombre, password = dni.strip(), nombre.strip(), password.strip()
        if not dni or not nombre:
            return JSONResponse(status_code=400, content={"msg": "Complete todos los campos."})
        if len(password) < 8: return JSONResponse(status_code=400, content={"msg": "Mínimo 8 caracteres."})
        if not re.search(r'[A-Z]', password): return JSONResponse(status_code=400, content={"msg": "Mínimo 1 mayúscula."})
        if len(re.findall(r'\d', password)) < 2: return JSONResponse(status_code=400, content={"msg": "Mínimo 2 números."})
        if not re.search(r'[^a-zA-Z0-9]', password): return JSONResponse(status_code=400, content={"msg": "Mínimo 1 carácter especial."})

        hashed_pw = await asyncio.to_thread(hash_pw, password)
        await db.execute(
            "INSERT INTO usuarios (dni, nombre, rol, sucursal, password, activo, req_cambio) VALUES ($1,$2,0,'',$3,1,0)",
            dni, nombre, hashed_pw
        )

    await abrir_sesion(response, dni)
    return {"msg": "ok"}
