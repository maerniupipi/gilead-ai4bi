#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
release=${1:-/opt/gilead-ai4bi}
context=$PWD/context
test -x "$release/weed"
test -d "$release/application/backend_v2/src"
test -d "$release/platform/backend/app"
install -d -m 0700 "$context"
install -d "$context/venvs" "$context/platform"
sync_tree() {
    local from=$1 to=$2
    shift 2
    install -d "$to"
    rsync -a --delete --delete-excluded \
        --exclude='.git/' --exclude='__pycache__/' --exclude='*.pyc' \
        --exclude='.env' --exclude='.env.*' --exclude='*.bak*' --exclude='*~' \
        "$@" "$from/" "$to/"
}
sync_tree "$release/python" "$context/python"
for role in application platform; do
    sync_tree "$release/venvs/$role" "$context/venvs/$role"
done
sync_tree "$release/application" "$context/application" --exclude='*.sqlite*'
sync_tree "$release/platform/backend" "$context/platform/backend" --exclude='/data' --exclude='/logs'
ln -sfn /var/lib/gilead-ai4bi/platform "$context/platform/backend/data"
ln -sfn /var/log/gilead-platform "$context/platform/backend/logs"
sync_tree "$release/platform/frontend" "$context/platform/frontend"
sync_tree "$release/opensearch-3.10.0" "$context/search" --exclude='/config' --exclude='/logs' --exclude='/data'
install -m 0755 "$release/weed" "$context/weed"
install -m 0644 /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg "$context/pgdg.gpg"
