FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY ../sewasetu_common /app/sewasetu_common

ENV PYTHONPATH=/app
