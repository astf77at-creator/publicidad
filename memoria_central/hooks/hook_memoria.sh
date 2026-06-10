#!/usr/bin/env bash
# Hook incremental de Memoria Central YOOHOO (eventos Stop y SessionEnd).
#
# Diseño: las sesiones duran días, así que NO dependemos del cierre. En cada
# Stop, con throttle de MEMORIA_INTERVALO_MIN (default 60), se envía el tramo
# NUEVO del transcript con tipo=avance. En SessionEnd se envía el último tramo
# pendiente con tipo=cierre (sin throttle). Si la sesión muere sin SessionEnd,
# los avances horarios ya quedaron guardados.
#
# El hook SIEMPRE falla en silencio y nunca bloquea a Claude Code:
#   - curl con --max-time 10
#   - cualquier error => exit 0
#
# Configurar en ~/.claude/settings.json (ver deploy/claude-settings-hooks.json).

# Nunca abortar el hook por un error: best-effort.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DIR")"
STATE_DIR="$DIR/state"
mkdir -p "$STATE_DIR" 2>/dev/null || true

# Cargar configuración (.env del servicio).
if [ -f "$ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ROOT/.env" 2>/dev/null || true
    set +a
fi
: "${MEMORIA_TOKEN:=}"
: "${MEMORIA_API_URL:=http://127.0.0.1:8742}"
: "${MEMORIA_INTERVALO_MIN:=60}"

# Python del venv si existe, si no el del sistema.
PY="$ROOT/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || exit 0

PAYLOAD="$(cat)"
BODY="$(mktemp 2>/dev/null)" || exit 0
trap 'rm -f "$BODY"' EXIT

RESULT="$(
    PAYLOAD="$PAYLOAD" \
    STATE_DIR="$STATE_DIR" \
    MEMORIA_INTERVALO_MIN="$MEMORIA_INTERVALO_MIN" \
    MEMORIA_BODY_FILE="$BODY" \
    "$PY" "$DIR/procesar.py" 2>/dev/null
)" || exit 0

ACTION="$(printf '%s' "$RESULT" | cut -f1)"
[ "$ACTION" = "SEND" ] || exit 0
OFFSET="$(printf '%s' "$RESULT" | cut -f2)"
STATE_FILE="$(printf '%s' "$RESULT" | cut -f3)"

# POST best-effort; si falla, salimos en silencio (el offset NO se confirma y
# el tramo se reintentará en el próximo envío).
if curl -sf --max-time 10 \
        -X POST "$MEMORIA_API_URL/api/sesiones" \
        -H "authorization: Bearer $MEMORIA_TOKEN" \
        -H "content-type: application/json" \
        --data-binary "@$BODY" >/dev/null 2>&1; then
    # Éxito: confirmar el avance del offset.
    "$PY" "$DIR/procesar.py" --commit "$STATE_FILE" "$OFFSET" >/dev/null 2>&1 || true
fi

exit 0
