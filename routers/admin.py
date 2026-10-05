import asyncio
import csv
import io
import os
import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from jztech_core import sessions

from database import DB, get_db, requiere_panel, hash_pw, gen_temp_pw, check_magic_bytes, logger


class CSVInvalido(ValueError):
    pass

router = APIRouter()


@router.get("/api/datos_panel")
async def get_datos(request: Request, adm: dict = Depends(requiere_panel)):

    async with get_db() as db:
        cfg_row = await db.fetchrow("SELECT * FROM configuracion WHERE id=1")
        cfg = dict(cfg_row) if cfg_row else {}
        tipos = [dict(r) for r in await db.fetch("SELECT * FROM tipos_solicitud")]

        if adm['rol'] == 0:
            usuarios = [dict(r) for r in await db.fetch("SELECT dni, nombre, rol, sucursal, bloqueado_hasta, activo, hora_entrada, hora_salida, dias_vacaciones, calle, altura, depto, cp, mail, telefono, mapa, fecha_baja FROM usuarios")]
            sol = [dict(r) for r in await db.fetch("SELECT s.*, u.nombre, u.sucursal FROM solicitudes s JOIN usuarios u ON s.dni=u.dni ORDER BY s.id DESC")]
            fr = [dict(r) for r in await db.fetch("SELECT m.*, u.nombre, u.sucursal FROM mediofrancos m JOIN usuarios u ON m.dni=u.dni ORDER BY m.fecha DESC")]
            conv = [dict(r) for r in await db.fetch("SELECT fc.dni, fc.fecha, u.nombre, u.sucursal FROM feriados_convocados fc JOIN usuarios u ON fc.dni=u.dni")]
            fichajes = [dict(r) for r in await db.fetch("SELECT f.*, u.nombre, u.hora_entrada, u.hora_salida FROM fichajes f JOIN usuarios u ON f.dni=u.dni ORDER BY f.fecha_hora DESC LIMIT 1500")]
        else:
            suc = adm['sucursal']
            usuarios = [dict(r) for r in await db.fetch("SELECT dni, nombre, rol, sucursal, bloqueado_hasta, activo, hora_entrada, hora_salida, dias_vacaciones, calle, altura, depto, cp, mail, telefono, mapa, fecha_baja FROM usuarios WHERE sucursal=$1", suc)]
            sol = [dict(r) for r in await db.fetch("SELECT s.*, u.nombre, u.sucursal FROM solicitudes s JOIN usuarios u ON s.dni=u.dni WHERE u.sucursal=$1 ORDER BY s.id DESC", suc)]
            fr = [dict(r) for r in await db.fetch("SELECT m.*, u.nombre, u.sucursal FROM mediofrancos m JOIN usuarios u ON m.dni=u.dni WHERE u.sucursal=$1 ORDER BY m.fecha DESC", suc)]
            conv = [dict(r) for r in await db.fetch("SELECT fc.dni, fc.fecha, u.nombre, u.sucursal FROM feriados_convocados fc JOIN usuarios u ON fc.dni=u.dni WHERE u.sucursal=$1", suc)]
            fichajes = [dict(r) for r in await db.fetch("SELECT f.*, u.nombre, u.hora_entrada, u.hora_salida FROM fichajes f JOIN usuarios u ON f.dni=u.dni WHERE u.sucursal=$1 ORDER BY f.fecha_hora DESC LIMIT 1500", suc)]

        sucs = [dict(r) for r in await db.fetch("SELECT * FROM sucursales")]
        fer = [dict(r) for r in await db.fetch("SELECT * FROM feriados ORDER BY fecha DESC")]

        return {"rol": adm['rol'], "sucursal": adm['sucursal'], "usuarios": usuarios, "fichajes": fichajes, "sucursales": sucs, "francos": fr, "feriados": fer, "solicitudes": sol, "convocados": conv, "config": cfg, "tipos_solicitud": tipos}


