FROM python:3.11-slim

WORKDIR /app

# Install system deps for lxml and Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxslt-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directories expected at runtime
RUN mkdir -p data/images examples config

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
ENV EXAMPLES_DIR=/app/examples
ENV CONFIG_DIR=/app/config

CMD ["python", "-m", "src.main"]
