# Relevamiento de Equipos

Servidor FastAPI + PostgreSQL para inventariar el hardware de las PCs de los juzgados sin usar pendrives. El técnico abre la página del servidor en la PC a relevar, copia un comando, lo pega en CMD o PowerShell, y el script recoge el hardware, pide los datos de ubicación y los guarda en la base.

## Cómo funciona

1. `GET /` muestra el comando a pegar en la PC:
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; iex (New-Object Net.WebClient).DownloadString('http://SERVIDOR:8000/script')"
   ```
2. `GET /script` entrega el script PowerShell en memoria (no se guarda nada en disco). El script:
   - detecta marca, modelo, service tag, BIOS, SO, CPU, RAM, disco, red, TPM y Secure Boot;
   - pide por teclado juzgado, edificio, piso, nombre, rol, código de activo y datos de la impresora (opcional);
   - envía todo como JSON a `POST /api/relevamiento`.
3. El servidor hace un *upsert* por `service_tag`: si la PC ya existía, se actualiza.
4. `GET /visor` lista los equipos registrados (se refresca cada 10 s) y `GET /exportar.csv` descarga todo en CSV (con BOM, abre bien en Excel / Power BI).

### Requisitos en la PC relevada

- PowerShell 3.0 o superior (Windows 7 necesita WMF 5.1).
- Ejecutar **como Administrador** para obtener TPM, Secure Boot, SMART y desgaste del disco. Sin admin, esos campos quedan vacíos.
- Si el service tag es genérico o vacío ("To be filled by O.E.M.", etc.), se usa `GEN-<MAC>`.

## Endpoints

| Método | Ruta                 | Descripción                                   |
|--------|----------------------|-----------------------------------------------|
| GET    | `/`                  | Página con el comando a copiar                |
| GET    | `/script`            | Script PowerShell (con la URL del servidor)   |
| POST   | `/api/relevamiento`  | Recibe el JSON e inserta/actualiza el equipo  |
| GET    | `/visor`             | Tabla HTML de equipos registrados             |
| GET    | `/exportar.csv`      | Exportación completa en CSV                   |

## Base de datos

- `schema.sql`: esquema idempotente (tabla `equipos` y vista `v_obsolescencia`). El servidor lo ejecuta al arrancar, con hasta 10 reintentos si la BD aún no está lista.
- `estructura.sql`: dump de referencia generado con `pg_dump`. No se usa en ejecución.

La vista `v_obsolescencia` calcula un puntaje de 0 a 100 por equipo según la antigüedad del BIOS, disco HDD, RAM < 8 GB, TPM distinto de 2.0 y estado del disco (salud, SMART, desgaste ≥ 80 %):

```sql
SELECT * FROM v_obsolescencia ORDER BY score_obsolescencia DESC;
```

## Configuración

Conexión a Postgres por variables de entorno:

| Variable       | Por defecto        | Notas                                         |
|----------------|--------------------|-----------------------------------------------|
| `DATABASE_URL` | —                  | Si está definida, tiene prioridad (Render)    |
| `DB_HOST`      | `127.0.0.1`        |                                               |
| `DB_PORT`      | `5432`             |                                               |
| `DB_NAME`      | `relevamiento_db`  |                                               |
| `DB_USER`      | `postgres`         | En docker compose: `relevamiento`             |
| `DB_PASSWORD`  | vacío              | Obligatoria en docker compose                 |
| `HOST`         | `127.0.0.1`        | Solo al correr con `python servidor2.py`      |
| `PORT`         | `8000`             |                                               |

## Ejecución local

Requiere Python 3.12 y un PostgreSQL con la base creada (`relevamiento_db`).

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:DB_PASSWORD = "tu_clave"
$env:HOST = "0.0.0.0"   # para que otras PCs de la red puedan acceder
python servidor2.py
```

Abrir `http://<IP-del-servidor>:8000/` desde la PC a relevar. Si el firewall de Windows bloquea el puerto, abrir el 8000.

## Docker

`docker-compose.yml` levanta la app y Postgres 16 (datos en el volumen `pgdata`). Crear un `.env` junto al compose:

```
DB_PASSWORD=una_clave_segura
APP_PORT=8000
```

```bash
docker compose up -d --build
```

## Despliegue

### GitLab CI (servidor propio)

`.gitlab-ci.yml` tiene dos etapas:

- **test**: instala dependencias y verifica que `servidor2.py` compile e importe.
- **deploy** (solo en la rama por defecto): copia por SSH los archivos necesarios a `DEPLOY_PATH`, genera el `.env` y ejecuta `docker compose up -d --build`.

Variables a definir en *Settings → CI/CD → Variables*:

| Variable          | Descripción                                            |
|-------------------|--------------------------------------------------------|
| `SSH_PRIVATE_KEY` | Clave privada con acceso al servidor (File o Variable) |
| `DEPLOY_HOST`     | IP o nombre del servidor destino                       |
| `DEPLOY_USER`     | Usuario SSH con permiso para usar Docker               |
| `DEPLOY_PATH`     | Opcional, por defecto `/opt/relevamiento`              |
| `DB_PASSWORD`     | Contraseña de Postgres (Masked, Protected)             |
| `APP_PORT`        | Opcional, por defecto `8000`                           |

El servidor destino necesita Docker con el plugin `docker compose`.

### Render

`render.yaml` es un Blueprint que crea una base Postgres gratuita y el servicio web, conectados por `DATABASE_URL`. En Render: *New → Blueprint* y elegir este repositorio.

Detrás de un proxy HTTPS (Render, nginx) uvicorn corre con `--proxy-headers` para que el comando mostrado en `/` use `https://`. El script fuerza TLS 1.2 porque PowerShell 5.1 en equipos viejos no lo usa por defecto.

## Archivos

```
servidor2.py        App FastAPI: página, script PowerShell, API, visor y CSV
schema.sql          Esquema que se aplica al arrancar
estructura.sql      Dump de referencia de la BD
requirements.txt    fastapi, uvicorn, psycopg2-binary, pydantic
Dockerfile          Imagen python:3.12-slim
docker-compose.yml  App + Postgres para servidor propio
.gitlab-ci.yml      Pipeline test + deploy por SSH
render.yaml         Blueprint para Render
```
