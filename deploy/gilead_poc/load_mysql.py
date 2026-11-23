"""Load deterministic mock rows with atomic, resumable project-only batches."""

from __future__ import annotations

import argparse
import base64
import json
import struct
import zlib
from pathlib import Path

from provision_mysql import connect
from seed import SEED_VERSION, expected_counts, rows

HERE = Path(__file__).resolve().parent
BATCH_SIZE = 1000


def encode_batch(batch):
    raw = json.dumps(
        batch, ensure_ascii=False, default=str, separators=(",", ":")
    ).encode()
    if len(raw) > 2_000_000:
        raise SystemExit("Seed batch exceeds bounded decoded payload")
    return base64.b64encode(struct.pack("<I", len(raw)) + zlib.compress(raw)).decode(
        "ascii"
    )


def json_relation(columns):
    definitions = []
    for index, column in enumerate(columns):
        datatype = (
            column["type"].replace("numeric", "decimal").replace("integer", "int")
        )
        if column["name"] == "max_ddi_version":
            datatype = "varchar(32)"
        definitions.append(
            f"`{column['name']}` {datatype} PATH '$[{index}]' ERROR ON EMPTY ERROR ON ERROR"
        )
    return (
        "JSON_TABLE(CONVERT(UNCOMPRESS(FROM_BASE64(%s)) USING utf8mb4), '$[*]' COLUMNS ("
        + ",".join(definitions)
        + ")) AS seed_batch"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument(
        "--transport", choices=["compressed-json", "values"], default="compressed-json"
    )
    args = parser.parse_args()
    schema = json.loads((HERE / "schema.json").read_text())
    report = {}
    with connect(args.env, timeout=300) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE(), CURRENT_USER()")
            database, user = cursor.fetchone()
            if database != "gilead_poc" or user.split("@")[0] != "gilead_poc_owner":
                raise SystemExit("Refusing wrong database/account")
            cursor.execute("SELECT GET_LOCK('gilead_poc_seed',3)")
            if cursor.fetchone()[0] != 1:
                raise SystemExit("Another loader holds the project lock")
            cursor.execute("SHOW TABLES")
            existing = {row[0] for row in cursor.fetchall()}
            if existing - set(schema) - {"_poc_seed_runs"}:
                raise SystemExit("Unexpected tables in business database")
            if existing and "_poc_seed_runs" not in existing:
                raise SystemExit("Refusing unmarked existing database")
            for statement in (HERE / "001_schema.sql").read_text().split(";"):
                if statement.strip():
                    cursor.execute(statement)
            cursor.execute("SHOW COLUMNS FROM _poc_seed_runs LIKE 'completed'")
            if not cursor.fetchone():
                # Upgrade only our own seed ledger; the six business schemas stay exact.
                cursor.execute(
                    "ALTER TABLE _poc_seed_runs ADD COLUMN completed BOOLEAN NOT NULL DEFAULT TRUE"
                )
            connection.commit()
            for table in [
                "prod_master",
                "ddi_coverage",
                "data_range_config",
                "v_ai4bi_ddi_sales",
                "sales_target_ai4bi",
                "teri_hierachy",
            ]:
                target = expected_counts()[table]
                cursor.execute(
                    "SELECT seed_version, rows_loaded, completed FROM _poc_seed_runs WHERE table_name=%s",
                    (table,),
                )
                prior = cursor.fetchone()
                cursor.execute(f"SELECT count(*) FROM `{table}`")
                actual = cursor.fetchone()[0]
                loaded = 0
                if prior:
                    if prior[0] != SEED_VERSION or actual != prior[1]:
                        raise SystemExit(
                            "Seed version/count mismatch; inspect without overwriting"
                        )
                    loaded = prior[1]
                    if prior[2]:
                        if loaded != target:
                            raise SystemExit("Completed seed has unexpected row count")
                        report[table] = {"rows": loaded, "action": "already_loaded"}
                        print(table, loaded, "already_loaded", flush=True)
                        continue
                elif actual:
                    raise SystemExit("Refusing nonempty unmarked table " + table)
                names = [column["name"] for column in schema[table]]
                query = (
                    f"INSERT INTO `{table}` ("
                    + ",".join("`" + n + "`" for n in names)
                    + ") VALUES ("
                    + ",".join(["%s"] * len(names))
                    + ")"
                )
                compressed_query = (
                    f"INSERT INTO `{table}` ("
                    + ",".join("`" + n + "`" for n in names)
                    + ") SELECT "
                    + ",".join("`" + n + "`" for n in names)
                    + " FROM "
                    + json_relation(schema[table])
                )
                batch = []

                def flush():
                    nonlocal loaded, batch
                    if args.transport == "compressed-json":
                        cursor.execute(compressed_query, (encode_batch(batch),))
                        if cursor.rowcount != len(batch):
                            raise SystemExit("Decoded seed row count mismatch")
                        cursor.execute("SHOW COUNT(*) WARNINGS")
                        if cursor.fetchone()[0]:
                            raise SystemExit(
                                "Seed conversion produced warnings; refusing commit"
                            )
                    else:
                        cursor.executemany(query, batch)
                    loaded += len(batch)
                    cursor.execute(
                        "INSERT INTO _poc_seed_runs(table_name,seed_version,rows_loaded,completed) VALUES (%s,%s,%s,FALSE) ON DUPLICATE KEY UPDATE rows_loaded=VALUES(rows_loaded),completed=FALSE",
                        (table, SEED_VERSION, loaded),
                    )
                    connection.commit()
                    batch = []
                    if loaded % 10000 == 0:
                        print(table, loaded, "/", target, flush=True)

                for number, row in enumerate(rows(table), 1):
                    if number <= loaded:
                        continue
                    if set(row) != set(names):
                        raise SystemExit("Unexpected generated columns")
                    batch.append(tuple(row[name] for name in names))
                    if len(batch) >= BATCH_SIZE:
                        flush()
                if batch:
                    flush()
                if loaded != target:
                    raise SystemExit("Generated row count mismatch")
                cursor.execute(
                    "UPDATE _poc_seed_runs SET completed=TRUE,completed_at=CURRENT_TIMESTAMP WHERE table_name=%s",
                    (table,),
                )
                connection.commit()
                report[table] = {"rows": loaded, "action": "loaded"}
                print(table, loaded, "complete", flush=True)
            cursor.execute("SELECT RELEASE_LOCK('gilead_poc_seed')")
    (HERE / "load-report.json").write_text(
        json.dumps(
            {
                "seed_version": SEED_VERSION,
                "database": "gilead_poc",
                "transport": args.transport,
                "tables": report,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    import time
    import pymysql

    for attempt in range(1, 13):
        try:
            main()
            break
        except pymysql.OperationalError as exc:
            if exc.args[0] not in {2003, 2006, 2013} or attempt == 12:
                raise
            print(
                "Connection interrupted; resume from committed ledger. Attempt",
                attempt,
                flush=True,
            )
            time.sleep(2)
