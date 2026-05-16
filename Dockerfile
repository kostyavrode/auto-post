FROM python:3.11-slim

WORKDIR /app

# No apt-get: many servers block deb.debian.org:80 during docker build.
# lxml and Pillow install from manylinux wheels on amd64/arm64.
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=lxml,Pillow -r requirements.txt

COPY . .

RUN mkdir -p data/images examples config

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
ENV EXAMPLES_DIR=/app/examples
ENV CONFIG_DIR=/app/config

CMD ["python", "-m", "src.main"]
