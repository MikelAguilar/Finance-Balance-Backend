# Finance Balance Backend

Backend de Finance Balance, una aplicación personal de finanzas para Android. Este servicio recibe y guarda la información que la app sincroniza, administra las cuentas de usuario y mantiene las sesiones de cada dispositivo.

## Qué hace

- Registro e inicio de sesión con correo y contraseña.
- Sesiones por dispositivo: puedes tener la cuenta abierta en varios teléfonos y cerrar la sesión de cualquiera de ellos a distancia.
- Sincronización de la información que la app guarda sin conexión.
- Borrado lógico: lo que se borra se oculta de inmediato y el servidor lo conserva 30 días antes de eliminarlo de forma definitiva.

## Estado

En desarrollo. Hoy solo está disponible el endpoint de salud. El resto se agrega por fases.

## Requisitos

- [Git](https://git-scm.com/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (o Docker Engine en Linux)
- Python 3.12 o superior, solo si vas a correr las pruebas fuera de Docker

## Cómo correrlo

1. Clona el repositorio y entra a la carpeta `backend`.
2. Copia la plantilla de variables de entorno y completa los valores:

   ```bash
   cp .env.example .env
   ```

3. Levanta la API y la base de datos:

   ```bash
   docker compose up --build
   ```

4. Verifica que el servicio responde:

   ```bash
   curl http://localhost:8000/health
   ```

El archivo `.env` contiene secretos locales y nunca se sube al repositorio.

## Documentación de la API

La API se documenta con Swagger (OpenAPI), que FastAPI genera automáticamente:

- Interfaz interactiva: http://localhost:8000/docs
- Especificación OpenAPI en JSON: http://localhost:8000/openapi.json

Puedes importar la especificación en Insomnia para hacer pruebas.

Swagger solo está disponible en desarrollo. En producción se desactiva.

## Endpoints

| Método | Ruta      | Descripción                        |
|--------|-----------|------------------------------------|
| GET    | `/health` | Indica si el servicio está activo. |

Los endpoints de cuentas y sesiones se listarán aquí cuando estén implementados. Su detalle completo estará en Swagger.

## Pruebas

```bash
pytest
```

Las pruebas de integración usan PostgreSQL real, así que requieren Docker en ejecución.

## Stack

**Backend:** Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · PostgreSQL · Docker Compose · pytest · ruff

**Cliente Android:** Kotlin · Jetpack Compose · Material 3 · Hilt · Room · DataStore · Coroutines y Flow · BiometricPrompt
