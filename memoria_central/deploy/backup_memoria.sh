#!/usr/bin/env bash
# Backup diario de memoria.db con rotación de 30 días.
# Usa `sqlite3 .backup` para una copia consistente respetando WAL.
#
# Cron sugerido (como usuario memoria), p. ej. /etc/cron.d/memoria-backup:
#   30 3 * * * memoria /opt/memoria_central/deploy/backup_memoria.sh >/dev/null 2>&1
set -euo pipefail

ROOT="${MEMORIA_ROOT:-/opt/memoria_central}"
DB="${MEMORIA_DB_PATH:-$ROOT/data/memoria.db}"
BK="$ROOT/backups"

mkdir -p "$BK"
TS="$(date -u +%Y%m%d-%H%M%S)"
DEST="$BK/memoria-$TS.db"

# Copia consistente (incluye contenido de WAL).
sqlite3 "$DB" ".backup '$DEST'"
gzip -f "$DEST"

# Rotación: borrar copias de más de 30 días.
find "$BK" -name 'memoria-*.db.gz' -mtime +30 -delete
