# Notas de los parches

Cambios de JZPass, del más nuevo al más viejo. Cada entrada corresponde a un push a `main`.

## 2026-10-05

### Corregido
- Conceptos de solicitud: ya no se puede crear uno sin nombre (el panel avisa y el servidor lo rechaza;
  antes quedaba un concepto vacío en la lista). El botón "Añadir Parámetro" se bloquea mientras guarda,
  para no crearlo dos veces con un doble clic.

## 2026-09-30

### Cambiado
- Los tests automáticos ya no forman parte del repositorio: se mantienen aparte, fuera del
  código del sistema. No cambia nada del funcionamiento.
