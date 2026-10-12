# Build from repo root: docker build -f services/docs-assistant/Dockerfile .
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY services/docs-assistant/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/common /app/common
COPY services/docs-assistant/app /app/app
COPY services/docs-assistant/docs /app/docs
RUN useradd -u 10001 appuser && chown -R appuser /app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
