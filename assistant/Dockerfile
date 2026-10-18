FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONPATH=/app
ENV DB_HOST=db
ENV DB_PORT=5432
ENV DB_NAME=sewasetu
ENV DB_USER=sewasetu
ENV DB_PASSWORD=sewasetu123
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8101
