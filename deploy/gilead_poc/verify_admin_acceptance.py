"""Reconcile actual admin conversation evidence with the synthetic warehouse."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from boost_volume_sql import connect


def close(actual, expected):
    assert abs(Decimal(str(actual)) - Decimal(str(expected))) < Decimal("0.01"), (actual, expected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()
    records = args.records
    cases = ["ask-1-final", "ask-2-complete", "ask-3", "ask-4-final", "ask-5", "ask-6-complete"]
    verified = []

    def read(name, suffix="trace"):
        return json.loads((records / f"{name}-{suffix}.json").read_text())

    def queries(name):
        trace = read(name)
        assert trace["run"]["status"] == "completed"
        assert any(
            e["type"] == "agent.done" and e["payload"].get("answer") for e in trace["events"]
        )
        values = [
            e["payload"]["preview"]
            for e in trace["events"]
            if e["type"] == "tool.result"
            and e["payload"].get("name") == "query_db"
            and e["payload"].get("ok")
        ]
        assert values and all(
            q.get("lab_provider") == "bootcamp" and q.get("mock_enabled") is False for q in values
        )
        return values

    def result(name, key, count=None):
        found = [
            q
            for q in queries(name)
            if key in q.get("columns", []) and (count is None or len(q.get("rows", [])) == count)
        ]
        assert found, name
        q = found[-1]
        return [dict(zip(q["columns"], row)) for row in q["rows"]]

    with connect() as c, c.cursor() as q:
        q.execute("SELECT DATABASE(),CURRENT_USER()")
        database, actor = q.fetchone()
        assert database == "gilead_poc" and actor.startswith("gilead_poc_owner@")
        q.execute(
            "SELECT SUM(sales_amt),SUM(target_amt),SUM(sales_qty) FROM sales_target_ai4bi "
            "WHERE data_type='Monthly' AND `year_month`=202609"
        )
        september = q.fetchone()
        close(result(cases[0], "sales_cny", 1)[0]["sales_cny"], september[0])
        q.execute(
            "SELECT SUM(sales_amt),SUM(target_amt),SUM(sales_qty) FROM sales_target_ai4bi "
            "WHERE data_type='Monthly' AND `year_month` BETWEEN 202601 AND 202609"
        )
        ytd = q.fetchone()
        report = read(cases[1], "report")
        assert report["source"]["truncated"] is False and len(report["rows"]) == 864
        for role, expected in zip(("amount", "target", "qty"), ytd):
            close(sum(Decimal(str(r[report["metrics"][role]])) for r in report["rows"]), expected)
        q.execute(
            "SELECT SUM(sales_amt),SUM(target_amt) FROM sales_target_ai4bi WHERE "
            "data_type='Monthly' AND `year_month`=202608"
        )
        august = q.fetchone()
        answer = result(cases[2], "at_rate", 1)[0]
        close(answer["sales_cny"], august[0])
        close(answer["target_amt"], august[1])
        close(Decimal(answer["at_rate"]) * 100, august[0] / august[1] * 100)
        q.execute(
            "SELECT SUM(sales_amt),SUM(target_amt) FROM sales_target_ai4bi WHERE "
            "data_type='Monthly' AND `year_month`=202609 AND region='华南' AND "
            "brand_name_cn='模拟品牌03'"
        )
        brand = q.fetchone()
        answer = result(cases[3], "at_rate", 1)[0]
        close(answer["sales_cny"], brand[0])
        close(answer["target_amt"], brand[1])
        q.execute(
            "SELECT province_name_cn,SUM(sales_amt) AS amount FROM sales_target_ai4bi WHERE "
            "data_type='Monthly' AND `year_month`=202608 GROUP BY province_name_cn ORDER BY "
            "amount DESC LIMIT 10"
        )
        expected = q.fetchall()
        actual = result(cases[4], "province_name_cn", 10)
        assert [r["province_name_cn"] for r in actual] == [r[0] for r in expected]
        for a, e in zip(actual, expected):
            close(a["sales_cny"], e[1])
        q.execute(
            "SELECT city_name_cn,SUM(sales_amt) FROM sales_target_ai4bi WHERE "
            "data_type='Monthly' AND `year_month`=202609 AND city_name_cn "
            "IN('广州','成都','武汉') GROUP BY city_name_cn"
        )
        expected = dict(q.fetchall())
        actual = result(cases[5], "sales_cny", 3)
        city_key = "city_name_cn" if "city_name_cn" in actual[0] else "city"
        assert {r[city_key] for r in actual} == set(expected)
        for row in actual:
            close(row["sales_cny"], expected[row[city_key]])
        for name in cases:
            trace = read(name)
            verified.append(
                {
                    "case": name,
                    "question": trace["run"]["question"],
                    "run_id": trace["run"]["id"],
                    "status": "passed",
                }
            )

        insight = read("insight-gap-refined", "report")
        for role, expected in zip(("amount", "target"), september):
            close(sum(Decimal(str(r[insight["metrics"][role]])) for r in insight["rows"]), expected)
        original = read("insight-gap-complete")
        lab_questions = [
            e["payload"].get("arguments", {}).get("question", "")
            for e in original["events"]
            if e["type"] == "tool.call" and e["payload"].get("name") == "ask_lab"
        ]
        assert any("华南" in question and "渠道" in question for question in lab_questions)
        assert any("华南" in question and "品牌" in question for question in lab_questions)

        ddi = read("insight-ddi-complete", "report")
        assert (
            read("insight-ddi-complete")["run"]["insight_meta"]["skill_pack_id"] == "ddi_analysis"
        )
        assert ddi["source"]["truncated"] is False and len(ddi["rows"]) == 864
        for role, expected in zip(("amount", "target", "qty"), ytd):
            close(sum(Decimal(str(r[ddi["metrics"][role]])) for r in ddi["rows"]), expected)
        for month, role in [(202509, "prior"), (202608, "previous")]:
            q.execute(
                "SELECT SUM(sales_amt) FROM sales_target_ai4bi WHERE data_type='Monthly' "
                "AND `year_month`=%s",
                (month,),
            )
            expected = q.fetchone()[0]
            actual = sum(
                Decimal(str(r[ddi["metrics"][role]]))
                for r in ddi["rows"]
                if str(r[ddi["date_field"]]) == "202609"
            )
            close(actual, expected)

        fields = read("ddi-followup-fields", "report")
        channel = read("ddi-followup-channel", "report")
        reviewed = read("ddi-findings-reviewed", "report")
        assert fields["id"] == channel["id"] == reviewed["id"] == ddi["id"]
        assert [fields["revision"], channel["revision"], reviewed["revision"]] == [2, 3, 5]
        assert all(
            r["filters"].get("region") == "华南" and not r["source"]["truncated"]
            for r in [fields, channel, reviewed]
        )
        assert {"region", "brand_name_cn", "terminal_channel_latest"}.issubset(
            fields["filter_fields"]
        )
        assert (
            "province_name_cn" in fields["visible_columns"]
            and "_share" in fields["visible_columns"]
        )
        q.execute(
            "SELECT SUM(sales_amt),SUM(target_amt) FROM sales_target_ai4bi "
            "WHERE data_type='Monthly' AND `year_month`=202609 AND region='华南'"
        )
        south = q.fetchone()
        for report in [channel, reviewed]:
            for role, expected in zip(("amount", "target"), south):
                close(
                    sum(Decimal(str(row[report["metrics"][role]])) for row in report["rows"]),
                    expected,
                )
        reused = read("insight-skill-reuse-reviewed", "report")
        assert reused["id"] == read("insight-skill-reuse", "report")["id"]
        for role, expected in zip(("amount", "target"), august):
            close(
                sum(Decimal(str(row[reused["metrics"][role]])) for row in reused["rows"]), expected
            )

    output = {
        "recommendations": verified,
        "insight_drilldown": "passed",
        "ddi_skill_and_complete_data": "passed",
        "ddi_followups_and_narrative_review": "passed",
        "saved_skill_reuse_with_new_month": "passed",
        "monthly_totals_cny": {
            "202609": str(september[0]),
            "202608": str(august[0]),
            "2026_ytd": str(ytd[0]),
        },
    }
    (records / "numerical-results.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2)
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
