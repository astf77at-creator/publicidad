"""OAuth 2.1 mínimo para que el conector remoto de la WEB de claude.ai funcione.

claude.ai (web) NO admite Bearer estático ni cabeceras personalizadas: exige
OAuth 2.1 con descubrimiento + registro dinámico + PKCE. Este módulo implementa
lo justo y necesario, actuando el `MEMORIA_TOKEN` como credencial humana en la
pantalla de autorización:

  RFC 9728  Protected Resource Metadata   GET /.well-known/oauth-protected-resource
  RFC 8414  Authorization Server Metadata GET /.well-known/oauth-authorization-server
  RFC 7591  Dynamic Client Registration   POST /register
            Authorization (PKCE S256)     GET/POST /authorize
            Token / Refresh               POST /token

El Bearer estático (MEMORIA_TOKEN) sigue siendo válido en paralelo para
Claude Code CLI, Claude Desktop, MCP Inspector y curl (ver main.py).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import db

# URL pública (issuer). En el VPS: https://memoria.yoohoo.mx
PUBLIC_URL = os.environ.get("MEMORIA_PUBLIC_URL", "http://127.0.0.1:8742").rstrip("/")

CODE_TTL = 600           # 10 min para canjear el código
ACCESS_TTL = 365 * 24 * 3600   # token de acceso de larga duración (uso personal)

router = APIRouter()


# --------------------------------------------------------------------------- #
# Estado en SQLite (sobrevive a reinicios del servicio)
# --------------------------------------------------------------------------- #
OAUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id     TEXT PRIMARY KEY,
    redirect_uris TEXT NOT NULL,      -- separadas por espacio
    client_name   TEXT,
    created        INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code           TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    scope          TEXT,
    expira         INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    token      TEXT PRIMARY KEY,
    tipo       TEXT NOT NULL,         -- access|refresh
    client_id  TEXT NOT NULL,
    scope      TEXT,
    expira     INTEGER NOT NULL
);
"""


