FROM python:3.11-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY . .

RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8000"]
