#!/usr/bin/env bash
# Restore a dump made by backup.sh into the running postgres service.
# Usage: infra/scripts/restore.sh backups/copilot-<stamp>.dump --confirm
# The target database is replaced (pg_restore --clean). Refuses to run without --confirm.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <dump-file> --confirm" >&2
  exit 2
fi

DUMP="$1"
if [ "${2:-}" != "--confirm" ]; then
  echo "This replaces the contents of the target database. Re-run with --confirm." >&2
  exit 2
fi
if [ ! -s "${DUMP}" ]; then
  echo "Dump not found or empty: ${DUMP}" >&2
  exit 1
fi

if [ -f "${DUMP}.sha256" ]; then
  sha256sum --check --status "${DUMP}.sha256" || {
    echo "Checksum mismatch for ${DUMP}" >&2
    exit 1
  }
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

DB="${POSTGRES_DB:-copilot}"
USER_NAME="${POSTGRES_SUPERUSER:-postgres}"

docker compose exec -T postgres pg_restore -U "${USER_NAME}" -d "${DB}" --clean --if-exists --no-owner <"${DUMP}"
echo "Restored ${DUMP} into ${DB}"
