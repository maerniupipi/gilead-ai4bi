"""Offline seed contract and independent KPI reference totals."""

from __future__ import annotations
import hashlib, json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from seed import SEED_VERSION, AS_OF, LAST_CLOSED_MONTH, rows, expected_counts

HERE = Path(__file__).resolve().parent


def main():
    schema = json.loads((HERE / "schema.json").read_text())
    counts = {}
    totals = defaultdict(lambda: [Decimal(0)] * 6)
    for table, cols in schema.items():
        names = {c["name"] for c in cols}
        count = 0
        for row in rows(table):
            assert set(row) == names, (table, names - set(row), set(row) - names)
            assert all(row[c["name"]] is not None for c in cols if not c["nullable"])
            count += 1
            if table == "sales_target_ai4bi":
                value = totals[(row["data_type"], row["year_month"])]
                for i, k in enumerate(
                    [
                        "sales_qty",
                        "sales_amt",
                        "sales_amt_asp",
                        "target_qty",
                        "target_amt",
                        "target_amt_asp",
                    ]
                ):
                    value[i] += row[k]
        assert count == expected_counts()[table], (table, count)
        counts[table] = count

    def period(start, end, kind="Monthly"):
        result = [Decimal(0)] * 6
        for (k, ym), value in totals.items():
            if k == kind and start <= ym <= end:
                result = [a + b for a, b in zip(result, value)]
        return result

    cases = []
    for name, cur, prev in [
        ("month_yoy", (202608, 202608), (202508, 202508)),
        ("qtd_yoy", (202607, 202608), (202507, 202508)),
        ("ytd_yoy", (202601, 202608), (202501, 202508)),
        ("last_complete_quarter_qoq", (202604, 202606), (202601, 202603)),
    ]:
        c, p = period(*cur), period(*prev)
        cases.append(
            {
                "name": name,
                "current_months": list(cur),
                "baseline_months": list(prev),
                "current_totals": list(map(str, c)),
                "baseline_totals": list(map(str, p)),
                "quantity_growth": str((c[0] - p[0]) / p[0]) if p[0] else None,
                "cny_growth": str((c[1] - p[1]) / p[1]) if p[1] else None,
            }
        )
    manifest = {
        "seed_version": SEED_VERSION,
        "synthetic": True,
        "as_of": str(AS_OF),
        "last_closed_month": LAST_CLOSED_MONTH,
        "table_counts": counts,
        "total_rows": sum(counts.values()),
        "schema_sha256": hashlib.sha256(
            (HERE / "schema.json").read_bytes()
        ).hexdigest(),
        "offline_contract": "passed",
        "golden_cases": cases,
        "notes": [
            "所有业务数据为合成模拟数据",
            "Monthly截至202608，Daily截至20260903",
            "历史Daily与Monthly不可混加",
            "未来层级快照不代表当前权限",
            "brand_code非唯一，不可直接按品牌关联产品明细",
        ],
    }
    (HERE / "seed-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in ["table_counts", "total_rows", "offline_contract"]
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
