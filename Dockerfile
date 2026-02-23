FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY main.py ./


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY main.py ./

RUN mkdir -p /data && chown -R app:app /app /data

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else sys.exit(1)"

CMD ["python", "main.py"]
