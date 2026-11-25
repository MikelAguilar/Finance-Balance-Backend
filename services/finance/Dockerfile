# Se construye desde la raíz del repositorio (ahí están pyproject.toml y uv.lock del workspace):
#   docker build -f services/finance/Dockerfile .
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
# uv --locked necesita ver el workspace completo: los pyproject.toml de todos los miembros, aunque
# esta imagen instale solo uno (--package).
COPY libs/common/pyproject.toml libs/common/
COPY services/auth/pyproject.toml services/auth/
COPY services/finance/pyproject.toml services/finance/
RUN uv sync --locked --no-dev --package finance-balance-finance --no-install-workspace

COPY libs/common/src libs/common/src
COPY services/finance/src services/finance/src
RUN uv sync --locked --no-dev --package finance-balance-finance --no-editable

USER appuser

EXPOSE 8000

# --root-path /finance: el gateway publica este servicio bajo /finance (Swagger arma sus URLs con eso).
CMD ["uvicorn", "finance_service.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--root-path", "/finance"]
