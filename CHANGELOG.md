# Notas de los parches

Cambios de JZPass, del más nuevo al más viejo. Cada entrada corresponde a un push a `main`.

## 2.13.0 — 2026-11-11

Tag `v2.13.0`.

### Nuevo
- **Desactivar sucursales:** en Sucursales cada tarjeta tiene **Desactivar / Reactivar** (columna nueva
  `sucursales.activa`, se agrega sola). Una sucursal inactiva deja de aparecer para asignar personal, convocar,
  abrir en feriados, en el tablero en vivo y en la plantilla CSV, pero conserva fichajes, reportes e historial;
  en los filtros de Asistencias, Empleados y Reportes figura como "(inactiva)". No se puede desactivar con
  empleados activos asignados (reasignarlos o darlos de baja primero). `/api/v1/sucursales` devuelve `activa`.

### Arreglado
- **Eliminar sucursal ya no deja datos huérfanos:** el servidor rechaza el borrado si la sucursal tiene
  empleados o fichajes (antes borraba la fila y los empleados quedaban sin local, con el fichaje roto).

## 2.12.0 — 2026-11-11

Tag `v2.12.0`.

### Nuevo
- **Dos documentos por concepto:** en Ajustes > Conceptos, "Documentos: uno al pedir / dos: al pedir y al
  volver". Con dos, la solicitud aprobada pide la **constancia de cierre** cuando termina el permiso (pasó la
  fecha hasta, o la fecha más la hora de regreso). Columnas nuevas `tipos_solicitud.requiere_cierre` y
  `solicitudes.archivo_cierre` (se agregan solas al arrancar).
- **Aviso de documentación pendiente en la app:** la campana y el Inicio suman los permisos terminados sin
  constancia, la pestaña Avisos los lista con el botón "Subir constancia" y la tarjeta de la solicitud muestra
  "Falta la constancia de cierre · Subir". `POST /api/solicitud/adjuntar` recibe `cual=inicio|cierre` y valida
  (concepto con cierre, solicitud aprobada, permiso terminado; el de inicio solo mientras está pendiente).
- **Panel:** bandeja **Falta documentación** en Solicitudes, aviso en "Requiere tu atención" del Inicio, los dos
  documentos en el detalle, y la ficha del empleado abre **Historial y documentos** (cada solicitud con sus
  adjuntos y el total de documentos).
- **Feriados en varias sucursales:** "Sucursales que abren" pasa de un desplegable de una sola a casilleros
  (Todas / cada sucursal); se guarda la lista separada por coma en `feriados.sucs_abren` (sin cambio de
  esquema). Al guardar un feriado con sucursales abiertas se abre directo la convocatoria del día.

### Arreglado
- **El campo de adjunto en la app aparecía solo con certificado "Obligatorio":** con "Opcional" no se podía
  adjuntar nada. Ahora se muestra siempre (con el texto según el concepto) y, si falta, la solicitud pendiente
  tiene "Adjuntar documento".
- **"Ver / editar personal convocado" se abría debajo del panel del día** (mismo z-index, antes en el DOM) y
  no se podía elegir a nadie. Ahora el panel del día se cierra al abrir la convocatoria. El modal avisa si el
  día no tiene feriado o la sucursal no abre ese día.
- **El administrador puede corregir la convocatoria después de las 18:00 del día anterior** (el reporte la usa
  para marcar falta); el límite sigue para el encargado.
- **Feriado con "sucursales que abren" vacío marcaba Falta a todos** en el reporte; ahora cuenta como feriado
  cerrado. La comparación de sucursal en feriados era por subcadena ("Centro" coincidía con "Centro Norte");
  ahora es exacta (`database.sucursal_abre`, compartida por fichaje, reporte y panel).

## 2.11.0 — 2026-11-07

Tag `v2.11.0`.

### Nuevo
- **Panel de administración rediseñado** (`dashboard.html`) según el handoff `design_handoff_jzpass_admin`:
  navegación lateral oscura por grupos (Operación, Comunicación, Administración) con contador de solicitudes
  pendientes, buscador **Ctrl+K** (módulos, acciones y empleados), formularios en panel lateral derecho
  (clic afuera o Esc cierran), avisos en toast y modo claro/oscuro con la misma clave de `localStorage`.
