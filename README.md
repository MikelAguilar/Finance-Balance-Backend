# Finance Balance Backend

Backend de Finance Balance, una aplicación personal de finanzas para Android. Este servicio recibe y guarda la información que la app sincroniza, administra las cuentas de usuario y mantiene las sesiones de cada dispositivo.

## Qué hace

- Registro con nombre, apellidos, correo y contraseña; inicio de sesión con correo y contraseña.
- Sesiones por dispositivo: puedes tener la cuenta abierta en varios teléfonos y cerrar la sesión de cualquiera de ellos a distancia.
- Sincronización de la información que la app guarda sin conexión.
- Borrado lógico: lo que se borra se oculta de inmediato y el servidor lo conserva 30 días antes de eliminarlo de forma definitiva. Las cuentas eliminadas son la excepción: se conservan siempre.

## Estado

En desarrollo. Hoy están disponibles el registro de cuentas, el inicio y cierre de sesión por dispositivo, la renovación de sesión, el cambio de contraseña, el perfil, la lista de dispositivos y la eliminación de la cuenta. El resto se agrega por fases.

## Arquitectura

Todas las peticiones entran por un **gateway** ([Caddy](https://caddyserver.com/)) que las reparte entre los servicios según el inicio de la ruta:

| Ruta en el gateway | Servicio | Carpeta |
|--------------------|----------|---------|
| `/auth/*` | Autenticación: cuentas, sesiones y dispositivos | `services/auth/` |
| `/finance/*` | Finanzas y sincronización (llega en una fase próxima) | — |

```
backend/
├── gateway/Caddyfile        # reglas del gateway
├── services/
│   └── auth/                # servicio de autenticación (paquete auth_service)
│       ├── src/auth_service/
│       ├── migrations/      # migraciones de Alembic del servicio
│       ├── tests/
│       ├── Dockerfile
│       └── pyproject.toml   # dependencias del servicio
├── docker-compose.yml       # db, auth y gateway
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
