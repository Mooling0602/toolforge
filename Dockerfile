FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TOOLFORGE_CONFIG=/app/config.yaml \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY vendor/xyml-toolcall /app/vendor/xyml-toolcall
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY config.example.yaml /app/config.example.yaml

RUN pip install -e /app/vendor/xyml-toolcall \
    && pip install -e /app \
    && cp /app/config.example.yaml /app/config.yaml

EXPOSE 8080

# Override config by mounting ./config.yaml -> /app/config.yaml
CMD ["uvicorn", "toolforge.app:app", "--host", "0.0.0.0", "--port", "8080"]
