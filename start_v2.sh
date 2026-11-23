#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend_v2"
FRONTEND_DIR="${PROJECT_DIR}/frontend"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

backend_pid=""
frontend_pid=""

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

listening_pids() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
}

free_port() {
  local port="$1"
  local service="$2"
  local pids
  pids="$(listening_pids "${port}")"
  if [[ -z "${pids}" ]]; then
    return 0
  fi
  printf '正在释放%s端口 %s（PID %s）…\n' \
    "${service}" "${port}" "$(printf '%s' "${pids}" | tr '\n' ' ')"
  # Stopped jobs (Ctrl-Z) ignore SIGTERM until continued.
  # shellcheck disable=SC2086
  kill -TERM ${pids} 2>/dev/null || true
  # shellcheck disable=SC2086
  kill -CONT ${pids} 2>/dev/null || true
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    [[ -z "$(listening_pids "${port}")" ]] && return 0
    sleep 0.2
  done
  pids="$(listening_pids "${port}")"
  if [[ -n "${pids}" ]]; then
    # shellcheck disable=SC2086
    kill -KILL ${pids} 2>/dev/null || true
    sleep 0.2
  fi
  if [[ -n "$(listening_pids "${port}")" ]]; then
    die "${service}端口 ${port} 仍被占用，无法启动。"
  fi
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM HUP
  [[ -n "${backend_pid}" ]] && kill "${backend_pid}" 2>/dev/null || true
  [[ -n "${frontend_pid}" ]] && kill "${frontend_pid}" 2>/dev/null || true
  [[ -n "${backend_pid}" ]] && wait "${backend_pid}" 2>/dev/null || true
  [[ -n "${frontend_pid}" ]] && wait "${frontend_pid}" 2>/dev/null || true
  exit "${status}"
}

trap cleanup EXIT INT TERM HUP

backend_python="${PYTHON_BIN:-${BACKEND_DIR}/.venv/bin/python}"
vite_bin="${FRONTEND_DIR}/node_modules/.bin/vite"

[[ -x "${backend_python}" ]] \
  || die "未找到 backend_v2 虚拟环境；请先按 backend_v2/README.md 安装。"
[[ -x "${vite_bin}" ]] \
  || die "前端依赖未安装；请先运行 cd frontend && npm install。"

"${backend_python}" -c \
  'import fastapi, sqlalchemy, sqlglot, uvicorn, xiaoying_quick' 2>/dev/null \
  || die "V2 后端依赖不完整；请运行 backend_v2/.venv/bin/pip install -e backend_v2。"

free_port "${BACKEND_PORT}" "后端"
free_port "${FRONTEND_PORT}" "前端"

printf '正在启动 Quick V2 后端：http://%s:%s\n' "${BACKEND_HOST}" "${BACKEND_PORT}"
(
  cd "${BACKEND_DIR}"
  exec "${backend_python}" -m uvicorn xiaoying_quick.app:app \
    --host "${BACKEND_HOST}" \
    --port "${BACKEND_PORT}"
) &
backend_pid=$!

proxy_host="${BACKEND_HOST}"
[[ "${proxy_host}" == "0.0.0.0" ]] && proxy_host="127.0.0.1"
export VITE_DEV_API_TARGET="${VITE_DEV_API_TARGET:-http://${proxy_host}:${BACKEND_PORT}}"

printf '正在启动 Quick V2 前端：http://%s:%s\n' "${FRONTEND_HOST}" "${FRONTEND_PORT}"
(
  cd "${FRONTEND_DIR}"
  exec "${vite_bin}" \
    --host "${FRONTEND_HOST}" \
    --port "${FRONTEND_PORT}" \
    --strictPort
) &
frontend_pid=$!

printf 'Quick V2 已启动；按 Ctrl+C 同时关闭前后端。\n'
printf '本地登录：admin / REPLACE_PRIVATE_CREDENTIAL\n'
printf '首次使用请先：backend_v2/tools/prepare_local.sh\n'

while kill -0 "${backend_pid}" 2>/dev/null \
  && kill -0 "${frontend_pid}" 2>/dev/null; do
  sleep 1
done

set +e
if ! kill -0 "${backend_pid}" 2>/dev/null; then
  wait "${backend_pid}"
  status=$?
  printf 'V2 后端进程已退出（状态码：%s）。\n' "${status}" >&2
else
  wait "${frontend_pid}"
  status=$?
  printf 'V2 前端进程已退出（状态码：%s）。\n' "${status}" >&2
fi
set -e

exit "${status}"