- **Inicio como tablero en vivo:** KPIs (presentes, llegadas tarde, pendientes, alertas de fichaje),
  presentismo por sucursal con barra apilada, histograma de llegadas cada 15 minutos con la línea de
  tolerancia, lista "Requiere tu atención" (fuera de radio, sin fichar, pendientes, caducadas, anuncios con
  firmas pendientes) y "Próximos 30 días".
- **Asistencias** con dos modos: *En vivo* (una tarjeta por sucursal con el estado de cada persona) y
  *Registros* (tabla con total de horas y badge de GPS, ausentes incluidos a pedido, reporte Excel).
- **Solicitudes como bandeja:** pestañas Pendientes / Aprobadas / En curso / Culminadas / Rechazadas /
  Caducadas, lista a la izquierda y detalle a la derecha con datos, adjunto, impacto (vacaciones, cobertura
  de la sucursal ese día, solicitudes del año) e historial; aprobar, rechazar, revocar o archivar desde el
  detalle (con edición de fechas en las de varios días).
- **Empleados con ficha:** lista con buscador y "Mostrar Inactivos", ficha con horas del mes, llegadas
  tarde, fichajes fuera de radio, datos del legajo, documento adjunto, historial y últimos fichajes;
  acciones Editar, Restablecer clave, Dar de baja / Reactivar y Desbloquear.
- **Sucursales** en tarjetas (coordenadas, radio GPS, personas, horarios) con Editar y "Ver personal";
  **Personalización** con muestras de color y vista previa del portal; **Ajustes** por grupos con
  interruptores para los sí/no, tipos de solicitud en tarjetas (editar o borrar) e importación CSV con
  zona para soltar el archivo, plantilla descargable y las claves provisorias de los nuevos mostradas al
  terminar (antes se descartaban).
- Calendario con celdas por día, eventos coloreados por tipo y lista "Este mes"; al tocar un día se
  gestionan feriado (con quitar), convocatoria y medio franco desde el mismo panel.

### Notas
- Solo frontend: no cambian endpoints ni base de datos. Lo que el diseño pedía y la API no expone
  (fichaje manual de un empleado sin registro, comentario al rechazar, ausencias históricas, fecha de
  ingreso a la empresa, borradores de anuncios) se omitió en vez de inventarlo.
- Las fuentes del diseño (Instrument Sans, JetBrains Mono) se usan si están instaladas; el CSP no permite
  Google Fonts, así que de lo contrario se usa la fuente del sistema.

## 2.10.2 — 2026-11-06

Tag `v2.10.2`.

### Arreglado
- **El administrador administra desde la app:** pestaña **Admin** en la barra inferior (abre el panel `/panel`) y
  botón "Administrar el sistema" en Legajo. La 2.10.1 lo había quitado por una mala lectura del pedido.
- **Agenda solo para el administrador:** el encargado tampoco la ve (en 2.10.1 la conservaba). El empleado sigue sin
  verla. El encargado conserva su acceso al panel desde Legajo.

## 2.10.1 — 2026-11-06

Tag `v2.10.1`.

### Cambiado
- **Agenda solo para encargado y administrador:** el empleado ya no ve la pestaña Agenda ni el acceso "Próximo medio
  franco" (veía únicamente lo propio: feriados, sus medios francos y sus vacaciones aprobadas; nunca datos de otros).
- **El administrador no administra desde la app:** se quita el acceso al panel desde Legajo para el rol 0; el panel
  sigue en `/panel`. El encargado conserva su acceso (medios francos y convocatorias se asignan ahí).
- **Ícono de la app instalada:** el glifo JZ queda centrado y más grande sobre azul con degradé, dentro de la zona
  segura del recorte de Android; se suman `icono-192.png`, `icono-512.png` (manifest) e `icono-180.png`
  (`apple-touch-icon`, iPhone no acepta SVG). El `icono.svg` queda como alternativa.

## 2.10.0 — 2026-11-06

Tag `v2.10.0`. Solo frontend: no cambia la API ni la base.