@router.post("/api/admin/{action}")
async def admin_actions(request: Request, action: str, adm: dict = Depends(requiere_panel)):
    form = await request.form()

    async with get_db() as db:
        if adm['rol'] == 0:
            if action == "guardar_suc":
                await db.execute("INSERT INTO sucursales (nombre,lat,lon,hora_cierre,hora_apertura_feriado,hora_cierre_feriado) VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (nombre) DO UPDATE SET lat=EXCLUDED.lat, lon=EXCLUDED.lon, hora_cierre=EXCLUDED.hora_cierre, hora_apertura_feriado=EXCLUDED.hora_apertura_feriado, hora_cierre_feriado=EXCLUDED.hora_cierre_feriado", str(form.get('d1')), float(form.get('d2')), float(form.get('d3')), str(form.get('d4')), str(form.get('d6')), str(form.get('d7')))
            elif action == "editar_suc":
                await db.execute("UPDATE sucursales SET nombre=$1, lat=$2, lon=$3, hora_cierre=$4, hora_apertura_feriado=$5, hora_cierre_feriado=$6 WHERE nombre=$7", str(form.get('d2')), float(form.get('d3')), float(form.get('d4')), str(form.get('d5')), str(form.get('d6')), str(form.get('d7')), str(form.get('d1')))
            elif action == "borrar_suc":
                await db.execute("DELETE FROM sucursales WHERE nombre=$1", str(form.get('d1')))
            elif action == "guardar_feriado":
                await db.execute("INSERT INTO feriados (fecha, nombre, sucs_abren) VALUES ($1,$2,$3) ON CONFLICT (fecha) DO UPDATE SET nombre=EXCLUDED.nombre, sucs_abren=EXCLUDED.sucs_abren", str(form.get('d1')), str(form.get('d2')), str(form.get('d3')))
            elif action == "borrar_feriado":
                await db.execute("DELETE FROM feriados WHERE fecha=$1", str(form.get('d1')))
            elif action == "editar_franco":
                await db.execute("UPDATE mediofrancos SET fecha=$1, turno=$2 WHERE id=$3", str(form.get('d2')), str(form.get('d3')), int(form.get('d1')))
            elif action == "borrar_franco":
                await db.execute("DELETE FROM mediofrancos WHERE id=$1", int(form.get('d1')))
            elif action == "guardar_concepto":
                nombre = str(form.get('nombre') or '').strip()
                if not nombre: return JSONResponse(status_code=400, content={"msg": "El concepto necesita un nombre."})
                await db.execute("INSERT INTO tipos_solicitud (nombre, tipo, requiere_foto, descuenta_dias, horas_por_dia) VALUES ($1,$2,$3,$4,$5) ON CONFLICT (nombre) DO UPDATE SET tipo=EXCLUDED.tipo, requiere_foto=EXCLUDED.requiere_foto, descuenta_dias=EXCLUDED.descuenta_dias, horas_por_dia=EXCLUDED.horas_por_dia", nombre, str(form.get('tipo')), int(form.get('foto')), int(form.get('desc')), float(form.get('horas')))
            elif action == "borrar_concepto":
                await db.execute("DELETE FROM tipos_solicitud WHERE nombre=$1", str(form.get('nombre')))
            elif action == "guardar_config":
                await db.execute("UPDATE configuracion SET empresa_nombre=$1, color_primario=$2, distancia_gps=$3, tolerancia_tarde=$4, anti_rebote_min=$5, vac_anticipo_dias=$6, intentos_login=$7, jornada_minima_hs=$8, franco_manana_ingreso=$9, franco_tarde_salida=$10, gps_estricto=$11, encargados_aprueban=$12, pw_prefijo=$13, pw_sufijo=$14, vacaciones_base=$15 WHERE id=1", str(form.get('empresa')), str(form.get('color')), float(form.get('gps')), int(form.get('tol')), int(form.get('anti')), int(form.get('vac_ant')), int(form.get('intentos')), float(form.get('jornada')), str(form.get('f_manana')), str(form.get('f_tarde')), int(form.get('gps_est')), int(form.get('enc_aprueba')), str(form.get('pw_pre')), str(form.get('pw_suf')), int(form.get('vac_base')))

            elif action == "guardar_logo":
                logo = form.get("logo")
                if logo and hasattr(logo, 'filename') and logo.filename:
                    raw = await logo.read(5 * 1024 * 1024)
                    ext = check_magic_bytes(raw)
                    if ext in ['png', 'jpg']:
                        with open(os.path.join("uploads", "favicon.png"), "wb") as f: f.write(raw)
                        return {"msg": "Logo corporativo actualizado de manera correcta."}
                return JSONResponse(status_code=400, content={"msg": "Archivo no admitido."})

            elif action == "importar_csv":
                archivo = form.get("archivo_csv")
                if not archivo or not hasattr(archivo, 'filename'): return JSONResponse(status_code=400, content={"msg": "Archivo requerido."})
                raw = await archivo.read(2 * 1024 * 1024)
                try:
                    cfg = await db.fetchrow("SELECT vacaciones_base FROM configuracion WHERE id=1")
                    v_base = cfg['vacaciones_base'] if cfg and cfg['vacaciones_base'] else 14

                    text = raw.decode('utf-8-sig')
                    reader = csv.DictReader(io.StringIO(text), delimiter=';')
                    nuevos, actualizados, credenciales = 0, 0, []
                    async with db.transaction():
                        for i, row in enumerate(reader, start=2):
                            if 'dni' not in row or 'nombre' not in row: raise CSVInvalido(f"Fila {i}: Falta DNI o Nombre.")
                            dni = str(row['dni']).strip()
                            if not dni: continue
                            existe = await db.fetchval("SELECT 1 FROM usuarios WHERE dni=$1", dni)
                            if existe:
                                # No se toca la clave ni req_cambio de usuarios existentes: solo datos.
                                await db.execute("UPDATE usuarios SET nombre=$2, rol=$3, sucursal=$4, hora_entrada=$5, hora_salida=$6, dias_vacaciones=$7, activo=1, fecha_baja=NULL WHERE dni=$1", dni, row['nombre'].strip(), int(row.get('rol', 2)), row.get('sucursal','').strip(), row.get('hora_entrada','09:00'), row.get('hora_salida','18:00'), int(row.get('dias_vacaciones', v_base)))
                                actualizados += 1
                            else:
                                temp_pw = gen_temp_pw()
                                hashed = await asyncio.to_thread(hash_pw, temp_pw)
                                await db.execute("INSERT INTO usuarios (dni,nombre,rol,sucursal,hora_entrada,hora_salida,password,activo,dias_vacaciones,req_cambio,fecha_baja) VALUES ($1,$2,$3,$4,$5,$6,$7,1,$8,1,NULL)", dni, row['nombre'].strip(), int(row.get('rol', 2)), row.get('sucursal','').strip(), row.get('hora_entrada','09:00'), row.get('hora_salida','18:00'), hashed, int(row.get('dias_vacaciones', v_base)))
                                credenciales.append({"dni": dni, "clave": temp_pw})
                                nuevos += 1
                    return {"msg": f"Importación completada: {nuevos} nuevos, {actualizados} actualizados. Las claves provisorias se muestran una sola vez.", "credenciales": credenciales}
                except CSVInvalido as e:
                    # Mensaje armado por la validacion de arriba (sin detalles internos).
                    return JSONResponse(status_code=400, content={"msg": str(e)})
                except (UnicodeDecodeError, ValueError, KeyError) as e:
                    logger.warning("Importacion de CSV rechazada: %r", e)
                    return JSONResponse(status_code=400, content={"msg": "No se pudo leer el CSV: revisar que sea UTF-8, separado por punto y coma, con las columnas esperadas y valores numericos validos."})

        if action == "guardar_convocados":
            fecha = form.get('d2')
            suc_target = form.get('d3')
            dnis_str = form.get('d1')
            dnis = dnis_str.split(',') if dnis_str else []
            if adm['rol'] == 1: suc_target = adm['sucursal']
            limite = datetime.strptime(fecha, "%Y-%m-%d").replace(hour=18, minute=0, second=0) - timedelta(days=1)
            if datetime.now() > limite: return JSONResponse(status_code=400, content={"msg": "Tiempo límite operativo excedido."})

            valid_dnis = []
            for d in dnis:
                if not d: continue
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", str(d))
                if tgt and tgt['sucursal'] == suc_target: valid_dnis.append(d)

            async with db.transaction():
                await db.execute("DELETE FROM feriados_convocados WHERE fecha=$1 AND dni IN (SELECT dni FROM usuarios WHERE sucursal=$2)", str(fecha), str(suc_target))
                for d in valid_dnis:
                    await db.execute("INSERT INTO feriados_convocados (dni, fecha) VALUES ($1,$2) ON CONFLICT DO NOTHING", str(d), str(fecha))

        elif action == "crear_user":
            if adm['rol'] != 0: return JSONResponse(status_code=403, content={"msg": "Acceso denegado."})
            cfg = await db.fetchrow("SELECT vacaciones_base FROM configuracion WHERE id=1")
            v_base = cfg['vacaciones_base'] if cfg and cfg['vacaciones_base'] else 14

            d1, d2, d3, d4, d5, d6 = form.get('d1').strip(), form.get('d2'), int(form.get('d3','2')), form.get('d4'), form.get('d5'), form.get('d6')
            d9 = int(form.get('d9', v_base))

            temp_pw = gen_temp_pw()
            hashed = await asyncio.to_thread(hash_pw, temp_pw)
            res = await db.execute("INSERT INTO usuarios (dni,nombre,rol,sucursal,hora_entrada,hora_salida,password,activo,dias_vacaciones,req_cambio) VALUES ($1,$2,$3,$4,$5,$6,$7,1,$8,1) ON CONFLICT (dni) DO NOTHING", str(d1), str(d2), int(d3), str(d4), str(d5), str(d6), hashed, int(d9))
            if res == "INSERT 0 0":
                return JSONResponse(status_code=400, content={"msg": "Ya existe un usuario con ese DNI."})
            return {"msg": f"Registro creado. Credencial provisoria (mostrar una sola vez): {temp_pw}"}

        elif action == "editar_user":
            d1, d2, d3, d4, d5, d6, d8, d9 = form.get('d1').strip(), form.get('d2'), int(form.get('d3','2')), form.get('d4'), form.get('d5'), form.get('d6'), int(form.get('d8','1')), int(form.get('d9','14'))
            d_new = str(form.get('d_new', d1)).strip()
            if adm['rol'] == 1:
                # Un encargado solo edita empleados (rol 2) de su sucursal y no puede:
                # asignar rol admin/encargado, mover de sucursal, ni renombrar el DNI. Asi no
                # puede escalar privilegios ni editarse a si mismo el rol (es rol 1, no rol 2).
                tgt = await db.fetchrow("SELECT sucursal, rol FROM usuarios WHERE dni=$1", str(d1))
                if not tgt or tgt['sucursal'] != adm['sucursal']:
                    return JSONResponse(status_code=403, content={"msg": "Usuario no correspondiente a la jurisdicción."})
                if tgt['rol'] in (0, 1):
                    return JSONResponse(status_code=403, content={"msg": "No puede editar administradores ni encargados."})
                d3 = 2
                d4 = adm['sucursal']
                d_new = str(d1)
            calle, altura, depto, cp, mail, tel = form.get('calle',''), form.get('altura',''), form.get('depto',''), form.get('cp',''), form.get('mail',''), form.get('tel','')
            mapa_file = form.get("mapa")
            filename_mapa = None

            curr_u = await db.fetchrow("SELECT activo, fecha_baja FROM usuarios WHERE dni=$1", str(d1))
            f_baja = curr_u['fecha_baja'] if curr_u else None

            # Lógica transaccional de estado (Asignación de Fecha de Baja)
            if curr_u and curr_u['activo'] == 1 and d8 == 0:
                f_baja = datetime.now().strftime("%Y-%m-%d")
            elif d8 == 1:
                f_baja = None

            if mapa_file and hasattr(mapa_file, 'filename') and mapa_file.filename:
                raw = await mapa_file.read(5 * 1024 * 1024 + 1)
                ext = check_magic_bytes(raw)
                if ext:
                    filename_mapa = f"map_{uuid.uuid4().hex}.{ext}"
                    with open(os.path.join("uploads", filename_mapa), "wb") as f: f.write(raw)

            if filename_mapa:
                await db.execute("UPDATE usuarios SET dni=$1, nombre=$2, rol=$3, sucursal=$4, hora_entrada=$5, hora_salida=$6, activo=$7, dias_vacaciones=$8, calle=$9, altura=$10, depto=$11, cp=$12, mail=$13, telefono=$14, mapa=$15, fecha_baja=$17 WHERE dni=$16", d_new, str(d2), int(d3), str(d4), str(d5), str(d6), d8, int(d9), str(calle), str(altura), str(depto), str(cp), str(mail), str(tel), filename_mapa, str(d1), f_baja)
            else:
                await db.execute("UPDATE usuarios SET dni=$1, nombre=$2, rol=$3, sucursal=$4, hora_entrada=$5, hora_salida=$6, activo=$7, dias_vacaciones=$8, calle=$9, altura=$10, depto=$11, cp=$12, mail=$13, telefono=$14, fecha_baja=$16 WHERE dni=$15", d_new, str(d2), int(d3), str(d4), str(d5), str(d6), d8, int(d9), str(calle), str(altura), str(depto), str(cp), str(mail), str(tel), str(d1), f_baja)

        elif action == "reset_pass":
            dni_target = form.get('d1').strip()
            if adm['rol'] == 1:
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", dni_target)
                if not tgt or tgt['sucursal'] != adm['sucursal']: return JSONResponse(status_code=403, content={"msg": "Jurisdicción denegada."})

            temp_pw = gen_temp_pw()
            hashed = await asyncio.to_thread(hash_pw, temp_pw)
            await db.execute("UPDATE usuarios SET password=$1, req_cambio=1, intentos=0, bloqueado_hasta=NULL WHERE dni=$2", hashed, dni_target)
            # Cierra todas las sesiones abiertas del usuario reseteado.
            await sessions.revoke_all_sessions_for_user(DB.pool, dni_target)
            return {"msg": f"Clave reseteada. Nueva credencial (mostrar una sola vez): {temp_pw}"}

        elif action == "desbloquear_user":
            if adm['rol'] != 0: return JSONResponse(status_code=403, content={"msg": "Acceso denegado."})
            dni_target = form.get('d1').strip()
            await db.execute("UPDATE usuarios SET intentos=0, bloqueado_hasta=NULL WHERE dni=$1", dni_target)
            return {"msg": "ok"}

        elif action == "salida_manual":
            fich_id = int(form.get('d1'))
            d2 = form.get('d2')
            if not re.match(r'^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$', d2): return JSONResponse(status_code=400, content={"msg": "Formato de hora incorrecto."})

            fich = await db.fetchrow("SELECT dni FROM fichajes WHERE id=$1", fich_id)
            if not fich: return JSONResponse(status_code=404, content={"msg": "Registro inexistente."})

            if adm['rol'] == 1:
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", fich['dni'])
                if not tgt or tgt['sucursal'] != adm['sucursal']: return JSONResponse(status_code=403, content={"msg": "Empleado fuera de jurisdicción."})

            await db.execute("UPDATE fichajes SET salida_manual=$1, motivo_salida=$2 WHERE id=$3", str(d2), str(form.get('d3')), fich_id)

        elif action == "corregir_entrada":
            fich_id = int(form.get('d1'))
            nueva_hora = form.get('d2')
            justificante = form.get('d3')
            if not re.match(r'^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$', nueva_hora) or not justificante or str(justificante).strip() == "":
                return JSONResponse(status_code=400, content={"msg": "Información requerida faltante."})

            fich = await db.fetchrow("SELECT dni, fecha_hora FROM fichajes WHERE id=$1", fich_id)
            if not fich: return JSONResponse(status_code=404, content={"msg": "Registro inexistente."})

            if adm['rol'] == 1:
                tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", fich['dni'])
                if not tgt or tgt['sucursal'] != adm['sucursal']: return JSONResponse(status_code=403, content={"msg": "Fuera de jurisdicción."})

            fecha_base = fich['fecha_hora'].split(' ')[0]
            nueva_fecha_hora = f"{fecha_base} {nueva_hora}:00"
            usr = await db.fetchrow("SELECT hora_entrada FROM usuarios WHERE dni=$1", fich['dni'])
            cfg = await db.fetchrow("SELECT tolerancia_tarde, franco_manana_ingreso FROM configuracion WHERE id=1")

            franco_corr = await db.fetchrow("SELECT turno FROM mediofrancos WHERE dni=$1 AND fecha=$2", fich['dni'], fecha_base)

            tol = cfg['tolerancia_tarde'] if cfg else 10
            h_ent_str = usr['hora_entrada'] if usr else "09:00"
            t_limite = datetime.strptime(h_ent_str, "%H:%M") + timedelta(minutes=tol)
            t_nueva = datetime.strptime(nueva_hora, "%H:%M")

            if franco_corr:
                tarde = 0
            else:
                tarde = 1 if t_nueva > t_limite else 0

            await db.execute("UPDATE fichajes SET fecha_hora=$1, tarde=$2, motivo_entrada=$3 WHERE id=$4", nueva_fecha_hora, tarde, justificante.strip(), fich_id)

        elif action == "asignar_franco":
            d1_raw = form.get('d1')
            d1 = d1_raw.split(' - ')[-1].strip() if ' - ' in d1_raw else d1_raw.strip()

            d2, d3 = form.get('d2'), form.get('d3')
            f_dt = datetime.strptime(d2, "%Y-%m-%d")
            dias_para_restar = f_dt.weekday() + 2
            limite = (f_dt - timedelta(days=dias_para_restar)).replace(hour=12, minute=0, second=0)
            if adm['rol'] == 1 and datetime.now() > limite: return JSONResponse(status_code=400, content={"msg": "El límite de tiempo para esta acción ha expirado."})

            tgt = await db.fetchrow("SELECT sucursal FROM usuarios WHERE dni=$1", str(d1))
            if tgt and (adm['rol'] == 0 or tgt['sucursal'] == adm['sucursal']):
                await db.execute("INSERT INTO mediofrancos (dni, fecha, turno, asignado_por) VALUES ($1,$2,$3,$4)", str(d1), str(d2), str(d3), str(adm['nombre']))
            else: return JSONResponse(status_code=400, content={"msg": "La asignación no es válida."})

        elif action == "estado_solicitud":
            cfg = await db.fetchrow("SELECT encargados_aprueban FROM configuracion WHERE id=1")
            puede_aprobar = True if adm['rol'] == 0 else (cfg and cfg['encargados_aprueban'] == 1)

            if not puede_aprobar:
                return JSONResponse(status_code=403, content={"msg": "Permisos insuficientes para esta operación."})

            d1, d2, d3, d4 = form.get('d1'), form.get('d2'), form.get('d3'), form.get('d4')
            sol = await db.fetchrow("SELECT s.dni, s.concepto, s.horas, s.estado, s.fecha_ausencia, s.fecha_fin, ts.tipo, ts.descuenta_dias, ts.horas_por_dia FROM solicitudes s JOIN tipos_solicitud ts ON s.concepto=ts.nombre WHERE s.id=$1", int(d1))
            if sol:
                async with db.transaction():
                    if sol['tipo'] == 'DIAS' and d2 == 'APROBADA':
                        try:
                            n_in = datetime.strptime(d3, "%Y-%m-%d") if d3 else datetime.strptime(sol['fecha_ausencia'], "%Y-%m-%d")
                            n_fi = datetime.strptime(d4, "%Y-%m-%d") if d4 else datetime.strptime(sol['fecha_fin'], "%Y-%m-%d")
                            if n_fi < n_in: return JSONResponse(status_code=400, content={"msg": "Inconsistencia en las fechas proporcionadas."})
                            n_d = (n_fi - n_in).days + 1
                            if sol['descuenta_dias'] == 1 and sol['estado'] != 'APROBADA':
                                await db.execute("UPDATE usuarios SET dias_vacaciones = dias_vacaciones - $1 WHERE dni=$2", int(n_d), sol['dni'])
                            await db.execute("UPDATE solicitudes SET estado=$1, fecha_ausencia=$2, fecha_fin=$3, horas=$4 WHERE id=$5", str(d2), n_in.strftime("%Y-%m-%d"), n_fi.strftime("%Y-%m-%d"), float(n_d * float(sol['horas_por_dia'] if sol['horas_por_dia']>0 else 1)), int(d1))
                        except ValueError: return JSONResponse(status_code=400, content={"msg": "Formato de fecha no válido."})
                    else:
                        if sol['descuenta_dias'] == 1 and sol['estado'] == 'APROBADA' and d2 != 'APROBADA':
                            await db.execute("UPDATE usuarios SET dias_vacaciones = dias_vacaciones + $1 WHERE dni=$2", int(sol['horas']), sol['dni'])
                        await db.execute("UPDATE solicitudes SET estado=$1 WHERE id=$2", str(d2), int(d1))
    return {"msg": "ok"}


