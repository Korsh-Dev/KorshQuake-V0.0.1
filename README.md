# KorshQuake v1.1.2 PRO 🌍⚡

**KorshQuake** es un centro de monitoreo, detección y alerta temprana de terremotos en tiempo real enfocado exclusivamente en cuatro territorios:
- 🇵🇦 **Panamá**
- 🇻🇪 **Venezuela**
- 🇪🇸 **España** (Península, Baleares e Islas Canarias)
- 🇦🇷 **Argentina**

El sistema ingiere y triangula en paralelo datos de redes sismológicas oficiales (IGN, FUNVISIS, INPRES, OSOP/RSN, EMSC y USGS) con refresco continuo en memoria RAM cada 2.8 segundos y respuesta de API en menos de 40 ms.

---

## 🚀 Cómo Montar KorshQuake en tu Servidor Web

### Opción 1: Ejecución Directa con Python (Sin dependencias)
KorshQuake utiliza únicamente la biblioteca estándar de Python 3.9+, por lo que no necesitas instalar librerías pesadas:

```bash
# 1. Clonar el repositorio
git clone https://github.com/Korsh-Dev/KorshQuake-V0.0.1.git
cd KorshQuake-V0.0.1

# 2. Ejecutar el servidor (puerto por defecto 8080 o el que elijas)
python3 server.py 8080
```
Abre en tu navegador: `http://TU_IP_O_DOMINIO:8080`

---

### Opción 2: Con Docker / Docker Compose (Recomendado para Producción)
Si tienes Docker instalado en tu servidor:

```bash
docker compose up -d --build
```
El contenedor se levantará automáticamente en segundo plano con reinicio continuo (`restart: always`).

---

### Opción 3: Servicio en Linux con Systemd (Segundo plano continuo)
Crea el archivo de servicio en `/etc/systemd/system/korshquake.service`:

```ini
[Unit]
Description=KorshQuake Realtime Hub
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/KorshQuake-V0.0.1
ExecStart=/usr/bin/python3 server.py 8080
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Luego actívalo:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now korshquake
```

---

### Opción 4: Configuración con Nginx (Puerto 80 / 443 con SSL)
Si quieres que responda en tu dominio directamente por el puerto 80/443 con HTTPS (Let's Encrypt):

```nginx
server {
    listen 80;
    server_name tu-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## 📲 Aplicación Móvil (APK y PWA)
- **Descarga directa de APK:** La aplicación web incluye la descarga directa de `KorshQuake.apk` en `/KorshQuake.apk`.
- **Instalación como WebAPK:** Abre la URL en Chrome/Edge desde cualquier celular Android y toca *"Instalar aplicación"* para añadirla con icono propio en la pantalla de inicio.

---

## 📡 Endpoints de la API
- `GET /api/events/live`: Canal de transmisión continua SSE (*Server-Sent Events*) para alertas sísmicas y detección de Onda P/S en tiempo real.
- `GET /api/predict`    : Motor EEW de predicción de arribo de Onda P ($7.8\text{ km/s}$) y Onda S ($4.1\text{ km/s}$), PGA y MMI hacia centros urbanos.
- `GET /api/quakes`     : GeoJSON en memoria RAM con sismos filtrados de Panamá, Venezuela, España y Argentina.
- `GET /api/status`     : Telemetría del servidor, modo de streaming y latencias.
- `GET /api/servers`    : Estado y latencia de las redes sismológicas conectadas.
- `GET /api/logs`       : Logs en tiempo real del motor sísmico.
- `GET /KorshQuake.apk` : Descarga del archivo APK instalable para Android.

---

## 🧪 Pruebas Automatizadas
Para verificar el funcionamiento y filtrado estricto:
```bash
python3 test_server.py
```
Todos los tests deben pasar con código de salida `0`.


## Despliegue en Produccion (quake.korsh.online)

El servicio esta contenerizado con Docker Compose y conectado a Nginx con proxy inverso SSL:

- **Dominio Publico:** `https://quake.korsh.online`
- **Globo 3D:** `https://quake.korsh.online/gods-eye`
- **Healthcheck:** `https://quake.korsh.online/api/health`
- **SSE Stream en Vivo:** `https://quake.korsh.online/api/events/live`

### Componentes de Despliegue (`deploy/`)

- `deploy/auto-update.sh`: Script de actualizacion automatica con Git pull, Docker build y reinicio sin caidas.
- `deploy/webhook_listener.py`: Servidor ligero en puerto 8089 para recibir webhooks de GitHub en `/api/github-webhook`.
- `deploy/korshquake-updater.timer`: Timer systemd que consulta GitHub cada 60 segundos para despliegue automatico continuo.
- `deploy/korshquake-updater.service`: Servicio oneshot disparado por el timer.
- `deploy/korshquake-webhook.service`: Servicio systemd persistente del listener de webhook.
- `deploy/nginx-quake.korsh.online.conf`: Configuracion de Nginx con SSL y streaming HTTP/1.1 sin buffer (`proxy_buffering off`).
