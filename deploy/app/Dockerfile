# Imagen del backend y de los workers OCR (una imagen para todos los clientes; D-016).
#   docker build -f deploy/app/Dockerfile -t facturas-app:<versión> .
#   docker build -f deploy/app/Dockerfile --build-arg INCLUIR_OCR=0 -t facturas-app:sin-ocr .   # pruebas locales
FROM python:3.13-slim

ARG INCLUIR_OCR=1
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Bibliotecas de sistema que usan PaddleOCR/OpenCV y PyMuPDF.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN if [ "$INCLUIR_OCR" = "1" ]; then \
      pip install -r requirements.txt; \
    else \
      grep -viE '^(paddleocr|paddlepaddle)' requirements.txt > /tmp/requisitos.txt && pip install -r /tmp/requisitos.txt; \
    fi

COPY app ./app
COPY VERSION ./

# Sin privilegios; los archivos del cliente llegan montados en /datos (vista descifrada de gocryptfs).
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin facturas \
 && mkdir -p /datos/uploads \
 && chown -R facturas /datos
USER facturas

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
ENTRYPOINT ["python", "-m", "app.plataforma.arranque"]
CMD ["api"]
