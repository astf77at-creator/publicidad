# Memoria Central YOOHOO

Bitácora unificada de sesiones de trabajo con Claude. Captura avances
**incrementales cada hora** (las sesiones duran días, no depende del cierre) y
se expone como **servidor MCP remoto** además de una API REST.

- **API REST** (uvicorn en `127.0.0.1:8742`, nunca expuesto directo)
- **MCP** Streamable HTTP montado en `/mcp` (SDK oficial `mcp` / FastMCP)
- **Auth**: Bearer estático (`MEMORIA_TOKEN`) **y** OAuth 2.1 con PKCE (para el
  conector web de claude.ai, que no admite tokens estáticos)
- **SQLite** WAL + **FTS5** para búsqueda de texto
- **Hooks** `Stop` (avance con throttle de 60 min) y `SessionEnd` (cierre)

> ⚠️ Este repositorio contiene el **código y los archivos de despliegue**. La
> instalación se ejecuta **en el VPS** (no en el sandbox de Claude Code web).

## Estructura

```
memoria_central/
├── app/
│   ├── main.py        # FastAPI + montaje MCP + middleware de auth
│   ├── db.py          # SQLite + FTS5 (triggers)
│   ├── mcp_server.py  # FastMCP con 5 tools
│   └── oauth.py       # OAuth 2.1 mínimo (RFC 9728/8414/7591 + PKCE)
├── hooks/
│   ├── hook_memoria.sh  # hook Stop/SessionEnd (curl, falla en silencio)
│   ├── procesar.py      # parseo del transcript + throttle + checkpoint
│   └── state/           # checkpoints por session_id
├── deploy/
│   ├── install.sh                 # instalador idempotente (root)
│   ├── memoria-central.service    # systemd
│   ├── Caddyfile                  # reverse proxy (recomendado)
│   ├── nginx-memoria.conf         # alternativa si nginx ya usa 80/443
│   ├── backup_memoria.sh          # backup + rotación 30 días
│   ├── memoria-backup.cron        # cron diario
│   └── claude-settings-hooks.json # bloque para ~/.claude/settings.json
├── data/              # memoria.db (no versionado)
├── backups/           # copias (no versionado)
├── requirements.txt
└── .env.example
```

## Instalación en el VPS

```bash
# 1) Copiar el directorio memoria_central/ al VPS (p. ej. clonando el repo)
sudo bash memoria_central/deploy/install.sh
```

El instalador (mismo patrón que `/opt/descargador_imagenes`):
verifica Python 3.11+, crea el usuario de servicio `memoria`, copia a
`/opt/memoria_central`, crea el venv e instala dependencias, genera el
`MEMORIA_TOKEN` con `openssl rand -hex 32` en `/opt/memoria_central/.env`
(**chmod 600, nunca se imprime**), instala y habilita el servicio systemd y el
cron de backup.

Comprobación:
```bash
curl -s http://127.0.0.1:8742/health         # {"ok":true,"mcp":true}
systemctl status memoria-central.service
sudo cat /opt/memoria_central/.env           # aquí está MEMORIA_TOKEN
```

## Exposición HTTPS (`memoria.yoohoo.mx`)

1. **Crear el registro A** de `memoria.yoohoo.mx` → IP del VPS (lo haces tú).
2. **Caddy** (recomendado, certificado automático):
   ```bash
   sudo apt install -y caddy
   sudo cp /opt/memoria_central/deploy/Caddyfile /etc/caddy/Caddyfile
   sudo systemctl reload caddy
   ```
   Si nginx ya ocupa 80/443, usa `deploy/nginx-memoria.conf` + `certbot --nginx`.
3. Pon la URL pública en el `.env` y reinicia:
   ```bash
   # MEMORIA_PUBLIC_URL=https://memoria.yoohoo.mx   (ya viene así por defecto)
   sudo systemctl restart memoria-central.service
   ```

## API REST

Todas las rutas (salvo `/health` y las de OAuth) requieren
`Authorization: Bearer $MEMORIA_TOKEN`.

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/sesiones` | inserta, devuelve `{"id":N}` |
| GET | `/api/sesiones?proyecto=&desde=&hasta=&q=&limit=20&session_id=` | `q` usa FTS5 |
| GET | `/api/resumen-semanal` | últimos 7 días por proyecto (conteo + pendientes) |
| GET | `/api/pendientes?proyecto=` | pendientes abiertos |
| GET | `/api/avance/{session_id}` | todos los registros de una sesión, cronológico |

## Hooks de Claude Code (avance incremental)

Pega el bloque `hooks` de `deploy/claude-settings-hooks.json` en tu
`~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "/opt/memoria_central/hooks/hook_memoria.sh", "timeout": 15 } ] }
    ],
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "/opt/memoria_central/hooks/hook_memoria.sh", "timeout": 15 } ] }
    ]
  }
}
```

Comportamiento:
- **Stop**: en cada respuesta terminada, si han pasado
  `MEMORIA_INTERVALO_MIN` (default 60) desde el último envío de esa sesión, lee
  **solo el tramo nuevo** del transcript (desde el offset guardado), arma un
  resumen y hace POST con `tipo="avance"`. Si no, sale en silencio.
- **SessionEnd**: envía el último tramo pendiente con `tipo="cierre"` (sin
  throttle). Si la sesión muere sin SessionEnd, los avances horarios ya están.
- El hook **siempre** sale `0` (curl `--max-time 10`); nunca bloquea a Claude.
- `proyecto` se infiere del `cwd`: `yoohoo`→yoohoo, `locales`/`lyb`→lyb,
  `isabela`→isabela, `asia`→asia_market, resto→otro.

## Conectar en claude.ai (web)

La web de claude.ai **solo soporta OAuth 2.1** para conectores remotos (no
permite pegar un token ni cabeceras). Este servidor implementa ese OAuth:

1. En claude.ai → **Settings → Connectors → Add custom connector**.
2. **URL del servidor MCP**: `https://memoria.yoohoo.mx/mcp`
3. Deja vacíos Client ID/Secret (el servidor hace **registro dinámico**).
4. Al pulsar *Connect*, claude.ai abrirá la pantalla de autorización del
   servidor: ahí **pegas tu `MEMORIA_TOKEN`** (el de `/opt/memoria_central/.env`).
   Eso completa el login OAuth y emite el token de acceso.

### Conectar en Claude Code CLI / Claude Desktop (Bearer directo)

```bash
claude mcp add --transport http memoria https://memoria.yoohoo.mx/mcp \
  --header "Authorization: Bearer $MEMORIA_TOKEN"
```

### Probar el MCP con el Inspector

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP | URL: https://memoria.yoohoo.mx/mcp
# Authentication: Bearer Token -> MEMORIA_TOKEN
```

## Configuración (`.env`)

| Variable | Default | Descripción |
|---|---|---|
| `MEMORIA_TOKEN` | — | token compartido (REST + MCP). `openssl rand -hex 32` |
| `MEMORIA_DB_PATH` | `data/memoria.db` | ruta de la BD |
| `MEMORIA_PORT` | `8742` | puerto de uvicorn (loopback) |
| `MEMORIA_INTERVALO_MIN` | `60` | throttle del hook en minutos |
| `MEMORIA_API_URL` | `http://127.0.0.1:8742` | URL que usa el hook para POST |
| `MEMORIA_PUBLIC_URL` | `https://memoria.yoohoo.mx` | issuer OAuth / metadata |

## Backups

`deploy/backup_memoria.sh` hace `sqlite3 .backup` (consistente con WAL), lo
comprime y rota copias de más de 30 días. Cron diario en
`deploy/memoria-backup.cron` (03:30 UTC).
