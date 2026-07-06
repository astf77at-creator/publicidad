#!/usr/bin/env bash
# Instalador idempotente de Memoria Central YOOHOO en el VPS.
# Mismo patrón operativo que /opt/descargador_imagenes (venv + systemd).
# Ejecutar como root:  sudo bash deploy/install.sh
#
# NO imprime el token. Lo genera (si falta) y lo guarda en /opt/memoria_central/.env (chmod 600).
set -euo pipefail

DEST="/opt/memoria_central"
SVC_USER="memoria"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Verificando Python 3.11+"
PYV="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
echo "    Python $PYV"
python3 -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,11) else 1)' \
    || { echo "ERROR: se requiere Python 3.11+"; exit 1; }

echo "==> Usuario de servicio: $SVC_USER"
id -u "$SVC_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$SVC_USER"

echo "==> Copiando código a $DEST"
mkdir -p "$DEST"
# Copiar app/, hooks/, deploy/, requirements.txt; preservar data/ y backups/ existentes.
cp -r "$SRC/app" "$DEST/"
cp -r "$SRC/hooks" "$DEST/"
cp -r "$SRC/deploy" "$DEST/"
cp "$SRC/requirements.txt" "$DEST/"
[ -f "$SRC/.env.example" ] && cp -n "$SRC/.env.example" "$DEST/.env.example" || true
mkdir -p "$DEST/data" "$DEST/backups" "$DEST/hooks/state"

echo "==> Entorno virtual + dependencias"
if [ ! -x "$DEST/venv/bin/python" ]; then
    python3 -m venv "$DEST/venv"
fi
"$DEST/venv/bin/pip" install --quiet --upgrade pip
"$DEST/venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

echo "==> Archivo .env"
if [ ! -f "$DEST/.env" ]; then
    TOKEN="$(openssl rand -hex 32)"
    cat > "$DEST/.env" <<EOF
MEMORIA_TOKEN=$TOKEN
MEMORIA_DB_PATH=$DEST/data/memoria.db
MEMORIA_HOST=127.0.0.1
MEMORIA_PORT=8742
MEMORIA_INTERVALO_MIN=60
MEMORIA_API_URL=http://127.0.0.1:8742
MEMORIA_PUBLIC_URL=https://memoria.yoohoo.mx
EOF
    echo "    .env creado con token nuevo (no se imprime)."
else
    echo "    .env ya existe; no se toca."
fi
chmod 600 "$DEST/.env"
chmod +x "$DEST/hooks/hook_memoria.sh" "$DEST/deploy/backup_memoria.sh" || true

echo "==> Permisos"
chown -R "$SVC_USER:$SVC_USER" "$DEST"

echo "==> systemd"
cp "$DEST/deploy/memoria-central.service" /etc/systemd/system/memoria-central.service
systemctl daemon-reload
systemctl enable memoria-central.service
systemctl restart memoria-central.service

echo "==> Cron de backup"
cp "$DEST/deploy/memoria-backup.cron" /etc/cron.d/memoria-backup
chmod 644 /etc/cron.d/memoria-backup

echo "==> Listo. Estado:"
sleep 1
systemctl --no-pager --full status memoria-central.service | head -n 12 || true
echo
echo "El token quedó en: $DEST/.env  (variable MEMORIA_TOKEN, chmod 600)"
echo "Healthcheck:  curl -s http://127.0.0.1:8742/health"