@router.get("/api/reporte_excel")
async def reporte_excel(request: Request, d_desde: str, d_hasta: str, suc: str="", dni: str="", adm: dict = Depends(requiere_panel)):
    if adm['rol'] == 1:
        suc = adm['sucursal']

    desde = datetime.strptime(d_desde, "%Y-%m-%d")
    hasta = datetime.strptime(d_hasta, "%Y-%m-%d")
    async with get_db() as db:
        p = []
        q = "SELECT * FROM usuarios WHERE 1=1"
        if suc:
            p.append(suc)
            q += f" AND sucursal=${len(p)}"
        if dni:
            p.append(dni)
            q += f" AND dni=${len(p)}"

        empleados_raw = [dict(r) for r in await db.fetch(q, *p)]
        empleados = []

        # Filtro de inclusión inteligente basado en fecha de corte
        for e in empleados_raw:
            if e['activo'] == 1:
                empleados.append(e)
            elif e['fecha_baja'] and e['fecha_baja'] >= d_desde:
                empleados.append(e)

        sucs_db = {row['nombre']: dict(row) for row in await db.fetch("SELECT * FROM sucursales")}

        fich_map = {}
        for r in await db.fetch("SELECT * FROM fichajes WHERE fecha_hora BETWEEN $1 AND $2", d_desde, d_hasta+' 23:59:59'):
            fich_map.setdefault(r['dni'], {})[r['fecha_hora'][:10]] = dict(r)

        fran_map = {(r['dni'], r['fecha']): r['turno'] for r in await db.fetch("SELECT dni, fecha, turno FROM mediofrancos WHERE fecha BETWEEN $1 AND $2", d_desde, d_hasta)}
        fer_map = {r['fecha']: r['sucs_abren'] for r in await db.fetch("SELECT fecha, sucs_abren FROM feriados WHERE fecha BETWEEN $1 AND $2", d_desde, d_hasta)}
        convocados_set = {(r['dni'], r['fecha']) for r in await db.fetch("SELECT dni, fecha FROM feriados_convocados WHERE fecha BETWEEN $1 AND $2", d_desde, d_hasta)}
        multidias_db = [dict(r) for r in await db.fetch("SELECT s.dni, s.concepto, s.fecha_ausencia, s.fecha_fin, ts.descuenta_dias, ts.horas_por_dia FROM solicitudes s JOIN tipos_solicitud ts ON s.concepto=ts.nombre WHERE ts.tipo='DIAS' AND s.estado='APROBADA'")]

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quotechar='"')

    writer.writerow(['DNI', 'Nombre', 'Sucursal', 'Días Trabajados', 'Llegadas Tarde', 'Cantidad Faltas Totales', 'Fechas de Faltas', 'Horas Totales', 'Días Vacaciones Tomados'])
    def scsv(v): return "'" + str(v) if str(v).startswith(('=','+','-','@')) else str(v)

    for e in empleados:
        curr = desde
        total_hs, tardes, faltas, dias_trabajados, dias_vacaciones = 0, 0, 0, 0, 0
        fechas_faltas = []

        while curr <= hasta:
            f_str = curr.strftime("%Y-%m-%d")

            # Aplicación de regla de negocio: Omisión contable post-baja
            if e['activo'] == 0 and e['fecha_baja'] and f_str > e['fecha_baja']:
                curr += timedelta(days=1)
                continue

            fer_abren = fer_map.get(f_str)
            es_feriado_abierto = fer_abren and (fer_abren == 'TODAS' or e['sucursal'] in fer_abren)
            permiso_multidia = next((v for v in multidias_db if v['dni'] == e['dni'] and v['fecha_ausencia'] <= f_str <= v['fecha_fin']), None)

            if permiso_multidia:
                if curr.weekday() != 6:
                    if permiso_multidia['descuenta_dias'] == 1: dias_vacaciones += 1
                    if permiso_multidia['horas_por_dia'] > 0:
                        total_hs += permiso_multidia['horas_por_dia']
            elif curr.weekday() != 6:
                fich = fich_map.get(e['dni'], {}).get(f_str)
                if fich:
                    dias_trabajados += 1
                    franco = fran_map.get((e['dni'], f_str))
                    if fich['tarde'] and not franco: tardes += 1

                    h_in = datetime.strptime(fich['fecha_hora'], "%Y-%m-%d %H:%M:%S").time()
                    if fich['salida_manual']: h_out = datetime.strptime(fich['salida_manual'], "%H:%M").time()
                    else:
                        if es_feriado_abierto:
                            cierre_suc = sucs_db[e['sucursal']]['hora_cierre_feriado']
                            h_out = min(datetime.strptime(cierre_suc, "%H:%M") + timedelta(minutes=30), datetime.strptime(cierre_suc, "%H:%M")).time()
                        else:
                            cierre_suc = sucs_db[e['sucursal']]['hora_cierre']
                            h_out_limit = min(datetime.strptime(cierre_suc, "%H:%M") + timedelta(minutes=30), datetime.strptime(e['hora_salida'], "%H:%M"))
                            if franco == 'TARDE': h_out_limit = min(h_out_limit, datetime.strptime("12:00", "%H:%M"))
                            h_out = h_out_limit.time()
                    hs = (h_out.hour * 60 + h_out.minute - h_in.hour * 60 - h_in.minute) / 60
                    total_hs += max(0, hs)
                else:
                    if es_feriado_abierto and ((e['dni'], f_str) in convocados_set):
                        faltas += 1
                        fechas_faltas.append(f_str)
                    elif not fer_abren:
                        faltas += 1
                        fechas_faltas.append(f_str)
            curr += timedelta(days=1)

        faltas_str = " | ".join(fechas_faltas) if fechas_faltas else "-"
        writer.writerow([scsv(e['dni']), scsv(e['nombre']), scsv(e['sucursal']), dias_trabajados, tardes, faltas, scsv(faltas_str), round(total_hs, 2), dias_vacaciones])

    r = Response(content=output.getvalue().encode('utf-8-sig'), media_type="text/csv")
    r.headers["Content-Disposition"] = 'attachment; filename="Reporte_Consolidated.csv"'
    return r
