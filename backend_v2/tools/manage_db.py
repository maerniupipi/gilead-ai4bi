"""Apply or inspect control-database migrations using the same .env as the backend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from xiaoying_quick.bootstrap.settings import Settings
from xiaoying_quick.infrastructure.persistence.provision import inspect_application_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upgrade", "check", "status"))
    args = parser.parse_args()
    settings = Settings()
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    if args.action == "upgrade":
        command.upgrade(config, "head")
    elif args.action == "check":
        command.check(config)
    else:
        print(json.dumps(inspect_application_database(settings.database_url).to_record()))


if __name__ == "__main__":
    main()
