#!/usr/bin/env bash
set -Eeuo pipefail
GILEAD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-18001}"
FRONTEND_PORT="${FRONTEND_PORT:-15173}"
SETUP_ONLY=false
case "${1:-}" in
  --setup-only) SETUP_ONLY=true ;;
  '') ;;
  *) echo '用法：./start_jilide.sh [--setup-only]' >&2; exit 2 ;;
esac
[[ -f "$GILEAD_ROOT/backend_v2/.env" ]] || { echo '缺少 backend_v2/.env 运行配置。' >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo '需要 Node.js 20 或更新版本。' >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo '需要 npm。' >&2; exit 1; }
node -e 'if(Number(process.versions.node.split(".")[0])<20)process.exit(1)' || { echo '需要 Node.js 20 或更新版本。' >&2; exit 1; }
if [[ ! -x "$GILEAD_ROOT/backend_v2/.venv/bin/python" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-}"
  if [[ -z "$PYTHON_BIN" ]]; then
    if command -v python3.13 >/dev/null 2>&1; then PYTHON_BIN=python3.13; else PYTHON_BIN=python3; fi
  fi
  "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10+，推荐 3.13"'
  "$PYTHON_BIN" -m venv "$GILEAD_ROOT/backend_v2/.venv"
fi
# Python.org 的 macOS 安装有时没有默认 CA 路径；沿用 pip 自带的根证书并保持 TLS 校验。
PIP_BUNDLED_CA="$({ "$GILEAD_ROOT/backend_v2/.venv/bin/python" -c 'from pip._vendor import certifi; print(certifi.where())'; } 2>/dev/null)"
if [[ -n "$PIP_BUNDLED_CA" ]]; then
  export PIP_CERT="${PIP_CERT:-$PIP_BUNDLED_CA}"
  export SSL_CERT_FILE="${SSL_CERT_FILE:-$PIP_BUNDLED_CA}"
fi
export PIP_DISABLE_PIP_VERSION_CHECK=1
if ! "$GILEAD_ROOT/backend_v2/.venv/bin/python" -c 'import xiaoying_quick, multipart, pymysql, cryptography' >/dev/null 2>&1; then
  echo '首次运行，正在安装后端锁定依赖。'
  "$GILEAD_ROOT/backend_v2/.venv/bin/python" -m pip install -r "$GILEAD_ROOT/backend_v2/requirements-runtime.lock" -e "$GILEAD_ROOT/backend_v2"
fi
if [[ ! -x "$GILEAD_ROOT/frontend/node_modules/.bin/vite" ]]; then
  echo '首次运行，正在安装前端锁定依赖。'
  (cd "$GILEAD_ROOT/frontend" && npm ci --ignore-scripts --no-audit --no-fund)
fi
if [[ "$SETUP_ONLY" == true ]]; then
  echo '前后端依赖已准备完成。'
  exit 0
fi
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    printf '端口 %s 已被占用，请调整端口后启动。\n' "$port" >&2
    exit 1
  fi
done
(cd "$GILEAD_ROOT/backend_v2" && .venv/bin/python ../deploy/gilead_poc/bootstrap_runtime.py)
backend_pid='';frontend_pid=''
cleanup() {
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
(
  cd "$GILEAD_ROOT/backend_v2"
  exec .venv/bin/python -m uvicorn xiaoying_quick.app:app --host 127.0.0.1 --port "$BACKEND_PORT"
) &
backend_pid=$!
(
  cd "$GILEAD_ROOT/frontend"
  export VITE_DEV_API_TARGET="http://127.0.0.1:$BACKEND_PORT"
  exec node_modules/.bin/vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) &
frontend_pid=$!
"$GILEAD_ROOT/backend_v2/.venv/bin/python" "$GILEAD_ROOT/deploy/gilead_poc/wait_ready.py" "$BACKEND_PORT" "$FRONTEND_PORT"
printf '吉利德 POC 前端 http://127.0.0.1:%s 后端 http://127.0.0.1:%s\n' "$FRONTEND_PORT" "$BACKEND_PORT"
printf '管理员账号见 backend_v2/.env 中的 XIAOYING_BOOTSTRAP_ADMIN_*。\n'
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done
cleanup
wait "$backend_pid"
