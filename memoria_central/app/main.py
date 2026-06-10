"""Memoria Central YOOHOO — FastAPI (REST) + montaje MCP (Streamable HTTP).

Escucha SOLO en 127.0.0.1:8742 (uvicorn). La exposición HTTPS la hace un
reverse proxy (Caddy o nginx) sobre memoria.yoohoo.mx. NUNCA exponer directo.

Auth: header `Authorization: Bearer $MEMORIA_TOKEN` en todas las rutas.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import db
from . import oauth

MEMORIA_TOKEN = os.environ.get("MEMORIA_TOKEN", "")
PUBLIC_URL = oauth.PUBLIC_URL

# La capa MCP es opcional para que la API REST arranque aunque el SDK mcp
# no esté instalado (útil en Fase 1). Si está, se monta en /mcp.
try:
    from .mcp_server import mcp as _mcp  # type: ignore
except Exception:  # pragma: no cover - degradación elegante
    _mcp = None


# --------------------------------------------------------------------------- #
# Autenticación Bearer (compartida por REST y MCP)
# --------------------------------------------------------------------------- #
_bearer = HTTPBearer(auto_error=False)


def require_token(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Valida el Bearer token en tiempo constante."""
    if not MEMORIA_TOKEN:
        # Falla cerrado: sin token configurado, nadie entra.
        raise HTTPException(status_code=503, detail="MEMORIA_TOKEN no configurado")
    if cred is None or cred.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Falta Authorization: Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(cred.credentials, MEMORIA_TOKEN):
        raise HTTPException(status_code=403, detail="Token inválido")


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class SesionIn(BaseModel):
    origen: str = Field(..., examples=["claude_code"])
    proyecto: str = Field(..., examples=["yoohoo"])
    titulo: str = ""
    resumen: str = ""
    pendientes: str = ""
    archivos: str = ""
    etiquetas: str = ""
    session_id: str = ""
    tipo: str = "manual"


# --------------------------------------------------------------------------- #
# Lifespan: arranca el session manager del MCP si está disponible
# --------------------------------------------------------------------------- #
import contextlib


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    oauth.init_oauth()
    if _mcp is not None:
        async with _mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(
    title="Memoria Central YOOHOO",
    version="1.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Rutas REST
# --------------------------------------------------------------------------- #
# Rutas de descubrimiento + flujo OAuth 2.1 (sin Bearer; son públicas por diseño)
app.include_router(oauth.router)


@app.get("/health")
def health() -> dict:
    """Sin auth: para healthchecks del proxy/systemd."""
    return {"ok": True, "mcp": _mcp is not None}


@app.post("/api/sesiones", dependencies=[Depends(require_token)])
def crear_sesion(s: SesionIn) -> dict:
    try:
        new_id = db.insert_sesion(
            origen=s.origen,
            proyecto=s.proyecto,
            titulo=s.titulo,
            resumen=s.resumen,
            pendientes=s.pendientes,
            archivos=s.archivos,
            etiquetas=s.etiquetas,
            session_id=s.session_id,
            tipo=s.tipo,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"id": new_id}


@app.get("/api/sesiones", dependencies=[Depends(require_token)])
def listar_sesiones(
    proyecto: str = "",
    desde: str = "",
    hasta: str = "",
    q: str = "",
    session_id: str = "",
    limit: int = Query(20, ge=1, le=200),
) -> dict:
    items = db.query_sesiones(
        proyecto=proyecto,
        desde=desde,
        hasta=hasta,
        q=q,
        session_id=session_id,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@app.get("/api/resumen-semanal", dependencies=[Depends(require_token)])
def resumen_semanal() -> dict:
    return db.resumen_semanal()


@app.get("/api/pendientes", dependencies=[Depends(require_token)])
def pendientes(proyecto: str = "") -> dict:
    items = db.pendientes_abiertos(proyecto=proyecto)
    return {"count": len(items), "items": items}


@app.get("/api/avance/{session_id}", dependencies=[Depends(require_token)])
def avance(session_id: str) -> dict:
    items = db.avance_sesion(session_id)
    return {"session_id": session_id, "count": len(items), "items": items}


# --------------------------------------------------------------------------- #
# Montaje MCP (Streamable HTTP) en /mcp — ver mcp_server.py
# --------------------------------------------------------------------------- #
def _token_valido(token: str) -> bool:
    """Acepta el Bearer estático (CLI/Desktop/curl) o un access token OAuth (web)."""
    if MEMORIA_TOKEN and secrets.compare_digest(token, MEMORIA_TOKEN):
        return True
    return oauth.verify_access_token(token)


class MCPAuthMiddleware:
    """Middleware ASGI puro: protege /mcp sin bufferizar el streaming.

    Si falta/!= token válido responde 401 con WWW-Authenticate que apunta al
    metadata de recurso protegido (RFC 9728), que es como claude.ai descubre
    el flujo OAuth.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""

        if not token or not _token_valido(token):
            resource_meta = f'{PUBLIC_URL}/.well-known/oauth-protected-resource'
            body = b'{"error":"invalid_token"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (
                            b"www-authenticate",
                            f'Bearer resource_metadata="{resource_meta}"'.encode(
                                "latin-1"
                            ),
                        ),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


if _mcp is not None:
    # streamable_http_app() expone la ruta en /mcp (streamable_http_path).
    # La envolvemos con el middleware de auth y la montamos en "/": las rutas
    # REST/OAuth, declaradas antes y más específicas, tienen prioridad; solo
    # /mcp cae aquí, sin redirección de trailing-slash.
    app.mount("/", MCPAuthMiddleware(_mcp.streamable_http_app()))
