# 吉利德 AI4BI Docker 运维

生产主机为 `10.3.97.198`，Compose 项目名为 `gilead`，服务器目录为 `/opt/gilead-compose`。应用入口是 [80 端口](http://10.3.97.198/)，平台入口是 [8080 端口](http://10.3.97.198:8080/)。分享页使用 3840，S3 签名下载使用 9000。

## 日常操作

以 `ubuntu` 登录服务器后进入管理目录。

```sh
sudo -i
cd /opt/gilead-compose
docker compose ps
docker compose logs --tail=100 -f application platform
```

重启单个应用可运行 `docker compose restart application` 或 `docker compose restart platform`。运行 `docker compose up -d --wait` 会按依赖顺序启动整套服务并检查健康状态。Docker 已设为开机启动，七个服务的重启策略均为 `unless-stopped`。

| Compose 服务 | 用途 | 数据或配置 |
| --- | --- | --- |
| `nginx` | 应用、平台、分享和 S3 入口，以及本机 OpenSearch 认证代理 | `/etc/nginx`，访问日志在 `/var/log/nginx` |
| `application` | 应用后端和应用前端 | `gilead_app` 库，文件在 `/var/lib/gilead-ai4bi/application` |
| `platform` | 平台 API 和后台任务进程 | `gilead_app` 库，文件在 `/var/lib/gilead-ai4bi/platform`，日志在 `/var/log/gilead-platform` |
| `postgres` | PostgreSQL 16.16，承载 `gilead_source` 和 `gilead_app` | `/var/lib/postgresql/16/main` |
| `redis` | Redis 6.0.16 | `/var/lib/redis`，配置在 `/etc/redis` |
| `s3` | SeaweedFS 4.54，桶名为 `gilead-files` | 对象在 `/var/lib/gilead-ai4bi/objects`，元数据在 `gilead_app.object_store` |
| `opensearch` | OpenSearch 3.10.0，承载 DDI 向量和知识索引 | `/var/lib/gilead-ai4bi/search`，日志在 `/var/log/gilead-search` |

本次沿用单机 Linux 的 `host` 网络，应用配置中的本机地址、SSH 隧道和 S3 签名地址可继续使用。数据目录通过绑定挂载持久化。数据库可在容器里直接管理。

```sh
docker compose exec -u postgres postgres psql -d gilead_source
docker compose exec -u postgres postgres psql -d gilead_app
```

## 更新配置与程序

应用端和平台端的配置源分别是 `/etc/gilead-ai4bi/application.env` 和 `/etc/gilead-ai4bi/platform.env`。修改后在管理目录执行以下命令，刷新供 Compose 读取的配置并重建受影响的容器。配置文件仅对服务器管理员开放。

```sh
./refresh-env.py
docker compose up -d --wait
```

版本号记录在管理目录的 `.env`。发布新程序时，将审核过的 Linux 发布文件更新到 `/opt/gilead-ai4bi`，包括应用代码、已构建的前端和相应的 Python 依赖。运行 `./prepare-release.sh` 准备镜像构建目录，给 `.env` 中的 `RELEASE_TAG` 设置新的版本，再运行以下命令。旧标签可用于回退到仍兼容当前数据库结构的镜像版本。

```sh
docker compose build
docker compose up -d --no-build --wait
```

单独发布问数应用时，可在 `.env` 中设置 `APPLICATION_RELEASE_TAG` 和 `NGINX_RELEASE_TAG`，执行 `docker compose build application nginx` 和 `docker compose up -d --no-deps --wait application nginx`。两个变量均可使用已有镜像标签回退。全栈统一发版时，将两个服务标签同步到新的 `RELEASE_TAG`，或清除这两个覆盖值以继承统一版本。

## 本次切换与恢复

2026 年 11 月 21 日北京时间 21:58，正式地址已由 Docker 提供服务。两个数据库的逻辑备份均已在隔离容器中实际还原。切换前后已逐行比较 6 张数据源表，合计 233,770 行，并比对 17 张应用和平台表、两个业务搜索索引及 S3 对象清单。已从内网浏览器登录两端，并通过 SSH 隧道访问两个数据库、Redis 和带认证的 OpenSearch。平台已验证业务 SQL、向量检索和 S3 签名下载。应用容器已验证与模型端点的 TLS 连接。

本次备份在服务器 `/var/backups/gilead-docker/20261121T134354Z/`，仅限服务器管理员访问。目录内含两个数据库的逻辑备份、角色定义、停服时的数据与配置归档、七个 Docker 镜像归档及 SHA-256 校验文件。镜像归档可以通过 `docker image load -i images.tar.gz` 导入。

原生服务已停用。需要退回原生部署时，在 `/opt/gilead-compose` 执行 `./rollback-to-native.sh`。脚本会短暂停服，先关闭项目容器，再用原服务接管当前数据目录并检查两个入口。恢复到历史备份是另一项操作，需要选择相应的备份时间点。
