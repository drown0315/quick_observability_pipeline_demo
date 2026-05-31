FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

COPY observability_gateway ./observability_gateway

EXPOSE 8001

CMD ["uv", "run", "--no-sync", "uvicorn", "observability_gateway.main:app", "--host", "0.0.0.0", "--port", "8001"]
