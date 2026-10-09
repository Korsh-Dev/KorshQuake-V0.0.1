FROM python:3.11-slim

WORKDIR /app

LABEL maintainer="Korsh-Dev"
LABEL description="KorshQuake - Realtime Seismic Monitoring Hub"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN if [ -s requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

COPY server.py test_server.py KorshQuake.apk ./
COPY web ./web

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health').read()" || exit 1

CMD ["python", "server.py", "8080"]
