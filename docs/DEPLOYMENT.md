# KorshQuake — Guía de despliegue y operación

> Documento para gente nueva en el proyecto. Última actualización: 2026-10-11 (auditoría de robustez completa).

## Arquitectura

```
                    ┌────────────────────────────────────────────────┐
 USGS / EMSC /      │  Contenedor Docker "korshquake-hub"            │
 IGN / FUNVISIS /   │  ├─ server.py (stdlib puro, sin deps pip)      │
 INPRES / GQ        │  │  ├─ worker: refresco RAM cada 2.8 s         │
 (feeds HTTP)  ───► │  │  ├─ WS nativo RFC6455 ──► EMSC live (sub-s)│
                    │  │  ├─ SSE /api/events/live ──► navegadores   │
 Teléfonos (APK)    │  │  ├─ SQLite WAL en /app/data (volumen)      │
 (mesh triggers) ──►│  │  └─ estáticos web/ + /KorshQuake.apk       │
                    │  └─ escucha 0.0.0.0:8080 (docker: :8088)      │
                    └────────────────────────────────────────────────┘
                          ▲ 127.0.0.1:8088            ▲ 127.0.0.1:8089
                          │                           │
                    nginx quake.korsh.online   korshquake-webhook.service
                    (TLS, headers de seguridad, (listener de GitHub webhook,
                     proxy /api/github-webhook)  dispara auto-update.sh)
```

- **`server.py`** — monolito stdlib-only (~3200 líneas). Sin requirements de producción.
- **`web/`** — frontend vanilla JS (`app.js`), PWA con service worker.
- **`test_server.py`** — suite `unittest` (sube el server real en puerto 8899).
- **`webhook_listener.py`** (+ copia en `deploy/`) — servicio aparte, NO vive en el contenedor.

## Cobertura mundial ("todos los países del mundo")

Desde la revisión de octubre 2026 el feed ya **no** se limita a los 5 países foco:

- `classify_event_country(lat, lon, place, auth)` (en `server.py`) devuelve `(código ISO, nombre en español, bandera emoji)` para cualquier evento del planeta:
  1. Los 5 países foco (PA/VE/ES/AR/HN) conservan la clasificación estricta por cajas de `identify_target_country()`.
  2. El resto se clasifica escaneando el texto `place`/`flynn_region` contra `_COUNTRY_TERMS` (~700 nombres de país, regiones y ciudades sísmicas EN/ES → código ISO), con regex alternativa ordenada por longitud descendente.
  3. Mar abierto / dorsales oceánicas sin nombre → `GLOBAL` / "Internacional" / 🌐.
- **Umbral anti-inundación:** fuera de los 5 países foco solo se publican eventos con `mag >= GLOBAL_MIN_MAG` (4.0). Los países foco se publican con cualquier magnitud. Ajustar la constante si se quiere más/menos densidad.
- **Ingesta:** `fetch_emsc_global()` añade la consulta EMSC sin bbox (`minmag=4.0&limit=100`, lo más nuevo primero). USGS `all_week` ya traía el mundo entero; ahora se conserva todo lo clasificado con M ≥ 4.0.
- **Contadores:** `counts_by_country` arranca con las 5 claves foco en 0 y añade dinámicamente cualquier código que aparezca (JP, ID, CL, …). El frontend muestra el total con la suma de todos los valores.
- **Mapa:** la vista "Todos" (`REGION_VIEWPORTS.all`) es ahora vista de planeta (centro [12, -30], zoom 2). Las pills de los 5 países siguen filtrando por código; "Todos" deja pasar todo.
- **Nodos mesh:** un teléfono registrado fuera de los países foco ya no se fuerza a "VE"; se clasifica (o `GLOBAL`).

## Servidores systemd en la VPS (195.26.244.209, /opt/korshquake)

| Unidad | Qué hace |
|---|---|
| `korshquake-updater.timer` | Cada **60 s**: `git fetch` + `git reset --hard origin/main` + `docker compose build/up`. Es el despliegue real. |
| `korshquake-webhook.service` | Listener en 127.0.0.1:8089; nginx lo expone en `/api/github-webhook`. Atajo on-demand del updater. |
| `korshquake-hub` (docker) | La app. `restart: unless-stopped`, healthcheck `/api/health`. |

⚠️ **Nunca edites `/opt/korshquake` a mano**: el timer hace `git reset --hard` y lo descarta en silencio. Todo cambio entra por `git push` a `main`.

