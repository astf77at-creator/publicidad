#!/usr/bin/env python3
"""Lógica del hook incremental de Memoria Central.

Lee el payload del hook (variable de entorno PAYLOAD), aplica el throttle por
session_id, lee SOLO el tramo nuevo del transcript (desde offset_transcript) y
construye el cuerpo JSON del POST. NO hace la petición HTTP: eso lo hace el
wrapper bash con curl (timeout 10s, falla en silencio).

Salida por stdout (una línea, campos separados por TAB):
    SKIP
    SEND<TAB><nuevo_offset><TAB><ruta_state_file>

Cuando decide SEND:
  - escribe el cuerpo JSON en el fichero $MEMORIA_BODY_FILE
  - actualiza el state con ultimo_envio=ahora (para respetar el throttle aunque
    el POST falle) y guarda offset_pendiente=nuevo_offset.
El offset_transcript SOLO se confirma (avanza) si el POST tuvo éxito, vía
--commit (lo invoca el wrapper bash tras un curl correcto).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

MAX_LINEAS_RESUMEN = 30
MAX_CHARS_LINEA = 220
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Create"}


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
    """Extrae texto plano de un campo message.content (str o lista de bloques)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        partes = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text", "")
                if t:
                    partes.append(t)
        return "\n".join(partes).strip()
    return ""


def _archivos_de_contenido(content, acc: set[str]) -> None:
    """Acumula rutas de ficheros tocados por tools de edición en el tramo."""
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


def _commit(state_file: str, nuevo_offset: int) -> None:
    p = Path(state_file)
    d = {}
    if p.exists():
        try:
            d = json.loads(p.read_text())
        except Exception:
            d = {}
    d["offset_transcript"] = int(nuevo_offset)
    d.pop("offset_pendiente", None)
    p.write_text(json.dumps(d))


def main() -> int:
    if len(sys.argv) >= 4 and sys.argv[1] == "--commit":
        _commit(sys.argv[2], int(sys.argv[3]))
        return 0

    payload = json.loads(os.environ.get("PAYLOAD", "{}"))
    session_id = payload.get("session_id") or ""
    transcript = payload.get("transcript_path") or ""
    cwd = payload.get("cwd") or ""
    event = payload.get("hook_event_name") or ""

    if not session_id or not transcript or not os.path.exists(transcript):
        print("SKIP")
        return 0

    state_dir = Path(os.environ["STATE_DIR"])
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{session_id}.json"

    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except Exception:
            state = {}
    ultimo = float(state.get("ultimo_envio", 0))
    offset = int(state.get("offset_transcript", 0))

    intervalo = int(os.environ.get("MEMORIA_INTERVALO_MIN", "60")) * 60
    ahora = time.time()
    es_cierre = event == "SessionEnd"

    # Throttle SOLO para Stop. SessionEnd (cierre) siempre intenta enviar el resto.
    if not es_cierre and (ahora - ultimo) < intervalo:
        print("SKIP")
        return 0

    size = os.path.getsize(transcript)
    if size <= offset and not es_cierre:
        print("SKIP")
        return 0

    with open(transcript, "rb") as f:
        f.seek(min(offset, size))
        chunk = f.read().decode("utf-8", "ignore")

    mensajes: list[tuple[str, str]] = []  # (rol, texto)
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
        print("SKIP")
        return 0

    # Título = último mensaje de usuario del tramo, truncado a 100 chars.
    una_linea = " ".join(ultimo_user.split())
    titulo = (una_linea[:100] or "(sin mensaje de usuario)")

    # Resumen = mensajes del tramo condensados (~30 líneas máx).
    lineas = []
    for rol, txt in mensajes:
        plano = " ".join(txt.split())
        if len(plano) > MAX_CHARS_LINEA:
            plano = plano[:MAX_CHARS_LINEA] + "…"
        lineas.append(f"{rol}: {plano}")
    if len(lineas) > MAX_LINEAS_RESUMEN:
        lineas = lineas[-MAX_LINEAS_RESUMEN:]
    resumen = "\n".join(lineas) if lineas else "(tramo sin texto)"

    body = {
        "origen": "claude_code",
        "proyecto": _proyecto_por_cwd(cwd),
        "titulo": titulo,
        "resumen": resumen,
        "pendientes": "",
        "archivos": ", ".join(sorted(archivos))[:1000],
        "etiquetas": event,
        "session_id": session_id,
        "tipo": "cierre" if es_cierre else "avance",
    }

    Path(os.environ["MEMORIA_BODY_FILE"]).write_text(
        json.dumps(body, ensure_ascii=False)
    )

    # Marca ultimo_envio ya (respeta throttle aunque el POST falle); offset se
    # confirmará vía --commit solo si el curl tiene éxito.
    state["ultimo_envio"] = ahora
    state["offset_pendiente"] = size
    state.setdefault("offset_transcript", offset)
    state_file.write_text(json.dumps(state))

    print(f"SEND\t{size}\t{state_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
