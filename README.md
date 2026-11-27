# Finance Balance Backend

Backend de Finance Balance, una aplicación personal de finanzas para Android. Este servicio recibe y guarda la información que la app sincroniza, administra las cuentas de usuario y mantiene las sesiones de cada dispositivo.

## Qué hace

- Registro con nombre, apellidos, correo y contraseña; inicio de sesión con correo y contraseña.
- Sesiones por dispositivo: puedes tener la cuenta abierta en varios teléfonos y cerrar la sesión de cualquiera de ellos a distancia.
- Sincronización de la información que la app guarda sin conexión.
- Borrado lógico: lo que se borra se oculta de inmediato, pero nada se elimina de la base. El servidor conserva todo, cuentas incluidas.

## Estado

En desarrollo. Hoy están disponibles el registro de cuentas, el inicio y cierre de sesión por dispositivo, la renovación de sesión, el cambio de contraseña, el perfil, la lista de dispositivos y la eliminación de la cuenta. El servicio de finanzas ya existe y solo acepta peticiones con una sesión activa. Ya tiene las tablas y reglas de tarjetas, movimientos (cargos, compras a meses y pagos) e ingreso mensual, y la sincronización completa: la app sube sus cambios (también los hechos sin red) y descarga lo que cambió, por páginas.

## Arquitectura