### Cambiado (app móvil nueva para empleados y encargados)
- `index.html` rehecho según el diseño `design_handoff_jzpass_mobile` (tono "fiel"): header con campana, contenido por
  pestañas y barra inferior. **Fichaje** (tarjeta con horas de hoy, ingreso, salida y GPS; botón único que pulsa hasta
  el ingreso y pasa a rojo para la salida; accesos a vacaciones, solicitudes en curso, próximo medio franco y avisos),
  **Permisos** (solicitudes con estado, adjunto y cancelar; hoja inferior para la nueva solicitud con chips de
  concepto, fechas u horas según el tipo y certificado cuando el concepto lo exige), **Agenda** (calendario con
  feriados, vacaciones, medios francos y convocatorias; lista de medios francos), **Legajo** (datos, tema, panel
  para admin y encargado, cerrar sesión, privacidad y términos). Los **avisos** (anuncios con firma de recibido)
  salen de la campana. Login, configuración inicial y cambio de clave provisoria con el mismo estilo.
- **Encargado:** pestaña **Aprobar** con las solicitudes pendientes de su sucursal (aprobar o rechazar), visible solo
  si "encargados aprueban" está activo. Asignar medios francos y convocatorias quedan en el panel (`/panel`).
- Lo que la API del empleado no devuelve no se muestra (sin historial de fichajes ni horas del mes, horario, correo
  o teléfono): decisión de no agregar endpoints para la app.

### Agregado
- **Instalable en el celular (PWA):** `manifest.webmanifest`, `icono.svg` y `sw.js` (servido por `main.py` con la
  versión para renovar la caché en cada release). Guarda solo el cascarón; `/api` nunca se cachea y sin red el
  fichaje avisa el error.

## 2.9.0 — 2026-11-06

Tag `v2.9.0`. Tabla nueva `claves_api` (se crea sola al arrancar).

### Agregado (API para integraciones, como en Flex y Tracker360)
- **Claves de API** en Ajustes del Sistema > Integraciones (API), solo administrador: se generan con un nombre, se
  muestran una sola vez (`jzp_...`), se guardan como hash SHA-256, se ve el último uso y se revocan desde la misma
  pantalla. Se mandan como `Authorization: Bearer jzp_...`, sin sesión ni CSRF. Solo lectura.
- **API `/api/v1`** con esa clave: `GET /api/v1/reportes/asistencia?desde&hasta&sucursal&dni&tipo=resumido|detallado&formato=json|csv`
  (el mismo reporte del panel, incluidos los dados de baja dentro del período; `csv` baja el mismo archivo),
  `GET /api/v1/empleados?sucursal&activos` (sin contacto ni claves) y `GET /api/v1/sucursales`. Errores con
  `{"detail": ...}` y 401 con `WWW-Authenticate: Bearer`, como las otras apps.
- Sirve para armar un informe automático (n8n → WhatsApp, planilla) sin crear un usuario de solo lectura en la base.

### Cambiado
- El cálculo del reporte quedó en `calcular_asistencia` + `resumen_asistencia` + `csv_asistencia` (admin.py) y lo
  comparten el CSV del panel y la API; el CSV no cambia.
- `jztech-core` 0.1.7: el test de rutas protegidas vuelve a ver las rutas de los routers con FastAPI 0.143 (antes
  pasaba en vacío) y ahora comprueba sesión en todo salvo `/api/v1`, y clave de API en `/api/v1`.

### Por qué
- Flex y Tracker ya tenían API con clave y JZPass no: para automatizar el reporte por WhatsApp hubo que crear un
  usuario de solo lectura en Postgres. Ese usuario ya se puede dar de baja.

## 2.8.0 — 2026-11-06

Tag `v2.8.0`.

### Agregado (fecha de baja visible y editable)
- El legajo muestra el campo "Fecha de baja" cuando el estado es Inactivo. Si se deja vacío al desactivar, se
  completa con la fecha del día (como hasta ahora). Se puede corregir después: sirve para poner el último día
  real de trabajo y para completar las bajas viejas que quedaron sin fecha.
- La lista de usuarios, con "Mostrar Inactivos", muestra la fecha de baja al lado del estado.

