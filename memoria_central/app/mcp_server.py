"""Capa MCP de Memoria Central YOOHOO.

SDK oficial `mcp` (FastMCP), transporte Streamable HTTP. La app ASGI se obtiene
con `mcp.streamable_http_app()` y se monta en `/mcp` desde main.py. La
autenticación (Bearer estático + OAuth 2.1) se aplica como middleware en el
montaje, ver main.py y oauth.py.

Las 5 tools son envoltorios finos sobre la capa db.py.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import db

# El transporte Streamable HTTP valida el header Host (protección anti
# DNS-rebinding). Como uvicorn escucha en 127.0.0.1, FastMCP la auto-activa solo
# para localhost y rechazaría el host público que reenvía nginx. Añadimos el
# host de MEMORIA_PUBLIC_URL a la lista de permitidos (mantenemos la protección).
_public = os.environ.get("MEMORIA_PUBLIC_URL", "http://127.0.0.1:8742")
_host = urlparse(_public).netloc  # p.ej. memoria.yoohoo.mx
_allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_allowed_origins = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
if _host:
    _allowed_hosts += [_host, f"{_host}:*"]
    _allowed_origins += [_public, f"https://{_host}", f"http://{_host}"]

# stateless_http=True: cada request es autocontenida (sin estado de sesión MCP),
# ideal para un conector remoto detrás de un proxy.
mcp = FastMCP(
    "Memoria Central YOOHOO",
    stateless_http=True,
    json_response=True,
    # Ruta interna /mcp; el sub-app se monta en "/" desde main.py, así el
    # endpoint final es exactamente /mcp sin redirección de trailing-slash.
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    ),
)


@mcp.tool()
def registrar_sesion(
    origen: str,
    proyecto: str,
    titulo: str,
    resumen: str,
    pendientes: str = "",
    archivos: str = "",
    etiquetas: str = "",
    session_id: str = "",
    tipo: str = "manual",
) -> dict[str, Any]:
    """Registra un avance o cierre de sesión en la memoria central.

    origen: claude_code|cowork|claude_ai|manual
    proyecto: yoohoo|lyb|isabela|asia_market|otro
    tipo: avance|cierre|manual
    session_id: agrupa varios avances de una misma sesión larga (días).
    """
    new_id = db.insert_sesion(
        origen=origen,
        proyecto=proyecto,
        titulo=titulo,
        resumen=resumen,
        pendientes=pendientes,
        archivos=archivos,
        etiquetas=etiquetas,
        session_id=session_id,
        tipo=tipo,
    )
    return {"id": new_id, "ok": True}


@mcp.tool()
def buscar_sesiones(
    q: str = "",
    proyecto: str = "",
    desde: str = "",
    hasta: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Busca registros. `q` usa FTS5 (título+resumen+pendientes).

    desde/hasta en ISO-8601 (ej. 2026-06-01). Devuelve los más recientes primero.
    """
    items = db.query_sesiones(
        q=q, proyecto=proyecto, desde=desde, hasta=hasta, limit=limit
    )
    return {"count": len(items), "items": items}


@mcp.tool()
def resumen_semanal() -> dict[str, Any]:
    """Resumen de los últimos 7 días agrupado por proyecto: conteo y pendientes."""
    return db.resumen_semanal()


@mcp.tool()
def pendientes_abiertos(proyecto: str = "") -> dict[str, Any]:
    """Lista los pendientes abiertos (no cerrados), opcionalmente por proyecto."""
    items = db.pendientes_abiertos(proyecto=proyecto)
    return {"count": len(items), "items": items}


@mcp.tool()
def avance_sesion(session_id: str) -> dict[str, Any]:
    """Devuelve TODOS los registros de una sesión en orden cronológico.

    Reconstruye la película completa de una sesión que duró varios días.
    """
    items = db.avance_sesion(session_id)
    return {"session_id": session_id, "count": len(items), "items": items}
