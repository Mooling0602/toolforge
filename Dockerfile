FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TOOLFORGE_CONFIG=/app/config.yaml

COPY vendor/xyml-toolcall /app/vendor/xyml-toolcall
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY config.example.yaml /app/config.example.yaml

RUN pip install --no-cache-dir -e /app/vendor/xyml-toolcall -e /app

EXPOSE 8080

CMD ["uvicorn", "toolforge.app:app", "--host", "0.0.0.0", "--port", "8080"]
