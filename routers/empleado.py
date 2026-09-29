import math
import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import JSONResponse

from database import get_db, requiere_sesion, check_magic_bytes, limiter

router = APIRouter()


def calc_dist(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


@router.get("/api/empleado/datos")
async def emp_datos(request: Request, user: dict = Depends(requiere_sesion)):
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


@router.post("/api/fichar")
@limiter.limit("10/minute")
async def fichar(request: Request, lat: float = Form(...), lon: float = Form(...), user: dict = Depends(requiere_sesion)):
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


@router.post("/api/solicitud/crear")
@limiter.limit("10/minute")
async def crear_solicitud(request: Request, concepto: str = Form(...), fecha_ausencia: str = Form(...), fecha_fin: str = Form(""), hora_inicio: str = Form(""), hora_fin: str = Form(""), motivo: str = Form(...), comprobante: UploadFile = File(None), user: dict = Depends(requiere_sesion)):
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


@router.post("/api/solicitud/adjuntar")
@limiter.limit("10/minute")
async def adjuntar_comprobante(request: Request, solicitud_id: int = Form(...), comprobante: UploadFile = File(...), user: dict = Depends(requiere_sesion)):
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


@router.post("/api/solicitud/cancelar")
@limiter.limit("10/minute")
async def cancelar_solicitud(request: Request, solicitud_id: int = Form(...), user: dict = Depends(requiere_sesion)):
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
