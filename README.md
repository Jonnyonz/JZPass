# JZ PASS - ERP & Control de Asistencias

JZ PASS es un sistema de gestión de recursos humanos, control de asistencias (fichaje por GPS) y administración de solicitudes operativas. Construido bajo filosofía SRE (Site Reliability Engineering), prioriza la estabilidad, la concurrencia y la inmutabilidad de los datos.

Versión actual: v2.1 (Open Source Edition)
Desarrollado por: Jz TechSolutions (https://jz-tech.mywire.org/)

## Tecnologías

* **Backend:** Python 3.10+, FastAPI, Uvicorn.
* **Base de Datos:** PostgreSQL 15, Asyncpg (Transaccional).
* **Frontend:** HTML5, Vanilla JS, CSS3 (Sin frameworks pesados, carga en milisegundos).
* **Seguridad:** JWT (HttpOnly Cookies), Bcrypt, Prevención CSRF, validación Magic Bytes.
* **Infraestructura:** Docker & Docker Compose.

## Instalación y Despliegue (Docker)

1. Clonar el repositorio:
   ```bash
   git clone [https://github.com/tu-usuario/jzpass.git](https://github.com/tu-usuario/jzpass.git)
   cd jzpass
