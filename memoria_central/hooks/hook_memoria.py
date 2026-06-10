#!/usr/bin/env python3
"""Hook incremental de Memoria Central — versión 100% Python, multiplataforma.

Pensado para correr Claude Code en cualquier SO (Windows/macOS/Linux) sin
depender de bash/curl. Hace el POST con urllib (timeout 10s) y SIEMPRE sale 0,
para no bloquear nunca a Claude Code.

Eventos: Stop (avance, con throttle de MEMORIA_INTERVALO_MIN) y SessionEnd
(cierre, sin throttle). Lee solo el tramo NUEVO del transcript desde el offset
guardado por session_id.

Configuración (cualquiera de las dos vías):
  1) Variables de entorno: MEMORIA_TOKEN, MEMORIA_API_URL, MEMORIA_INTERVALO_MIN
  2) Un fichero `config.env` junto a este script con líneas CLAVE=valor:
        MEMORIA_TOKEN=xxxxxxxx
        MEMORIA_API_URL=https://memoria.yoohoo.mx
        MEMORIA_INTERVALO_MIN=60

Configurar en settings.json (ver deploy/claude-settings-hooks-python.json):
  "command": "python \"C:\\\\ruta\\\\a\\\\hook_memoria.py\""
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

MAX_LINEAS_RESUMEN = 30
MAX_CHARS_LINEA = 220
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Create"}
HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "state"
TIMEOUT = 10  # segundos del POST


def _cargar_config() -> dict[str, str]:
    """Config desde entorno; completa con config.env junto al script."""
    cfg = {
        "MEMORIA_TOKEN": os.environ.get("MEMORIA_TOKEN", ""),
        "MEMORIA_API_URL": os.environ.get("MEMORIA_API_URL", "https://memoria.yoohoo.mx"),
        "MEMORIA_INTERVALO_MIN": os.environ.get("MEMORIA_INTERVALO_MIN", "60"),
    }
    f = HERE / "config.env"
    if f.exists():
        for linea in f.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = linea.split("=", 1)
            k, v = k.strip(), v.strip()
            # El entorno tiene prioridad; el fichero solo rellena lo que falte.
            if k in cfg and not os.environ.get(k):
                cfg[k] = v
    return cfg


def _proyecto_por_cwd(cwd: str) -> str:
    c = (cwd or "").lower()
    if "yoohoo" in c:
        return "yoohoo"
    if "locales" in c or "lyb" in c:
        return "lyb"
    if "isabela" in c:
        return "isabela"
    if "asia" in c:
        return "asia_market"
    return "otro"


def _texto_de_contenido(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        partes = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
        ]
        return "\n".join(partes).strip()
    return ""


def _archivos_de_contenido(content, acc: set[str]) -> None:
    if not isinstance(content, list):
        return
    for b in content:
        if (
            isinstance(b, dict)
            and b.get("type") == "tool_use"
            and b.get("name") in EDIT_TOOLS
        ):
            fp = (b.get("input") or {}).get("file_path")
            if fp:
                acc.add(fp)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    session_id = payload.get("session_id") or ""
    transcript = payload.get("transcript_path") or ""
    cwd = payload.get("cwd") or ""
    event = payload.get("hook_event_name") or ""

    if not session_id or not transcript or not os.path.exists(transcript):
        return 0

    cfg = _cargar_config()
    token = cfg["MEMORIA_TOKEN"]
    api_url = cfg["MEMORIA_API_URL"].rstrip("/")
    if not token:
        return 0  # sin token no hacemos nada (silencio)

    try:
        intervalo = int(cfg["MEMORIA_INTERVALO_MIN"]) * 60
    except ValueError:
        intervalo = 3600

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{session_id}.json"
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    ultimo = float(state.get("ultimo_envio", 0))
    offset = int(state.get("offset_transcript", 0))

    ahora = time.time()
    es_cierre = event == "SessionEnd"

    # Throttle SOLO para Stop. SessionEnd intenta siempre enviar el resto.
    if not es_cierre and (ahora - ultimo) < intervalo:
        return 0

    size = os.path.getsize(transcript)
    if size <= offset and not es_cierre:
        return 0

    with open(transcript, "rb") as f:
        f.seek(min(offset, size))
        chunk = f.read().decode("utf-8", "ignore")

    mensajes: list[tuple[str, str]] = []
    archivos: set[str] = set()
    ultimo_user = ""
    for linea in chunk.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            obj = json.loads(linea)
        except Exception:
            continue
        tipo = obj.get("type")
        msg = obj.get("message") or {}
        if tipo == "user":
            txt = _texto_de_contenido(msg.get("content"))
            if txt:
                mensajes.append(("U", txt))
                ultimo_user = txt
        elif tipo == "assistant":
            txt = _texto_de_contenido(msg.get("content"))
            if txt:
                mensajes.append(("A", txt))
            _archivos_de_contenido(msg.get("content"), archivos)

    if not mensajes and not es_cierre:
        return 0

    titulo = " ".join(ultimo_user.split())[:100] or "(sin mensaje de usuario)"

    lineas = []
    for rol, txt in mensajes:
        plano = " ".join(txt.split())
        if len(plano) > MAX_CHARS_LINEA:
            plano = plano[:MAX_CHARS_LINEA] + "…"
        lineas.append(f"{rol}: {plano}")
    if len(lineas) > MAX_LINEAS_RESUMEN:
        lineas = lineas[-MAX_LINEAS_RESUMEN:]
    resumen = "\n".join(lineas) if lineas else "(tramo sin texto)"

    body = json.dumps(
        {
            "origen": "claude_code",
            "proyecto": _proyecto_por_cwd(cwd),
            "titulo": titulo,
            "resumen": resumen,
            "pendientes": "",
            "archivos": ", ".join(sorted(archivos))[:1000],
            "etiquetas": event,
            "session_id": session_id,
            "tipo": "cierre" if es_cierre else "avance",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    # Marca ultimo_envio ya (respeta throttle aunque el POST falle).
    state["ultimo_envio"] = ahora
    state.setdefault("offset_transcript", offset)
    state_file.write_text(json.dumps(state), encoding="utf-8")

    # POST best-effort; el offset solo avanza si el POST tuvo éxito.
    try:
        req = urllib.request.Request(
            f"{api_url}/api/sesiones",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if 200 <= resp.status < 300:
                state["offset_transcript"] = size
                state_file.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass  # falla en silencio

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # NUNCA bloquear a Claude Code
