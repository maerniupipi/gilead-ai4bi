#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ $(id -u) != 0 ]]; then echo "Run on the deployment host as root." >&2; exit 1; fi
if [[ ! -f .docker-owns-state ]]; then echo "The Docker ownership marker is absent." >&2; exit 1; fi

docker compose -p gilead stop nginx
docker compose -p gilead stop application platform
docker compose -p gilead down --timeout 90
if [[ -n $(docker ps -q --filter 'label=com.docker.compose.project=gilead') ]]; then
    echo "Project containers are still running." >&2
    exit 1
fi
rm -- .docker-owns-state
systemctl daemon-reload
systemctl enable postgresql.service redis-server.service gilead-opensearch.service \
    gilead-s3.service gilead-platform.service gilead-application.service nginx.service
systemctl start postgresql.service postgresql@16-main.service redis-server.service gilead-opensearch.service
systemctl start gilead-s3.service gilead-platform.service gilead-application.service nginx.service
for _ in $(seq 1 90); do
    if curl -fsS --max-time 3 http://127.0.0.1/api/v2/health/ready >/dev/null 2>&1 \
        && curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
        echo "Native services are serving both endpoints on the current data."
        exit 0
    fi
    sleep 2
done
echo "Check native service status and journals." >&2
exit 1
