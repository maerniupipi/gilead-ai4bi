#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
export PYTHONPATH="${ROOT}:${ROOT}/app${PYTHONPATH:+:$PYTHONPATH}"
if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${ROOT}/.env"
  set +a
fi
export XIAOYING_KNOWLEDGE_ROOT="${XIAOYING_KNOWLEDGE_ROOT:-${ROOT}/knowledge}"
export XIAOYING_SECRET_STORE_PATH="${XIAOYING_SECRET_STORE_PATH:-${ROOT}/var/secrets.json}"
export XIAOYING_SECRET_KEY_PATH="${XIAOYING_SECRET_KEY_PATH:-${ROOT}/var/master.key}"
mkdir -p "${ROOT}/var"
cd "${ROOT}"

exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
