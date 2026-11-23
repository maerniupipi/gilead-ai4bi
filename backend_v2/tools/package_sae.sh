#!/usr/bin/env bash
# Build an Aliyun SAE Python ZIP: requirements.txt at the root, code under app/.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "${ROOT}/.." && pwd)"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/xiaoying-sae.XXXXXX")"
OUT="${1:-${ROOT}/dist/xiaoying-quick-sae.zip}"

cleanup() {
  rm -rf "${STAGE}"
}
trap cleanup EXIT

mkdir -p "${STAGE}/app" "$(dirname "${OUT}")"

cp "${ROOT}/deploy/sae/app/__init__.py" "${STAGE}/app/__init__.py"
cp "${ROOT}/deploy/sae/app/main.py" "${STAGE}/app/main.py"
cp "${ROOT}/deploy/sae/app/__main__.py" "${STAGE}/app/__main__.py"
cp -R "${ROOT}/src/xiaoying_quick" "${STAGE}/app/xiaoying_quick"
cp "${ROOT}/deploy/sae/requirements.txt" "${STAGE}/requirements.txt"
cp "${ROOT}/deploy/sae/start.sh" "${STAGE}/start.sh"
cp "${ROOT}/deploy/sae/alembic.ini" "${STAGE}/alembic.ini"
if [[ -f "${ROOT}/deploy/sae/app/runtime_defaults.py" ]]; then
  cp "${ROOT}/deploy/sae/app/runtime_defaults.py" "${STAGE}/app/runtime_defaults.py"
fi
if [[ -f "${ROOT}/deploy/sae/runtime.env" ]]; then
  cp "${ROOT}/deploy/sae/runtime.env" "${STAGE}/.env"
  cp "${ROOT}/deploy/sae/runtime.env" "${STAGE}/runtime.env"
  cp "${ROOT}/deploy/sae/runtime.env" "${STAGE}/app/.env"
fi
chmod +x "${STAGE}/start.sh"

if [[ -d "${REPO}/knowledge" ]]; then
  mkdir -p "${STAGE}/knowledge" "${STAGE}/app/knowledge"
  cp -R "${REPO}/knowledge/." "${STAGE}/knowledge/"
  cp -R "${REPO}/knowledge/." "${STAGE}/app/knowledge/"
  # ASCII copies survive Java unzip when Chinese names are mangled.
  for dest in "${STAGE}/knowledge" "${STAGE}/app/knowledge"; do
    mkdir -p "${dest}/seed-files/labs"
    cp "${REPO}/knowledge/项目知识文档/业务知识.md" "${dest}/seed-files/business.md"
    cp "${REPO}/knowledge/项目知识文档/实验室总索引.md" "${dest}/seed-files/lab-index.md"
    cp "${REPO}/knowledge/项目知识文档/labs/actual.md" "${dest}/seed-files/labs/actual.md"
    cp "${REPO}/knowledge/项目知识文档/labs/demand.md" "${dest}/seed-files/labs/demand.md"
    cp "${REPO}/knowledge/项目知识文档/labs/外部市场-简单.md" "${dest}/seed-files/labs/ext-simple.md"
    cp "${REPO}/knowledge/项目知识文档/labs/外部市场-复杂.md" "${dest}/seed-files/labs/ext-complex.md"
  done
fi

if [[ -f "${ROOT}/var/secrets.json" ]]; then
  mkdir -p "${STAGE}/var"
  cp "${ROOT}/var/secrets.json" "${STAGE}/var/secrets.json"
  if [[ -f "${ROOT}/var/master.key" ]]; then
    cp "${ROOT}/var/master.key" "${STAGE}/var/master.key"
  fi
fi

SQL_DIR="${ROOT}/dist/sae-sql"
if [[ -d "${SQL_DIR}" ]]; then
  mkdir -p "${STAGE}/sql"
  cp -R "${SQL_DIR}/." "${STAGE}/sql/"
fi

FRONTEND_DIST="${REPO}/frontend/dist"
if [[ -f "${FRONTEND_DIST}/index.html" ]]; then
  rm -rf "${STAGE}/app/www"
  cp -R "${FRONTEND_DIST}" "${STAGE}/app/www"
fi

find "${STAGE}" \( -name '__pycache__' -o -name '.DS_Store' \) -prune -exec rm -rf {} +
find "${STAGE}" -name '*.pyc' -delete

# Python zipfile sets the UTF-8 language encoding flag. macOS `zip` does not,
# so SAE's Java unzip mangles 项目知识文档 and the seeder finds nothing.
python3 "${ROOT}/tools/write_utf8_zip.py" "${STAGE}" "${OUT}"

printf 'wrote %s (%s)\n' "${OUT}" "$(wc -c < "${OUT}" | tr -d ' ') bytes"
printf 'SAE start command:\n'
printf '  python -m uvicorn app.main:app --host 0.0.0.0 --port 8080\n'
printf 'or:\n'
printf '  sh start.sh\n'
