FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Environment settings
ENV PYTHONUNBUFFERED=1
ENV PORT=10400
ENV CDP_HOST=host.docker.internal
ENV CDP_PORT=9223
ENV GEMINI_ARCHIVE_DIR=/app/archive

EXPOSE 10400

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10400"]