def init_oauth() -> None:
    conn = db.get_conn()
    try:
        conn.executescript(OAUTH_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _token() -> str:
    return secrets.token_urlsafe(32)


def _now() -> int:
    return int(time.time())


def verify_access_token(token: str) -> bool:
    """True si `token` es un access token OAuth vigente."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT expira FROM oauth_tokens WHERE token=? AND tipo='access'",
            (token,),
        ).fetchone()
    finally:
        conn.close()
    return bool(row) and int(row["expira"]) > _now()


# --------------------------------------------------------------------------- #
# Metadata de descubrimiento
# --------------------------------------------------------------------------- #
@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource_metadata() -> JSONResponse:
    return JSONResponse(
        {
            "resource": f"{PUBLIC_URL}/mcp",
            "authorization_servers": [PUBLIC_URL],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["memoria"],
        }
    )


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
def authorization_server_metadata() -> JSONResponse:
    return JSONResponse(
        {
            "issuer": PUBLIC_URL,
            "authorization_endpoint": f"{PUBLIC_URL}/authorize",
            "token_endpoint": f"{PUBLIC_URL}/token",
            "registration_endpoint": f"{PUBLIC_URL}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["memoria"],
        }
    )


# --------------------------------------------------------------------------- #
# Registro dinámico de cliente (RFC 7591)
# --------------------------------------------------------------------------- #
@router.post("/register")
async def register(request: Request) -> JSONResponse:
    body = await request.json()
    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uris requerido")
    client_id = "mc_" + secrets.token_hex(16)
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO oauth_clients(client_id, redirect_uris, client_name, created)"
            " VALUES (?,?,?,?)",
            (
                client_id,
                " ".join(redirect_uris),
                body.get("client_name", ""),
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse(
        status_code=201,
        content={
            "client_id": client_id,
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": body.get("client_name", ""),
        },
    )


def _client_ok(client_id: str, redirect_uri: str) -> bool:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT redirect_uris FROM oauth_clients WHERE client_id=?",
            (client_id,),
        ).fetchone()
    finally:
        conn.close()
    return bool(row) and redirect_uri in row["redirect_uris"].split()


# --------------------------------------------------------------------------- #
# Autorización con PKCE: el MEMORIA_TOKEN actúa de credencial
# --------------------------------------------------------------------------- #
_FORM = """<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Memoria Central — Autorizar</title>
<style>body{{font-family:system-ui;max-width:380px;margin:8vh auto;padding:0 1rem}}
input{{width:100%;padding:.6rem;font-size:1rem;box-sizing:border-box}}
button{{margin-top:1rem;padding:.6rem 1.2rem;font-size:1rem;cursor:pointer}}
.err{{color:#b00;margin:.5rem 0}}</style></head><body>
<h2>Memoria Central YOOHOO</h2>
<p>Autoriza el acceso de <b>{client}</b> pegando tu token de acceso.</p>
{error}
<form method=post action="/authorize">
<input type=password name=token placeholder="MEMORIA_TOKEN" autofocus required>
<input type=hidden name=client_id value="{client_id}">
<input type=hidden name=redirect_uri value="{redirect_uri}">
<input type=hidden name=code_challenge value="{code_challenge}">
<input type=hidden name=state value="{state}">
<input type=hidden name=scope value="{scope}">
<button type=submit>Autorizar</button>
</form></body></html>"""


@router.get("/authorize")
def authorize_form(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    state: str = "",
    scope: str = "memoria",
    resource: str = "",
) -> HTMLResponse:
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type debe ser 'code'")
    if code_challenge_method != "S256" or not code_challenge:
        raise HTTPException(status_code=400, detail="PKCE S256 requerido")
    if not _client_ok(client_id, redirect_uri):
        raise HTTPException(status_code=400, detail="client_id/redirect_uri inválido")
    html = _FORM.format(
        client=client_id,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        state=state,
        scope=scope,
        error="",
    )
    return HTMLResponse(html)


@router.post("/authorize", response_model=None)
def authorize_submit(
    token: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    state: str = Form(""),
    scope: str = Form("memoria"),
) -> HTMLResponse | RedirectResponse:
    memoria_token = os.environ.get("MEMORIA_TOKEN", "")
    if not _client_ok(client_id, redirect_uri):
        raise HTTPException(status_code=400, detail="client_id/redirect_uri inválido")
    if not memoria_token or not secrets.compare_digest(token, memoria_token):
        html = _FORM.format(
            client=client_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            state=state,
            scope=scope,
            error='<p class=err>Token incorrecto.</p>',
        )
        return HTMLResponse(html, status_code=401)

    code = _token()
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO oauth_codes(code, client_id, redirect_uri, code_challenge,"
            " scope, expira) VALUES (?,?,?,?,?,?)",
            (code, client_id, redirect_uri, code_challenge, scope, _now() + CODE_TTL),
        )
        conn.commit()
    finally:
        conn.close()

    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


def _verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    calc = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(calc, challenge)


def _issue_tokens(client_id: str, scope: str) -> dict:
    access = _token()
    refresh = _token()
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO oauth_tokens(token, tipo, client_id, scope, expira)"
            " VALUES (?,?,?,?,?)",
            (access, "access", client_id, scope, _now() + ACCESS_TTL),
        )
        conn.execute(
            "INSERT INTO oauth_tokens(token, tipo, client_id, scope, expira)"
            " VALUES (?,?,?,?,?)",
            (refresh, "refresh", client_id, scope, _now() + ACCESS_TTL),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
        "refresh_token": refresh,
        "scope": scope,
    }


@router.post("/token")
def token(
    grant_type: str = Form(...),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(""),
    code_verifier: str = Form(""),
    refresh_token: str = Form(""),
) -> JSONResponse:
    conn = db.get_conn()
    try:
        if grant_type == "authorization_code":
            row = conn.execute(
                "SELECT * FROM oauth_codes WHERE code=?", (code,)
            ).fetchone()
            if not row or int(row["expira"]) < _now():
                return JSONResponse(status_code=400, content={"error": "invalid_grant"})
            if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
                return JSONResponse(status_code=400, content={"error": "invalid_grant"})
            if not _verify_pkce(code_verifier, row["code_challenge"]):
                return JSONResponse(status_code=400, content={"error": "invalid_grant"})
            conn.execute("DELETE FROM oauth_codes WHERE code=?", (code,))
            conn.commit()
            return JSONResponse(_issue_tokens(client_id, row["scope"] or "memoria"))

        if grant_type == "refresh_token":
            row = conn.execute(
                "SELECT * FROM oauth_tokens WHERE token=? AND tipo='refresh'",
                (refresh_token,),
            ).fetchone()
            if not row or int(row["expira"]) < _now():
                return JSONResponse(status_code=400, content={"error": "invalid_grant"})
            return JSONResponse(_issue_tokens(row["client_id"], row["scope"] or "memoria"))
    finally:
        conn.close()

    return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})