### Por qué
- El reporte de asistencia ya incluía a los dados de baja hasta su fecha de baja, pero los desactivados antes
  de que existiera ese campo quedaron sin fecha y no aparecían, y no había forma de verla ni cambiarla.

## 2.7.3 — 2026-10-20

Tag `v2.7.3`.

### Agregado (fichaje más claro para el empleado)
- Al fichar aparece un aviso grande en el centro de la pantalla: verde con tilde y "ENTRADA REGISTRADA" o
  "SALIDA REGISTRADA" con la hora, o rojo con cruz y "NO SE REGISTRÓ" con el motivo (fuera de rango, anti-rebote,
  jornada mínima, sin ubicación, etc.). Vibra en el celular. Se cierra con "Entendido", tocando afuera o con Esc.
- Cartel arriba en la vista del empleado con lo que ya fichó hoy: "Ya marcaste tu ENTRADA hoy a las HH:MM" o
  "Ya marcaste tu SALIDA hoy a las HH:MM (entrada HH:MM)".
- El botón cambia según el día: "Registrar Fichaje" sin fichar, "Marcar Salida" en rojo después de la entrada y
  "Jornada finalizada" (bloqueado) después de la salida.
- `GET /api/empleado/datos` devuelve `fichaje_hoy` (`{entrada, salida}` o `null`).

### Cambiado
- Panel de solicitudes: las solicitudes culminadas ya no muestran "Revocar Aprobación" (ni en la tarjeta ni en
  "ver más").

## 2.7.2 — 2026-10-15

Tag `v2.7.2`.

### Cambiado (dependencias alineadas en las cuatro apps)
- Mismas versiones en Tracker360, JZPass, JZTravell y JZ Middle: FastAPI 0.143.1 (Starlette 1.8.0), Uvicorn
  0.54.0, Pydantic 2.14.1, asyncpg 0.32.0, argon2-cffi 25.1.0, httpx 0.28.1, bcrypt 5.0.0 y `jztech-core` 0.1.6.
  Las dependencias indirectas se actualizaron a su última versión compatible. Todas tienen binarios para
  Python 3.11 a 3.13 (la instalación sin Docker sigue sin necesitar compilador).
- FastAPI agrega desde la 0.142 la dependencia `opentelemetry-api` (paquete oficial de OpenTelemetry).
- `jztech-core` 0.1.6: con bcrypt 5, una clave de más de 72 caracteres contra un hash bcrypt viejo ya no da error.
- Se quita la clave `version:` del `docker-compose.yml` (Docker la ignora y avisa que es obsoleta).

## 2.7.1 — 2026-10-14

Tag `v2.7.1`, publicado en GitHub Releases. Junta los cambios posteriores a 2.7.0.

### Cambiado (firma de anuncios)
- Para firmar el recibido de un anuncio se escribe el DNI en vez de la contraseña (nadie la recordaba). Acepta
  el DNI con o sin puntos; tiene que ser el del usuario que tiene la sesión abierta. Sigue el límite de 5
  intentos por minuto.

### Corregido (instalador con Docker)
- `install.sh` ya no levanta los contenedores con `--remove-orphans`. En un servidor compartido, Docker puede
  contar como "huérfanos" del proyecto contenedores de otras aplicaciones que quedaron con la misma etiqueta de
  proyecto, y los borraba. El contenedor de Caddy de las instalaciones 2.6.0 se sigue sacando por su nombre
  (`jzpass_caddy`).

## 2.7.0 — 2026-10-13

Tag `v2.7.0`, publicado en GitHub Releases. Junta los cambios posteriores a 2.6.0.

### Agregado (aviso de versión nueva)
- El administrador ve en el inicio del panel un aviso cuando hay una versión más nueva publicada en GitHub
  Releases, con el enlace a qué cambia y cómo actualizar (`sudo bash install.sh` con Docker, `sudo jzpass-actualizar`
  sin Docker). Solo informa: no descarga ni cambia nada. La consulta se guarda una hora; sin internet no muestra
  nada. La versión instalada se ve al pie del panel. Necesita salida a internet hacia `api.github.com`.

