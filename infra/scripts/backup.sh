#!/usr/bin/env bash
# Dump the application and warehouse database in custom format to backups/ (created if missing).
# Run from the repository root: infra/scripts/backup.sh
set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

DB="${POSTGRES_DB:-copilot}"
USER_NAME="${POSTGRES_SUPERUSER:-postgres}"
OUT_DIR="${BACKUP_DIR:-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="${OUT_DIR}/${DB}-${STAMP}.dump"

mkdir -p "${OUT_DIR}"
docker compose exec -T postgres pg_dump -U "${USER_NAME}" -d "${DB}" -Fc --no-owner >"${TARGET}"

if [ ! -s "${TARGET}" ]; then
  echo "Backup failed: ${TARGET} is empty" >&2
  rm -f "${TARGET}"
  exit 1
fi

sha256sum "${TARGET}" >"${TARGET}.sha256"
echo "Wrote ${TARGET} ($(wc -c <"${TARGET}") bytes)"