⚠️ Cambios en `webhook_listener.py` requieren `systemctl restart korshquake-webhook` (el updater solo reconstruye el contenedor).

## Desplegar

```bash
git push origin main          # rama main = producción
sleep 100                     # timer 60 s + docker build
ssh root@VPS 'cd /opt/korshquake && git log -1 --oneline && docker ps | grep quake'
curl -s https://quake.korsh.online/api/health
```

**Rollback:** `git revert <sha> && git push` — el timer lo despliega solo. (No hacer `git reset` en la VPS; se pierde en el siguiente ciclo de todos modos.)

## Variables de entorno

| Variable | Dónde | Efecto |
|---|---|---|
| `PORT` | compose → contenedor | Puerto interno del server (default 8080; nginx apunta a 8088 por el mapeo de puertos). |
| `GITHUB_WEBHOOK_SECRET` | `korshquake-webhook.service` (`Environment=`) | Si está puesta, el webhook exige firma `X-Hub-Signature-256` válida (403 si no). Si no está, acepta cualquier POST (comportamiento histórico). El webhook de GitHub debe configurarse con el mismo secret y contenido `application/json`. |
| `ADMIN_TOKEN` | `docker-compose.yml` → `environment:` | Si está puesta, `/admin` y `/api/admin/*` exigen header `X-Admin-Token` o `?token=*** (comparación timing-safe). Si no está, la consola queda abierta (comportamiento histórico). Las rutas `/api/nodes/*` siguen públicas (las usa el APK). |

## Claves VAPID (Web Push)

- Pública: hardcodeada en `server.py` (`VAPID_PUBLIC_KEY`), punto EC no comprimido de 65 bytes en base64url.
- **Privada: `/opt/korshquake/data/vapid_private.pem` en la VPS** (el dir `data/` es volumen persistente y está en `.gitignore`; la clave privada NUNCA se sube a git).
- Regenerar: `openssl ecparam -name prime256v1 -genkey -noout -out vapid_private.pem && openssl ec -in vapid_private.pem -pubout -outform DER | tail -c 65 | basenc --base64url | tr -d '=\n'`
- Nota honesta: el server aún **no envía** notificaciones push (solo registra suscripciones en la tabla `push_subscriptions`); la clave real hace que el `serviceWorker.register().pushManager.subscribe()` del navegador funcione en lugar de fallar con la clave placeholder anterior.

## Tests

```bash
python3 -m unittest test_server -v     # 39 tests; no usa pytest
```

Regla del repo: **cada bug arreglado entra con su test de regresión**. Los tests suben el server real en el puerto 8899 y hacen HTTP de verdad.

## Convenciones de código (lo que aprendimos a golpes)

- **Nunca casteos crudos `float()`/`int()` sobre input de API** → usan `_safe_float`/`_safe_int` (el 90% de los 500 históricos venían de ahí).
- `felt_reports` = total fusionado (USGS `felt` + reportes comunitarios). No pisarlo con el conteo comunitario.
- Todo HTML/XML/CSV generado desde datos de feed se escapa (`html_lib.escape`, `xml_escape`, `_csv_escape`).
- Body de POST limitado a 1 MB (413).
- Commits **siempre** como `EL Pilot PR <138331374+ELPilotPR@users.noreply.github.com>`.

## Backlog conocido

- [ ] Enviar notificaciones push reales (nada envía a `push_subscriptions` todavía; haría falta un emisor VAPID con JWT ES256 — stdlib-only es posible pero trabajoso).
- [ ] Configurar `GITHUB_WEBHOOK_SECRET` end-to-end (requiere admin del repo en GitHub para crear/editar el webhook; ELPilotPR solo tiene push — la API de hooks responde 404 sin admin). El timer de 60 s hace el despliegue igual, así que esto es solo latencia.
- [ ] Activar `ADMIN_TOKEN` en producción (generar token, ponerlo en compose + pasarlo al admin.html).
- [x] ~~Historial de git pesado~~ — **hecho 2026-10-11**: `git filter-repo --path gods-eye-view --invert-paths` + force-push; clon pasó de 110 MB a 19 MB. Ojo: si alguien tiene un clon viejo, necesita `git fetch && git reset --hard origin/main` (historial reescrito). Backup del historial original en poder del mantenedor.
- [x] ~~`web/index.html` dice "3.6 MB" para el APK~~ — corregido a 3.4 MB (2026-10-11).
