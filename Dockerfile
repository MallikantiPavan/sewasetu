FROM python:3.11-slim
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
COPY sewasetu_common/ ./sewasetu_common/
COPY seed/ ./seed/
COPY evals/ ./evals/
ENV SECRET_KEY=render-deploy-key-2026
EXPOSE 8000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "2"]