Todas las peticiones entran por un **gateway** ([Caddy](https://caddyserver.com/)) que las reparte entre los servicios según el inicio de la ruta:

| Ruta en el gateway | Servicio | Carpeta |
|--------------------|----------|---------|
| `/auth/*` | Autenticación: cuentas, sesiones y dispositivos | `services/auth/` |
| `/finance/*` | Finanzas y sincronización (en construcción). Solo con sesión activa: antes de cada petición el gateway la verifica con autenticación (`forward_auth`) y le entrega el usuario en `X-User-Id`. | `services/finance/` |

```
backend/
├── gateway/Caddyfile        # reglas del gateway
├── libs/
│   └── common/              # código común (paquete service_common): salud, cabeceras y app base
├── services/
│   ├── auth/                # servicio de autenticación (paquete auth_service)
│   │   ├── src/auth_service/
│   │   ├── migrations/      # migraciones de Alembic del servicio
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml   # dependencias del servicio
│   └── finance/             # servicio de finanzas (paquete finance_service)
│       ├── src/finance_service/
│       ├── migrations/      # migraciones de Alembic (esquema finance)
│       ├── contract/        # casos de validación y ejemplos de sincronización para la app
│       └── tests/
├── tools/crap.py            # CRAP por función (complejidad y cobertura)
├── docker-compose.yml       # db, auth, finance y gateway
├── pyproject.toml           # workspace de uv y herramientas de desarrollo
└── uv.lock                  # versiones exactas de todo el workspace
```

Solo el gateway publica un puerto. Los servicios se comunican por la red interna de Docker Compose.

## Requisitos

- [Git](https://git-scm.com/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (o Docker Engine en Linux)
- Python 3.12 o superior y [uv](https://docs.astral.sh/uv/), solo si vas a correr las pruebas fuera de Docker

## Cómo correrlo

1. Clona el repositorio y entra a la carpeta `backend`.
2. Copia la plantilla de variables de entorno y completa los valores:

   ```bash
   cp .env.example .env
   ```

3. Levanta la base de datos, el servicio de autenticación y el gateway:

   ```bash
   docker compose up --build
   ```

4. Verifica que el gateway y el servicio responden:

   ```bash
   curl http://localhost:8000/health        # gateway
   curl http://localhost:8000/auth/health   # servicio de autenticación
   ```

El archivo `.env` contiene secretos locales y nunca se sube al repositorio.

## Documentación de la API

La API se documenta con Swagger (OpenAPI), que FastAPI genera automáticamente:

- Interfaz interactiva: http://localhost:8000/auth/docs
- Especificación OpenAPI en JSON: http://localhost:8000/auth/openapi.json

Puedes importar la especificación en Insomnia para hacer pruebas.

Swagger solo está disponible en desarrollo. En producción se desactiva.

## Endpoints

| Método | Ruta (en el gateway) | Descripción |
|--------|----------------------|-------------|
| GET    | `/health`            | Indica si el gateway está activo. |
| GET    | `/auth/health`       | Indica si el servicio de autenticación está activo. |
| GET    | `/finance/health`    | Indica si el servicio de finanzas está activo. Requiere sesión activa (`401` sin ella). |
| POST   | `/finance/sync`      | Aplica los cambios que sube la app (`sent_at` y `changes`, opcionales) y descarga lo que cambió en la cuenta después de `cursor` (`{"cursor": 0}` la primera vez), en páginas de 500, con el `cursor` nuevo y `has_more`. Requiere sesión activa. `422` con ruta, campo y regla si algo no es válido; entonces no se guarda nada. |
| POST   | `/auth/register`     | Crea una cuenta con `first_name`, `last_name` (todos los apellidos en un campo; 1 a 100 caracteres cada uno, sin caracteres de control), correo y contraseña (12 a 128 caracteres). `201`; `409` si el correo ya existe; `422` si falta un dato o no es válido. |
| POST   | `/auth/sessions`     | Inicia sesión en un dispositivo (`device_id`, `device_name`). Devuelve el token de acceso (15 min) y el refresh token (90 días). `401` si las credenciales no son válidas; `429` (con `Retry-After`) tras 5 fallos del mismo correo en 15 minutos. |
| POST   | `/auth/sessions/refresh` | Entrega tokens nuevos a cambio del refresh token, que deja de servir. Reutilizar uno viejo cierra la sesión. `401` si no es válido. |
| DELETE | `/auth/sessions/current` | Cierra la sesión de este dispositivo. Requiere `Authorization: Bearer <token de acceso>`. `204`. |
| PUT    | `/auth/password` | Cambia la contraseña (pide la actual) y cierra los demás dispositivos. `204`; `403` si la actual no es correcta. |
| GET    | `/auth/me` | Perfil de la cuenta: id, correo, nombre, apellidos y fecha de alta. |
| PATCH  | `/auth/me` | Cambia el nombre, los apellidos o los dos; lo que no se envía queda igual. No se pueden borrar (`null` da `422`). Solo acepta `first_name` y `last_name`. |
| DELETE | `/auth/me` | Elimina la cuenta. Pide la contraseña en el cuerpo (`{"password": "..."}`). Cierra la sesión de todos los dispositivos y el correo queda libre para registrarse otra vez. `204`; `403` si la contraseña no es correcta. |
| GET    | `/auth/sessions` | Dispositivos con sesión activa, del uso más reciente al más antiguo; `current` marca este dispositivo. |
| DELETE | `/auth/sessions/{id}` | Cierra la sesión de otro dispositivo (o de este). `204`, también si ya estaba cerrada; `404` si no existe o es de otra cuenta. |

Los endpoints de `/auth/me`, `/auth/sessions` (GET y DELETE) y `/auth/password` requieren `Authorization: Bearer <token de acceso>`.

### Eliminar la cuenta

Eliminar la cuenta es solo un borrado lógico: nada se borra de la base. La fila queda marcada con `deleted_at`, deja de poder iniciar sesión (responde igual que una contraseña incorrecta) y todas sus sesiones se revocan al instante. El correo solo es único entre las cuentas no eliminadas, así que se puede volver a registrar enseguida.

El detalle completo de cada endpoint está en Swagger y en el contrato `services/auth/openapi.json`.

### Datos de finanzas y casos compartidos

Finanzas guarda sus tablas en el esquema `finance` de la misma base (`cards`, `movements` y `monthly_income`), con su propia tabla de versiones de Alembic. Reglas principales:

- El dinero va en centavos enteros (`BIGINT`), nunca en float. La tasa mensual de una compra a meses viaja como texto (`"0.03"`) y se guarda en `NUMERIC(7,6)`.
- La fecha de un movimiento viaja en ISO 8601 con offset (`2026-11-26T03:00:00+01:00`) y se guarda como instante más offset. Sin offset o a más de 24 horas en el futuro se rechaza.
- Cada registro lleva `version`, `idempotency_key` y `deleted_at` para la sincronización; nada se borra.

`services/finance/contract/validation-cases.json` tiene los casos que el servidor acepta y rechaza (con el campo y la regla de cada rechazo). La app los copia para sus pruebas; las de Python los recorren completos.

### Sincronización: descarga por páginas

Cada escritura en finanzas toma el siguiente número de una secuencia (`change_seq`). La app manda el último número que recibió (`cursor`) y el servidor contesta con lo que cambió después:

- Cada página trae hasta 500 registros en orden, el `cursor` nuevo y `has_more`.
- Si un movimiento de la página apunta a una tarjeta que todavía no se envió, la tarjeta viaja en esa misma página.
- Cada sincronización toma un candado por cuenta: dos teléfonos de la misma cuenta van uno detrás del otro y nunca llega una página a medias.
- Cada registro trae `id`, `key` (la clave que generó la app), `version` y `data` con la misma forma que la app sube.

### Sincronización: subida de cambios

La app manda en la misma llamada lo que cambió sin red: `sent_at` (la hora de su reloj al enviar) y `changes` con `cards`, `movements` y `monthly_income`.

- Un registro nuevo lleva `key` (la clave que genera la app); una edición, `id` y `base_version` (la versión sobre la que se editó). Siempre: `change_id`, `updated_at` con offset y `data`. Un movimiento apunta a su tarjeta con `{"id"}` o con `{"key"}`, también de una tarjeta de la misma subida.
- Si la versión coincide, el cambio se aplica. Si no (dos teléfonos editaron lo mismo), gana la hora de edición más reciente, corregida con la diferencia entre el reloj del teléfono y el del servidor; si empatan, se queda lo que ya estaba. Una hora posterior al envío cuenta como hecha al enviar.
- Reintentar es seguro: la clave de cada registro nuevo y el `change_id` de cada edición evitan duplicar o aplicar dos veces.
- Crear un ingreso cuando ya hay uno vigente se resuelve como un choque con él.
- `results` dice, en el orden de la petición, si cada cambio quedó `applied` o `lost` y cómo quedó el registro. Si algo no vale (`not_found`, `duplicate`, `too_many` o una regla de los datos), responde `422` y no se guarda nada.

`services/finance/contract/sync-examples.json` tiene peticiones y respuestas reales de descarga y de subida; las pruebas de Python las comparan con lo que contesta el servidor.

## Pruebas

Las versiones exactas de todas las librerías están en `uv.lock`. Instálalas y corre las revisiones:

```bash
uv sync --locked --all-packages
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Las pruebas de integración usan PostgreSQL real y se omiten si no defines `TEST_DATABASE_URL` (en CI corren siempre, con cobertura mínima del 90 %). Esa base se vacía en cada prueba: no uses la de desarrollo.

```bash
TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost:5432/pruebas uv run pytest --cov
```

El CI también mide la calidad con herramientas gratuitas:

- **Duplicación** (pylint `duplicate-code`): ningún bloque de 6 líneas repetido en el código fuente.
- **CRAP** (`tools/crap.py`, con radon y la cobertura): ninguna función llega a 10.
- **Mutación** (mutmut, un job por paquete): ningún mutante sobrevive. mutmut no corre en Windows.

```bash
uv run pytest --cov --cov-report=json && uv run python tools/crap.py coverage.json
uv run pylint --disable=all --enable=duplicate-code --min-similarity-lines=6 libs/common/src services/auth/src services/finance/src tools/crap.py
```

Si cambias la API a propósito, regenera el contrato y revísalo en el PR:

```bash
UPDATE_OPENAPI=1 uv run pytest services/auth/tests/contract
```

Para cambiar una dependencia de un servicio, edita su `services/<servicio>/pyproject.toml` y corre `uv lock` en la raíz. Sube `uv.lock` en el mismo commit.

## Seguridad

CI corre en cada push, en cada PR y cada lunes:

- **Bandit:** busca patrones de código inseguro en `services/`.
- **pip-audit:** compara las versiones de `uv.lock` con la base pública de vulnerabilidades conocidas.
- **gitleaks:** busca secretos en todo el historial de git.

Dependabot abre cada semana PRs que actualizan `uv.lock`, las acciones de CI y las imágenes de Docker (la del servicio y las de `docker-compose.yml`).

La API responde con cabeceras de seguridad (`nosniff`, `DENY`, `no-referrer`, `no-store`). En producción agrega además HSTS y Content-Security-Policy. No habilita CORS: la app Android no lo necesita, y así ningún sitio web puede llamar a la API desde un navegador.

## Stack

**Backend:** Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · PostgreSQL · Docker Compose · Caddy · uv · pytest · ruff · Bandit · pip-audit · gitleaks

**Cliente Android:** Kotlin · Jetpack Compose · Material 3 · Hilt · Room · DataStore · Coroutines y Flow · BiometricPrompt