### Agregado (anuncios generales con firma de recibido)
- Módulo **Notificaciones** en el panel (solo administrador): publicar un anuncio (título y mensaje) que les llega
  a todos los usuarios activos en ese momento. Listado de 10 por página con vistos y firmados de cada anuncio,
  botón **Anular** (deja de mostrarse a los empleados; el registro se conserva) y **Ver detalles**: tabla
  deslizable de quién lo vio y quién lo firmó, con búsqueda y filtro (firmaron / vieron sin firmar / no lo
  vieron), y **Descargar Reporte** (CSV `;` con fecha de visto, fecha de firma e IP de la firma).
- En la pantalla del empleado, arriba del fichaje, **Avisos de la empresa**: los 3 más nuevos sin firmar (el resto
  con "Ver todos"). **Ver más** despliega el mensaje y registra el visto (la primera vez); **Aceptado / Recibido**
  pide la contraseña del empleado (para que no sea un clic sin querer), registra la firma con fecha, hora e IP y
  saca el aviso de la lista. Hasta 5 intentos de firma por minuto y por sesión.
- Tablas nuevas `anuncios` y `anuncio_lecturas` (se crean solas al arrancar). Rutas en `routers/anuncios.py`.

### Corregido (seguridad)
- `esc()` de `index.html` y `dashboard.html` no escapaba nada (cada carácter se reemplazaba por sí mismo desde
  septiembre): un motivo de solicitud o un nombre con HTML se ejecutaba en el panel. Ahora escapa `& < > ' "`.

### Cambiado (instaladores sin Caddy)
- `install.sh` (Docker) e `install-native.sh` ya no levantan ni instalan Caddy: instalan JZPass y lo dejan
  escuchando por http en su puerto (8000 con Docker, 8020 sin Docker) de todas las interfaces (`JZPASS_BIND` lo
  cambia). El HTTPS lo pone el proxy del servidor. Al terminar muestran dónde quedó escuchando, la dirección
  pública (`JZPASS_DOMAIN`, que queda en `ALLOWED_ORIGINS`) y el token inicial. `JZPASS_PROXY_IP=<IP>` suma a
  `TRUSTED_PROXIES` la IP de un proxy que esté en otro equipo. Se saca el servicio `caddy` y su perfil `https`
  del compose. `JZPASS_HTTPS`, `JZPASS_IP`, `JZPASS_HTTPS_PORT` y `JZPASS_CADDY` se ignoran con un aviso.

### Cómo migra una instalación existente
- Con Docker: volver a correr `sudo bash install.sh` en la carpeta de la instalación. Respalda la base, saca el
  contenedor `jzpass_caddy` (`docker rm -f`), la carpeta `caddy/` y las claves que ya no se
  usan del `.env` (`CADDY_*`, `JZPASS_HTTPS`, `JZPASS_IP`, `COMPOSE_PROFILES=https`), y la app pasa a escuchar en
  `0.0.0.0` (un `APP_BIND=127.0.0.1` puesto a mano sin Caddy se respeta). Los volúmenes de certificados de
  Caddy no se borran solos: el instalador muestra el `docker volume rm`. Una instalación anterior a Caddy
  (2.5.1, sin esas claves) se actualiza igual que siempre.
- Sin Docker: volver a correr `sudo ./install-native.sh` desde el clon (el actualizador solo cambia el código y
  avisa si el servicio sigue escuchando solo en `127.0.0.1`). Un Caddy configurado por una versión anterior no
  se desinstala (puede usarlo otra app): el instalador avisa cómo sacarlo.

## 2.6.0 — 2026-10-06

Tag `v2.6.0`, publicado en GitHub Releases. Junta los cambios posteriores a 2.5.1.

### Agregado (HTTPS en la instalación con Docker)
- `install.sh` configura HTTPS: levanta un contenedor de Caddy (`jzpass_caddy`, perfil `https` del compose)
  delante de la app. Con dominio (`JZPASS_DOMAIN=rrhh.empresa.com`, o contestando la pregunta) saca el
  certificado solo; sin dominio usa la IP del servidor con la CA local de Caddy y deja el certificado raíz en
  `caddy/ca-local.crt`. Si el 443 ya está en uso, queda en el primero libre entre 8443, 9443 y 10443. Al terminar
  muestra un aviso con la dirección y qué hacer con el certificado. Sin HTTPS no se podía iniciar sesión desde
  otra PC ni fichar con el GPS del celular. `JZPASS_HTTPS=no` lo desactiva.
