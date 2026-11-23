"""Create isolated Gilead databases on the existing J&J Aliyun MySQL instance."""

from __future__ import annotations
import argparse, json, secrets, ssl
from pathlib import Path
from urllib.parse import urlsplit, unquote
import certifi, pymysql
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]


def read_env(path):
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def tls():
    return ssl.create_default_context(cafile=certifi.where())


def connect(path, timeout=120):
    e = read_env(path)
    return pymysql.connect(
        host=e["MYSQL_HOST"],
        port=int(e.get("MYSQL_PORT", 3306)),
        user=e["MYSQL_USER"],
        password=e["MYSQL_PASSWORD"],
        database=e["MYSQL_DATABASE"],
        charset="utf8mb4",
        ssl=tls() if e.get("MYSQL_SSL_MODE", "require") == "require" else None,
        connect_timeout=10,
        read_timeout=timeout,
        write_timeout=timeout,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--platform-env", required=True, type=Path)
    p.add_argument("--ssl-mode", choices=["require", "disable"], default="require")
    a = p.parse_args()
    e = read_env(a.platform_env)
    u = urlsplit(e["DATABASE_URL"])
    if not (u.hostname or "").endswith(".rds.aliyuncs.com"):
        raise SystemExit("Expected the configured Aliyun RDS MySQL instance")
    root = ROOT / "secrets"
    root.mkdir(exist_ok=True)
    root.chmod(0o700)
    marker = root / "mysql-provision.json"
    if marker.exists():
        prior = json.loads(marker.read_text())
        if prior["host"] != u.hostname:
            raise SystemExit("Host changed; refusing to reuse credentials")
        print("Existing project database credentials retained")
        return
    c = pymysql.connect(
        host=u.hostname,
        port=u.port or 3306,
        user=unquote(u.username or ""),
        password=unquote(u.password or ""),
        charset="utf8mb4",
        ssl=tls() if a.ssl_mode == "require" else None,
        connect_timeout=10,
        autocommit=True,
    )
    record = {
        "host": u.hostname,
        "business_database": "gilead_poc",
        "control_database": "gilead_agent_loop",
        "ssl_mode": a.ssl_mode,
    }
    pending = root / "mysql-provision-pending.json"
    recovering = pending.exists()
    if recovering:
        saved = json.loads(pending.read_text())
        if saved["host"] != u.hostname:
            raise SystemExit("Pending provision belongs to a different host")
        credentials = saved["credentials"]
    else:
        credentials = {
            name: secrets.token_urlsafe(30)
            for name in ["gilead_poc_owner", "gilead_lab_reader", "gilead_react_app"]
        }
    with c:
        with c.cursor() as s:
            s.execute("SHOW STATUS LIKE 'Ssl_cipher'")
            cipher = s.fetchone()[1]
            if a.ssl_mode == "require":
                assert cipher, "TLS required"
            s.execute(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('gilead_poc','gilead_agent_loop')"
            )
            if s.fetchone() and not recovering:
                raise SystemExit(
                    "Project database already exists without local provisioning record"
                )
            s.execute(
                "SELECT count(*) FROM mysql.user WHERE user IN ('gilead_poc_owner','gilead_lab_reader','gilead_react_app')"
            )
            if s.fetchone()[0] and not recovering:
                raise SystemExit(
                    "Project account already exists; inspect before creating"
                )
            # Persist the newly generated project-only passwords before remote mutations.
            pending.write_text(json.dumps({**record, "credentials": credentials}))
            pending.chmod(0o600)
            for db in ["gilead_poc", "gilead_agent_loop"]:
                s.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            for name, password in credentials.items():
                required = "REQUIRE SSL" if a.ssl_mode == "require" else ""
                s.execute(
                    "CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s "
                    + required
                    + " WITH MAX_USER_CONNECTIONS %s",
                    (name, "%", password,
                     3 if name == "gilead_lab_reader" else 12 if name == "gilead_react_app" else 5),
                )
            s.execute(
                "GRANT ALL PRIVILEGES ON `gilead_poc`.* TO 'gilead_poc_owner'@'%'"
            )
            s.execute(
                "GRANT ALL PRIVILEGES ON `gilead_agent_loop`.* TO 'gilead_react_app'@'%'"
            )
            s.execute("USE `gilead_poc`")
            for statement in (
                Path(__file__).with_name("001_schema.sql").read_text().split(";")
            ):
                if statement.strip():
                    s.execute(statement)
            for table in [
                "sales_target_ai4bi",
                "v_ai4bi_ddi_sales",
                "prod_master",
                "teri_hierachy",
                "ddi_coverage",
                "data_range_config",
            ]:
                s.execute(
                    f"GRANT SELECT ON `gilead_poc`.`{table}` TO 'gilead_lab_reader'@'%'"
                )
    for name, file in [
        ("gilead_poc_owner", "business-owner.env"),
        ("gilead_lab_reader", "lab-reader.env"),
    ]:
        path = root / file
        path.write_text(
            f"MYSQL_HOST={u.hostname}\nMYSQL_PORT={u.port or 3306}\nMYSQL_DATABASE=gilead_poc\nMYSQL_USER={name}\nMYSQL_PASSWORD={credentials[name]}\nMYSQL_SSL_MODE={a.ssl_mode}\n"
        )
        path.chmod(0o600)
    control = {
        "database": "gilead_agent_loop",
        "username": "gilead_react_app",
        "password": credentials["gilead_react_app"],
        "admin_username": "admin",
        "admin_password": secrets.token_urlsafe(20),
        "auth_secret": secrets.token_urlsafe(40),
        "sql_secret": secrets.token_urlsafe(40),
        "provision_token": secrets.token_urlsafe(40),
    }
    path = root / "control-plane.json"
    path.write_text(json.dumps(control, indent=2))
    path.chmod(0o600)
    query = (
        {
            "charset": "utf8mb4",
            "ssl_ca": certifi.where(),
            "ssl_verify_cert": "true",
            "ssl_verify_identity": "true",
        }
        if a.ssl_mode == "require"
        else {"charset": "utf8mb4", "ssl_disabled": "true"}
    )
    url = URL.create(
        "mysql+pymysql",
        username=control["username"],
        password=control["password"],
        host=u.hostname,
        port=u.port or 3306,
        database=control["database"],
        query=query,
    )
    values = {
        "XIAOYING_ENVIRONMENT": "development",
        "XIAOYING_DATABASE_URL": url.render_as_string(hide_password=False),
        "XIAOYING_DB_AUTO_CREATE": "false",
        "XIAOYING_AUTH_HMAC_SECRET": control["auth_secret"],
        "XIAOYING_SQL_APPROVAL_HMAC_SECRET": control["sql_secret"],
        "XIAOYING_AUTH_ISSUER": "gilead-poc",
        "XIAOYING_AUTH_TOKEN_TTL_SECONDS": "28800",
        "XIAOYING_PROVISION_TOKEN": control["provision_token"],
        "XIAOYING_BOOTSTRAP_ADMIN_USERNAME": "admin",
        "XIAOYING_BOOTSTRAP_ADMIN_PASSWORD": control["admin_password"],
        "XIAOYING_KNOWLEDGE_ROOT": "../knowledge_gilead",
        "XIAOYING_SECRET_STORE_PATH": "./var/gilead-secrets.json",
        "XIAOYING_SECRET_KEY_PATH": "./var/gilead-master.key",
        "XIAOYING_ALLOW_SQLITE_DATA_SOURCES": "false",
        "XIAOYING_DATA_SOURCE_ALLOWED_HOSTS": u.hostname,
        "XIAOYING_DATABASE_POOL_SIZE": "3",
        "XIAOYING_DATABASE_MAX_OVERFLOW": "1",
        "XIAOYING_JOB_MAX_WORKERS": "2",
        "XIAOYING_CORS_ALLOWED_ORIGINS": "http://127.0.0.1:15173,http://localhost:15173",
        "XIAOYING_LAB_FALLBACK": "off",
        "XIAOYING_LAB_FALLBACK_ON_ERROR": "false",
    }
    env = ROOT / "backend_v2/.env"
    env.write_text("\n".join(k + "=" + str(v) for k, v in values.items()) + "\n")
    env.chmod(0o600)
    marker.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    marker.chmod(0o600)
    pending.unlink()
    print(
        "Created gilead_poc + gilead_agent_loop on existing Aliyun RDS; credentials saved privately"
    )


if __name__ == "__main__":
    main()
