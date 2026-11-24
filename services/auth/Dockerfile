# Se construye desde la raíz del repositorio (ahí están pyproject.toml y uv.lock del workspace):
#   docker build -f services/auth/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras uv.lock no cambie.
COPY pyproject.toml uv.lock ./
COPY services/auth/pyproject.toml services/auth/
RUN uv sync --locked --no-dev --package finance-balance-auth --no-install-workspace

COPY services/auth/src services/auth/src
RUN uv sync --locked --no-dev --package finance-balance-auth --no-editable

COPY services/auth/alembic.ini services/auth/
COPY services/auth/migrations services/auth/migrations

USER appuser

EXPOSE 8000

# --root-path /auth: el gateway publica este servicio bajo /auth (Swagger arma sus URLs con eso).
CMD ["sh", "-c", "alembic -c services/auth/alembic.ini upgrade head && uvicorn auth_service.main:create_app --factory --host 0.0.0.0 --port 8000 --root-path /auth"]
