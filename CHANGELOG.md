# Notas de los parches

Cambios de JZPass, del más nuevo al más viejo. Cada entrada corresponde a un push a `main`.

## Sin versión todavía (2026-10-05)

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
