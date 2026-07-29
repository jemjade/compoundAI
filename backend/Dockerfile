# 고정된 uv 의존성으로 Python 3.12 FastAPI Runtime을 Build한다.
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
ARG INSTALL_PADDLEOCR=false
RUN if [ "$INSTALL_PADDLEOCR" = "true" ]; then \
      uv sync --frozen --no-dev --no-install-project --extra paddleocr-cpu; \
    else \
      uv sync --frozen --no-dev --no-install-project; \
    fi
ENV PATH="/app/.venv/bin:$PATH"
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