- Al actualizar respalda la base en `backups/` antes de reconstruir, y sigue con la versión recién bajada del
  propio instalador. Una instalación nueva deja la app escuchando solo en el servidor (se entra por Caddy).
- Ya no instala el `docker-compose` viejo por separado: usa el plugin `docker compose` del Docker oficial.

### Cambiado (instalación sin Docker)
- `install-native.sh` rehecho con el mismo esquema que Tracker360 y JZTravell (Debian 12/13, Ubuntu 24.04):
  cada versión en su propia carpeta con su entorno de Python (`/opt/jzpass/releases`), los adjuntos aparte en
  `/var/lib/jzpass/uploads` (no se tocan al actualizar), código de solo lectura para el servicio y HTTPS con
  Caddy por dominio (certificado automático) o por la IP del servidor (antes usaba un nombre de prueba en
  `/etc/hosts`). Instala las dependencias sin compilar, verificando los hashes. Ya no apaga Apache: si ocupa el
  puerto 80, Caddy atiende solo HTTPS. Antes de seguir comprueba que la base acepte la clave del `.env`.
- Una instalación nativa anterior se pasa sola a este esquema al volver a correr el instalador, conservando la
  base, los secretos, el puerto, el dominio y los adjuntos.

### Agregado
- Actualizador `sudo jzpass-actualizar` (`--buscar`, `--volver`): arma la versión nueva aparte, respalda la
  base, cambia y verifica que responda; si no responde, vuelve sola a la anterior y, si el esquema cambió,
  restaura la base como estaba.
- `.gitattributes`: los scripts de Linux siempre con finales de línea LF.

## 2.5.1 — 2026-10-05

### Cambiado
- Reportes de asistencia (resumido y detallado): los empleados salen ordenados por nombre. Antes el orden
  dependía de la base y podía cambiar entre una descarga y otra.

### Corregido
- Barra lateral (2.5.0): con la barra cerrada no se veían los iconos de los módulos (el navegador centraba
  icono + nombre dentro del botón y el icono quedaba afuera). Ahora se ven cerrada, abierta y en el celular.
- El inicio de sesión informaba rol "empleado" (2) a los administradores (rol 0). La pantalla no lo usaba
  (toma el rol de otro lado), así que no cambia nada para el usuario; queda correcto para quien lo consulte.

## 2.5.0 — 2026-10-05

### Agregado
- Reporte de asistencia resumido o detallado. El resumido es el de siempre (una fila por empleado, con días
  trabajados, llegadas tarde, faltas, horas y vacaciones). El detallado muestra día por día cada jornada:
  estado (trabajado, falta, feriado, domingo o el concepto de la licencia), ingreso, salida (marcando cuando
  es estimada porque no se fichó), horas, llegada tarde, medio franco y los motivos. Los dos usan el mismo
  cálculo, así que los totales del detallado coinciden con el resumido.
- El reporte se puede sacar para un empleado en particular (o para todos, como hasta ahora), filtrando la
  lista por sucursal. El archivo lleva el tipo y el DNI en el nombre.

### Cambiado
- Barra lateral del panel igual que la de Tracker360: angosta con los iconos y, al pasar el mouse, se
  despliega con el nombre de cada sección. En el celular se abre con el botón de menú y muestra los nombres.

### Corregido
- Conceptos de solicitud: ya no se puede crear uno sin nombre (el panel avisa y el servidor lo rechaza;
  antes quedaba un concepto vacío en la lista). El botón "Añadir Parámetro" se bloquea mientras guarda,
  para no crearlo dos veces con un doble clic.

## 2026-09-30

### Cambiado
- Los tests automáticos ya no forman parte del repositorio: se mantienen aparte, fuera del
  código del sistema. No cambia nada del funcionamiento.
