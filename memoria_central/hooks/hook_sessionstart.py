#!/usr/bin/env python3
"""Hook SessionStart de Memoria Central — carga tu contexto automáticamente.

Al iniciar CUALQUIER sesión de Claude Code, consulta tu Memoria Central y
IMPRIME a stdout un resumen (últimos días + pendientes + últimas sesiones).
Claude Code añade ese stdout al contexto de la sesión: así Claude "se pone al
día" solo, sin que escribas nada.

SIEMPRE sale 0 y falla en silencio (si la API no responde, no imprime nada,
para no retrasar el arranque).

Config (igual que hook_memoria.py): variables de entorno o `config.env` junto
al script con MEMORIA_TOKEN y MEMORIA_API_URL.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 8
MAX_PENDIENTES = 15
MAX_RECIENTES = 8
MAX_CHARS = 4000  # tope del bloque de contexto para no inflar la sesión


def _cargar_config() -> tuple[str, str]:
    token = os.environ.get("MEMORIA_TOKEN", "")
    api = os.environ.get("MEMORIA_API_URL", "https://memoria.yoohoo.mx")
    f = HERE / "config.env"
    if f.exists():
        for linea in f.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = (x.strip() for x in linea.split("=", 1))
            if k == "MEMORIA_TOKEN" and not token:
                token = v
            elif k == "MEMORIA_API_URL" and not os.environ.get("MEMORIA_API_URL"):
                api = v
    return token, api.rstrip("/")


def _get(api: str, token: str, path: str):
    req = urllib.request.Request(
        f"{api}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def main() -> int:
    token, api = _cargar_config()
    if not token:
        return 0

    try:
        resumen = _get(api, token, "/api/resumen-semanal")
        pendientes = _get(api, token, "/api/pendientes")
        recientes = _get(api, token, "/api/sesiones?limit=%d" % MAX_RECIENTES)
    except Exception:
        return 0  # silencio si la API no responde

    out: list[str] = []
    out.append("=== Memoria Central YOOHOO — contexto de sesiones previas ===")

    proyectos = (resumen or {}).get("proyectos") or {}
    total = (resumen or {}).get("total", 0)
    if total:
        conteos = ", ".join(
            f"{p}: {g.get('conteo', 0)}" for p, g in proyectos.items()
        )
        out.append(f"\nÚltimos 7 días ({total} registros) — {conteos}")

    pend_items = (pendientes or {}).get("items") or []
    if pend_items:
        out.append(f"\nPendientes abiertos ({len(pend_items)}):")
        for it in pend_items[:MAX_PENDIENTES]:
            txt = " ".join((it.get("pendientes") or "").split())[:150]
            out.append(f"  - [{it.get('proyecto', 'otro')}] {txt}")

    rec_items = (recientes or {}).get("items") or []
    if rec_items:
        out.append("\nÚltimas sesiones registradas:")
        for it in rec_items:
            fecha = (it.get("fecha") or "")[:10]
            titulo = " ".join((it.get("titulo") or "").split())[:80]
            out.append(f"  - {fecha} [{it.get('proyecto', 'otro')}] {titulo}")

    if len(out) <= 1:
        return 0  # nada útil que inyectar

    out.append(
        "\nPara profundizar usa el conector 'memoria': buscar_sesiones, "
        "avance_sesion(session_id), resumen_semanal, pendientes_abiertos."
    )

    texto = "\n".join(out)
    if len(texto) > MAX_CHARS:
        texto = texto[:MAX_CHARS] + "\n…"
    print(texto)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
