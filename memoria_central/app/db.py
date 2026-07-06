"""Capa de datos de Memoria Central YOOHOO.

SQLite en modo WAL + tabla virtual FTS5 sincronizada por triggers.
La tabla `sesiones` agrupa avances INCREMENTALES de una misma sesión larga
mediante la columna `session_id` (una sesión puede durar días y generar
muchos registros de tipo "avance" antes de un eventual "cierre").
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# Ruta de la BD: configurable por entorno, default junto al paquete.
DB_PATH = Path(
    os.environ.get(
        "MEMORIA_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "memoria.db"),
    )
)

ORIGENES = {"claude_code", "cowork", "claude_ai", "manual"}
PROYECTOS = {"yoohoo", "lyb", "isabela", "asia_market", "otro"}
TIPOS = {"avance", "cierre", "manual"}


def _now_iso() -> str:
    """Timestamp ISO-8601 en UTC, con sufijo Z."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def get_conn() -> sqlite3.Connection:
    """Conexión SQLite con WAL, claves foráneas y row factory por nombre."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS sesiones (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL DEFAULT '',
    fecha       TEXT    NOT NULL,            -- ISO-8601 UTC
    origen      TEXT    NOT NULL,            -- claude_code|cowork|claude_ai|manual
    proyecto    TEXT    NOT NULL,            -- yoohoo|lyb|isabela|asia_market|otro
    titulo      TEXT    NOT NULL DEFAULT '',
    resumen     TEXT    NOT NULL DEFAULT '',
    pendientes  TEXT    NOT NULL DEFAULT '',
    archivos    TEXT    NOT NULL DEFAULT '',
    etiquetas   TEXT    NOT NULL DEFAULT '',
    tipo        TEXT    NOT NULL DEFAULT 'manual'  -- avance|cierre|manual
);

CREATE INDEX IF NOT EXISTS idx_sesiones_fecha      ON sesiones(fecha);
CREATE INDEX IF NOT EXISTS idx_sesiones_proyecto   ON sesiones(proyecto);
CREATE INDEX IF NOT EXISTS idx_sesiones_session_id ON sesiones(session_id);

-- FTS5 con contenido externo sobre titulo + resumen + pendientes.
CREATE VIRTUAL TABLE IF NOT EXISTS sesiones_fts USING fts5(
    titulo, resumen, pendientes,
    content='sesiones',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers para mantener el índice FTS sincronizado.
CREATE TRIGGER IF NOT EXISTS sesiones_ai AFTER INSERT ON sesiones BEGIN
    INSERT INTO sesiones_fts(rowid, titulo, resumen, pendientes)
    VALUES (new.id, new.titulo, new.resumen, new.pendientes);
END;

CREATE TRIGGER IF NOT EXISTS sesiones_ad AFTER DELETE ON sesiones BEGIN
    INSERT INTO sesiones_fts(sesiones_fts, rowid, titulo, resumen, pendientes)
    VALUES ('delete', old.id, old.titulo, old.resumen, old.pendientes);
END;

CREATE TRIGGER IF NOT EXISTS sesiones_au AFTER UPDATE ON sesiones BEGIN
    INSERT INTO sesiones_fts(sesiones_fts, rowid, titulo, resumen, pendientes)
    VALUES ('delete', old.id, old.titulo, old.resumen, old.pendientes);
    INSERT INTO sesiones_fts(rowid, titulo, resumen, pendientes)
    VALUES (new.id, new.titulo, new.resumen, new.pendientes);
END;
"""


def init_db() -> None:
    """Crea esquema, índices, tabla FTS y triggers (idempotente)."""
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _validar(campo: str, valor: str, permitidos: set[str]) -> str:
    if valor not in permitidos:
        raise ValueError(
            f"{campo} inválido: {valor!r}. Permitidos: {sorted(permitidos)}"
        )
    return valor


