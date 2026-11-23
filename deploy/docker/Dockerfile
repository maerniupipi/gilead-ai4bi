FROM public.ecr.aws/docker/library/ubuntu:22.04@sha256:f64b2ffc2f10ab8f8505aa56b2664bd846cbb9df87c7e2532e30f7667021c0e6 AS base
ENV LANG=C.UTF-8
ARG UBUNTU_MIRROR=http://cn.archive.ubuntu.com/ubuntu
RUN printf 'deb %s jammy main universe\ndeb %s jammy-updates main universe\ndeb %s jammy-security main universe\n' \
        "$UBUNTU_MIRROR" "$UBUNTU_MIRROR" "$UBUNTU_MIRROR" > /etc/apt/sources.list \
    && printf 'Acquire::Retries "3";\n' > /etc/apt/apt.conf.d/80gilead-retries \
    && apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/*

FROM base AS postgres
ARG PG_VERSION=16.16-1.pgdg22.04+1
COPY pgdg.gpg /usr/share/keyrings/gilead-pgdg.gpg
RUN groupadd --gid 122 postgres && useradd --uid 116 --gid 122 --home-dir /var/lib/postgresql --no-create-home postgres \
    && echo 'deb [signed-by=/usr/share/keyrings/gilead-pgdg.gpg] https://apt.postgresql.org/pub/repos/apt jammy-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends postgresql-common \
    && printf '\ncreate_main_cluster = false\n' >> /etc/postgresql-common/createcluster.conf \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "postgresql-16=$PG_VERSION" "postgresql-client-16=$PG_VERSION" \
    && rm -rf /var/lib/apt/lists/* /etc/ssl/private/ssl-cert-snakeoil.key
RUN chgrp 121 /etc/ssl/private && chmod 0710 /etc/ssl/private
ENV PATH=/usr/lib/postgresql/16/bin:$PATH
USER 116:122
CMD ["postgres","-D","/var/lib/postgresql/16/main","-c","config_file=/etc/postgresql/16/main/postgresql.conf"]

FROM base AS redis
ARG REDIS_VERSION=5:6.0.16-1ubuntu1.2
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "redis-server=$REDIS_VERSION" "redis-tools=$REDIS_VERSION" \
    && rm -rf /var/lib/apt/lists/*
RUN chown -R 115:120 /var/log/redis
USER 115:120
CMD ["redis-server","/etc/redis/redis.conf","--daemonize","no","--supervised","no","--pidfile","/tmp/redis.pid","--logfile",""]

FROM base AS nginx
ARG NGINX_VERSION=1.18.0-6ubuntu14.24
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "nginx-core=$NGINX_VERSION" \
    && rm -rf /var/lib/apt/lists/*
COPY platform/frontend /opt/gilead-ai4bi/platform/frontend
CMD ["nginx","-g","daemon off;"]

FROM base AS s3
COPY weed /opt/gilead-ai4bi/weed
WORKDIR /etc/gilead-s3
USER 996:996
ENTRYPOINT ["/opt/gilead-ai4bi/weed"]

FROM base AS opensearch
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libgomp1 libstdc++6 procps \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 995 gilead-search && useradd --uid 995 --gid 995 --create-home gilead-search
WORKDIR /opt/gilead-ai4bi/opensearch-3.10.0
COPY search/ ./
ENV OPENSEARCH_JAVA_OPTS="-Xms1g -Xmx1g"
USER 995:995
CMD ["./bin/opensearch"]

FROM base AS python-runtime
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        fonts-dejavu-core libbz2-1.0 libexpat1 libffi8 libgomp1 libgssapi-krb5-2 \
        libicu70 liblzma5 libpq5 libreadline8 libsqlite3-0 libstdc++6 libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*
COPY python /opt/gilead-ai4bi/python
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

FROM python-runtime AS application
RUN groupadd --gid 998 gilead-app && useradd --uid 998 --gid 998 --create-home gilead-app
COPY venvs/application /opt/gilead-ai4bi/venvs/application
COPY application /opt/gilead-ai4bi/application
WORKDIR /opt/gilead-ai4bi/application/backend_v2
ENV PATH=/opt/gilead-ai4bi/venvs/application/bin:$PATH PYTHONPATH=/opt/gilead-ai4bi/application/backend_v2/src
USER 998:998
CMD ["sh","-ec","python tools/manage_db.py upgrade && exec python -m uvicorn xiaoying_quick.app:app --host 127.0.0.1 --port 9999"]

FROM python-runtime AS platform
RUN groupadd --gid 997 gilead-platform && useradd --uid 997 --gid 997 --create-home gilead-platform
COPY venvs/platform /opt/gilead-ai4bi/venvs/platform
COPY platform/backend /opt/gilead-ai4bi/platform/backend
WORKDIR /opt/gilead-ai4bi/platform/backend
ENV PATH=/opt/gilead-ai4bi/venvs/platform/bin:$PATH
USER 997:997
CMD ["python","-m","app.runtime"]
