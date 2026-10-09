FROM python:3.11-slim

WORKDIR /app

# Metadatos del contenedor
LABEL maintainer="Korsh-Dev"
LABEL description="KorshQuake - Realtime Seismic Monitoring Hub"

# Copiar código del proyecto
COPY server.py test_server.py requirements.txt KorshQuake.apk ./
COPY web ./web

# Exponer el puerto del servidor HTTP
EXPOSE 8080

# Ejecutar el servidor multihilo de KorshQuake
CMD ["python", "server.py", "8080"]