def insert_sesion(
    *,
    origen: str,
    proyecto: str,
    titulo: str,
    resumen: str,
    pendientes: str = "",
    archivos: str = "",
    etiquetas: str = "",
    session_id: str = "",
    tipo: str = "manual",
    fecha: str | None = None,
) -> int:
    """Inserta un registro y devuelve su id."""
    _validar("origen", origen, ORIGENES)
    _validar("proyecto", proyecto, PROYECTOS)
    _validar("tipo", tipo, TIPOS)
    fecha = fecha or _now_iso()

    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO sesiones
                (session_id, fecha, origen, proyecto, titulo,
                 resumen, pendientes, archivos, etiquetas, tipo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                fecha,
                origen,
                proyecto,
                titulo,
                resumen,
                pendientes,
                archivos,
                etiquetas,
                tipo,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _fts_query(q: str) -> str:
    """Convierte texto libre en una consulta FTS5 segura (prefijo por término).

    Cada palabra se envuelve entre comillas dobles para neutralizar la sintaxis
    especial de FTS5 y se le añade `*` para búsqueda por prefijo.
    """
    terminos = [t for t in q.replace('"', " ").split() if t]
    if not terminos:
        return ""
    return " ".join(f'"{t}"*' for t in terminos)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def query_sesiones(
    *,
    proyecto: str = "",
    desde: str = "",
    hasta: str = "",
    q: str = "",
    session_id: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Búsqueda con filtros opcionales. `q` usa FTS5; el resto son filtros SQL.

    `desde`/`hasta` se comparan como ISO-8601 (orden lexicográfico == cronológico).
    """
    limit = max(1, min(int(limit), 200))
    where: list[str] = []
    params: list[Any] = []
    join = ""

    if q:
        fts = _fts_query(q)
        if fts:
            join = "JOIN sesiones_fts f ON f.rowid = s.id"
            where.append("sesiones_fts MATCH ?")
            params.append(fts)

    if proyecto:
        where.append("s.proyecto = ?")
        params.append(proyecto)
    if session_id:
        where.append("s.session_id = ?")
        params.append(session_id)
    if desde:
        where.append("s.fecha >= ?")
        params.append(desde)
    if hasta:
        where.append("s.fecha <= ?")
        params.append(hasta)

    sql = f"SELECT s.* FROM sesiones s {join}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.fecha DESC, s.id DESC LIMIT ?"
    params.append(limit)

    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def resumen_semanal() -> dict[str, Any]:
    """Resumen de los últimos 7 días agrupado por proyecto.

    Para cada proyecto: conteo de registros y lista de pendientes no vacíos.
    """
    desde = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")

    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT proyecto, fecha, titulo, pendientes, tipo, session_id
            FROM sesiones
            WHERE fecha >= ?
            ORDER BY proyecto, fecha DESC
            """,
            (desde,),
        ).fetchall()
    finally:
        conn.close()

    grupos: dict[str, dict[str, Any]] = {}
    for r in rows:
        g = grupos.setdefault(
            r["proyecto"], {"conteo": 0, "pendientes": [], "registros": []}
        )
        g["conteo"] += 1
        if r["pendientes"].strip():
            g["pendientes"].append(
                {"fecha": r["fecha"], "titulo": r["titulo"], "texto": r["pendientes"]}
            )
        g["registros"].append(
            {"fecha": r["fecha"], "titulo": r["titulo"], "tipo": r["tipo"]}
        )

    return {
        "desde": desde,
        "hasta": _now_iso(),
        "total": sum(g["conteo"] for g in grupos.values()),
        "proyectos": grupos,
    }


def pendientes_abiertos(proyecto: str = "") -> list[dict[str, Any]]:
    """Registros con `pendientes` no vacío, opcionalmente filtrados por proyecto.

    Se excluyen los de tipo "cierre" (se asume que cerraron el tramo).
    """
    where = ["pendientes <> ''", "tipo <> 'cierre'"]
    params: list[Any] = []
    if proyecto:
        where.append("proyecto = ?")
        params.append(proyecto)

    sql = (
        "SELECT id, session_id, fecha, proyecto, titulo, pendientes, tipo "
        "FROM sesiones WHERE " + " AND ".join(where) + " ORDER BY fecha DESC"
    )
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def avance_sesion(session_id: str) -> list[dict[str, Any]]:
    """Todos los registros de una sesión en orden CRONOLÓGICO (ascendente).

    Reconstruye la "película completa" de una sesión de varios días.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sesiones WHERE session_id = ? ORDER BY fecha ASC, id ASC",
            (session_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
