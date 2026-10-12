# Build from repo root: docker build -f services/portal/Dockerfile .
FROM node:22-alpine AS web-build
WORKDIR /app
COPY services/portal/web/package*.json ./
RUN npm ci
COPY services/portal/web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
COPY services/portal/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/portal/app.py /app/app.py
COPY --from=web-build /app/dist /app/web/dist
RUN useradd -u 10001 appuser
USER 10001
EXPOSE 8501
CMD ["uvicorn", "app:app", "--host=0.0.0.0", "--port=8501"]
