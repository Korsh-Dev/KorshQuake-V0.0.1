#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/korshquake"
cd "$REPO_DIR"

# Obtener ultimos cambios sin modificar arbol de trabajo
git fetch origin main --quiet

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [AUTO-UPDATE] Nueva version detectada en GitHub: $REMOTE_HASH (actual: $LOCAL_HASH)"
    git reset --hard origin/main
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [AUTO-UPDATE] Reconstruyendo contenedor Docker..."
    docker compose build --pull
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [AUTO-UPDATE] Reiniciando contenedor korshquake-hub..."
    docker compose up -d --remove-orphans
    docker image prune -f
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [AUTO-UPDATE] Actualizacion completada exitosamente a $REMOTE_HASH"
fi
