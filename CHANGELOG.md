# Notas de los parches

Cambios de JZPass, del más nuevo al más viejo. Cada entrada corresponde a un push a `main`.

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
