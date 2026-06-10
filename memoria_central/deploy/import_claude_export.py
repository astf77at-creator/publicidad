#!/usr/bin/env python3
"""Importa el export de datos de claude.ai a Memoria Central YOOHOO.

claude.ai (Settings -> Privacy -> Export data) envía por correo un .zip con un
`conversations.json` que contiene TODAS tus conversaciones. Este script lo lee y
sube cada conversación a Memoria Central (un registro por chat).

Ejecutar donde haya red hacia la API (tu PC o el VPS). Requiere Python 3.

Uso:
  python import_claude_export.py RUTA_AL_ZIP_O_JSON \
      --api https://memoria.yoohoo.mx --token TU_MEMORIA_TOKEN

Opciones:
  --proyecto NOMBRE   fuerza el proyecto (yoohoo|lyb|isabela|asia_market|otro);
                      por defecto se infiere por palabras clave del título/texto.
  --max N             máximo de caracteres por conversación (def. 60000).
  --dry-run           no sube nada; solo muestra lo que haría.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

PROYECTOS = {"yoohoo", "lyb", "isabela", "asia_market", "otro"}


def infer_proyecto(text: str) -> str:
    t = text.lower()
    if "yoohoo" in t:
        return "yoohoo"
    if "lyb" in t or "locales" in t:
        return "lyb"
    if "isabela" in t:
        return "isabela"
    if "asia" in t:
        return "asia_market"
    return "otro"


def load_conversations(path: str):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next(
                (n for n in z.namelist() if n.endswith("conversations.json")), None
            )
            if not name:
                sys.exit("ERROR: no se encontró conversations.json dentro del .zip")
            return json.loads(z.read(name))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def msg_text(m: dict) -> str:
    """Texto de un mensaje del export (campo 'text' o lista 'content')."""
    txt = m.get("text")
    if isinstance(txt, str) and txt.strip():
        return txt.strip()
    partes = []
    for c in m.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
            partes.append(c["text"])
    return "\n".join(partes).strip()


def to_iso(s: str) -> str:
    try:
        return (
            datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except Exception:
        return (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )


def post(api: str, token: str, body: dict) -> tuple[bool, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/sesiones",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return (200 <= r.status < 300), str(r.status)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read()[:200].decode('utf-8','ignore')}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export", help="ruta al .zip del export o a conversations.json")
    ap.add_argument("--api", default="https://memoria.yoohoo.mx")
    ap.add_argument("--token", required=True)
    ap.add_argument("--proyecto", default="", help="forzar proyecto; vacío = inferir")
    ap.add_argument("--max", type=int, default=60000)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.proyecto and a.proyecto not in PROYECTOS:
        sys.exit(f"--proyecto inválido. Use uno de: {sorted(PROYECTOS)}")

    convs = load_conversations(a.export)
    if not isinstance(convs, list):
        sys.exit("ERROR: el formato no es una lista de conversaciones")

    total = len(convs)
    ok = fail = vacios = 0
    print(f"Encontradas {total} conversaciones. {'(DRY-RUN) ' if a.dry_run else ''}Subiendo...")

    for i, conv in enumerate(convs, 1):
        name = conv.get("name") or conv.get("title") or "(sin título)"
        uuid = conv.get("uuid") or conv.get("id") or ""
        created = to_iso(conv.get("created_at") or conv.get("created") or "")
        msgs = conv.get("chat_messages") or conv.get("messages") or []

        lineas = []
        for m in msgs:
            sender = (m.get("sender") or m.get("role") or "").lower()
            who = "U" if sender in ("human", "user") else "A"
            t = msg_text(m)
            if t:
                lineas.append(f"{who}: {t}")
        full = "\n".join(lineas)
        if not full.strip():
            vacios += 1
            continue
        if len(full) > a.max:
            full = full[: a.max] + "\n…[truncado]"

        proyecto = a.proyecto or infer_proyecto(f"{name}\n{full[:2000]}")
        body = {
            "origen": "claude_ai",
            "proyecto": proyecto,
            "titulo": name[:100],
            "resumen": full,
            "pendientes": "",
            "archivos": "",
            "etiquetas": "import",
            "session_id": uuid,
            "tipo": "manual",
            "fecha": created,
        }

        if a.dry_run:
            print(f"  [{i}/{total}] {created}  {proyecto:11}  {name[:60]}")
            ok += 1
            continue

        good, info = post(a.api, a.token, body)
        if good:
            ok += 1
        else:
            fail += 1
            print(f"  FALLÓ [{i}/{total}] {name[:50]} -> {info}")

    print(f"\nListo. Subidas OK: {ok} | Fallidas: {fail} | Vacías (omitidas): {vacios}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
