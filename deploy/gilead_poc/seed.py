"""Reproducible synthetic business data. No Gilead or J&J records are copied."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

SEED_VERSION = "gilead-poc-v1-20261022"
AS_OF = date(2026, 9, 3)
LAST_CLOSED_MONTH = 202608
HCO_COUNT = 120
CENT = Decimal("0.01")
REGIONS = ["华北", "华东", "华南", "华中", "西南", "西北"]
GEO = [
    ("北京", "北京"),
    ("天津", "天津"),
    ("上海", "上海"),
    ("江苏", "南京"),
    ("广东", "广州"),
    ("福建", "福州"),
    ("湖北", "武汉"),
    ("湖南", "长沙"),
    ("四川", "成都"),
    ("重庆", "重庆"),
    ("陕西", "西安"),
    ("甘肃", "兰州"),
]


def months(start=202401, end=202609):
    y, m = divmod(start, 100)
    while y * 100 + m <= end:
        yield y * 100 + m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def org(h: int, ym: int):
    region = (h - 1) // 20
    # Five HCOs change historical ownership in 2026; permission-month attribution
    # must not be confused with the historical business-month attribution.
    if h <= 5 and ym >= 202601:
        region = 2
    return {
        "region": REGIONS[region],
        "ts": f"TS{h:03d}",
        "sam": f"ASM{region + 1:02d}",
        "rd": f"RSM{region + 1:02d}",
        "sd": "SD01",
    }


def hco(h: int):
    province, city = GEO[((h - 1) // 10) % 12]
    return {
        "hco_code": f"MOCKHCO{h:04d}",
        "hco_name": f"模拟医疗机构{h:03d}",
        "province_code": f"P{((h - 1) // 10) % 12 + 1:02d}",
        "province_name_cn": province,
        "city_code": f"C{((h - 1) // 10) % 12 + 1:02d}",
        "city_name_cn": city,
        "tier": f"T{h % 3 + 1}",
    }


def product_rows():
    for p in range(1, 17):
        b = p if p <= 13 else p - 13
        ta = (b - 1) % 6 + 1
        yield {
            "prod_code": f"MOCKPROD{p:03d}",
            "prod_code_codi": f"MOCKCODI{p:03d}",
            "prod_name_cn": f"模拟产品{p:02d}",
            "prod_name_en": f"Synthetic product {p:02d}",
            "prod_alias": f"模拟别名{p:02d}",
            "chemical_name": f"模拟化学名{b:02d}",
            "generic_name": f"模拟通用名{b:02d}",
            "brand_code": f"MOCKBRAND{b:03d}",
            "brand_name_cn": f"模拟品牌{b:02d}",
            "brand_name_en": f"Synthetic brand {b:02d}",
            "dosage_forms": "模拟剂型",
            "origin_place": "模拟产地",
            "cold_chain_flag": p % 2,
            "pkg_type": "盒",
            "pkg_size": "1盒",
            "min_unit": "片",
            "min_unit_size": "1片",
            "prod_imgurl": None,
            "manufacturer": "POC模拟生产商",
            "manufacturer_addr": "模拟地址",
            "specification": f"模拟规格{p:02d}",
            "license_issue_flag": 1,
            "license_num": f"MOCK-LICENSE-{p:03d}",
            "license_eff_date": datetime(2020, 1, 1),
            "license_exp_date": datetime(2030, 12, 31),
            "ta_code": f"MOCKTA{ta:02d}",
            "ta_name_cn": f"模拟治疗领域{ta}",
            "ta_name_en": f"Synthetic TA {ta}",
        }


def transactions():
    day = date(2024, 1, 1)
    ident = 0
    prods = list(product_rows())
    while day <= AS_OF:
        for h in range(1, HCO_COUNT + 1):
            for line in range(2):
                ident += 1
                pi = (day.toordinal() + h * 7 + line * 5) % 16
                p = prods[pi]
                b = int(p["brand_code"][-3:])
                qty = (day.day * 7 + h * 3 + line * 11) % 35 + 1
                qty += (day.year - 2024) * 3 + day.month % 4
                if ident % 89 == 0:
                    qty = -qty  # Returns remain signed.
                if b == 13 and day.year == 2024:
                    qty = 0  # A new-brand, zero-baseline scenario.
                if h == 1 and b == 12 and day.year == 2025 and day.month == 9:
                    qty = 0
                price = Decimal(100 + b * 9 + pi * 2).quantize(CENT)
                asp = (price / Decimal("7.2")).quantize(CENT)
                row = {
                    "id": ident,
                    "sales_id": f"MOCKSALE{(ident - 1) // 2:09d}",
                    "sales_date": day,
                    "year_month": day.year * 100 + day.month,
                    "upstream_code": f"MOCKUP{h % 12:03d}",
                    "upstream_extr_code": f"MOCKEXTUP{h % 12:03d}",
                    "downstream_code": f"MOCKDOWN{h:04d}",
                    "downstream_extr_code": f"MOCKEXTDOWN{h:04d}",
                    "affiliate_hco_code": hco(h)["hco_code"],
                    "prod_code_codi": p["prod_code_codi"],
                    "prod_code": p["prod_code"],
                    "sales_qty": Decimal(qty),
                    "data_channel": "模拟DDI",
                    "upstream_level": "一级",
                    "downstream_level": "终端",
                    "downstream_is_special_flag": int(h % 17 == 0),
                    "price_hist": price,
                    "special_price_hist": price,
                    "standard_price_hist": price,
                    "price_latest": price,
                    "daily_date_version": AS_OF,
                    "market_type": "核心市场",
                    "terminal_type": "医院准入",
                    "terminal_channel": "医院",
                    "terminal_platform": "线下",
                    "market_type_latest": "核心市场",
                    "terminal_type_latest": "医院准入",
                    "terminal_channel_latest": "医院",
                    "terminal_platform_latest": "线下",
                    "channel_source": None,
                    "data_type": "Daily",
                    "sales_type": "纯销",
                    "from_cust_bizlevel": "经销商",
                    "to_cust_bizlevel": "终端",
                    "from_cust_org_type1": "模拟商业公司",
                    "codi_rec_id": ident,
                    "asp_price": asp,
                    "brand_name_cn": p["brand_name_cn"],
                }
                yield h, b, row
        day += timedelta(days=1)


def sales_rows():
    sums = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])
    for h, b, r in transactions():
        a = sums[(r["year_month"], h, b)]
        a[0] += r["sales_qty"]
        a[1] += r["sales_qty"] * r["price_latest"]
        a[2] += r["sales_qty"] * r["asp_price"]
    for ym in months():
        for h in range(1, HCO_COUNT + 1):
            geo, ownership = hco(h), org(h, ym)
            for b in range(1, 14):
                q, cny, usd = sums[(ym, h, b)]
                target = Decimal(90 + (h * 3 + b * 7) % 70)
                if h == 1 and b == 13:
                    target = Decimal(0)  # Zero target must yield NULL attainment.
                price = Decimal(100 + b * 9)
                ta = (b - 1) % 6 + 1
                for kind in (
                    ["Daily", "Monthly"] if ym <= LAST_CLOSED_MONTH else ["Daily"]
                ):
                    yield {
                        **geo,
                        "year_month": ym,
                        "teri_code": ownership["ts"],
                        "sam_teri_code": ownership["sam"],
                        "rd_teri_code": ownership["rd"],
                        "brand_code": f"MOCKBRAND{b:03d}",
                        "brand_name_cn": f"模拟品牌{b:02d}",
                        "brand_name_en": f"Synthetic brand {b:02d}",
                        "sales_qty": q,
                        "sales_amt": cny,
                        "sales_amt_asp": usd,
                        "target_qty": target,
                        "target_amt": target * price,
                        "target_amt_asp": (target * price / Decimal("7.2")).quantize(
                            CENT
                        ),
                        "market_type_latest": "核心市场",
                        "terminal_type_latest": "医院准入",
                        "terminal_channel_latest": "医院",
                        "terminal_platform_latest": "线下",
                        "ts_name": f"模拟代表{h:03d}",
                        "ts_adid": f"mock.ts.{h:03d}",
                        "sam_name": f"模拟地区经理{ownership['sam'][-2:]}",
                        "sam_adid": f"mock.asm.{ownership['sam'][-2:]}",
                        "rd_name": f"模拟大区经理{ownership['rd'][-2:]}",
                        "rd_adid": f"mock.rsm.{ownership['rd'][-2:]}",
                        "region": ownership["region"],
                        "data_type": kind,
                        "ta": f"模拟治疗领域{ta}",
                        "bu": f"MOCKBU{(ta - 1) // 3 + 1}",
                    }


def territory_rows():
    for ym in months(202101, 203603):
        for h in range(1, HCO_COUNT + 1):
            g, o = hco(h), org(h, ym)
            for ta in range(1, 7):
                yield {
                    "year_month": ym,
                    "hco_code": g["hco_code"],
                    "hco_name_cn": g["hco_name"],
                    **{
                        k: v
                        for k, v in g.items()
                        if k
                        in {
                            "province_code",
                            "province_name_cn",
                            "city_code",
                            "city_name_cn",
                            "tier",
                        }
                    },
                    "ta": f"模拟治疗领域{ta}",
                    "teri_ta": f"模拟治疗领域{ta}",
                    "ts_teri_code": o["ts"],
                    "ts_teri_name": f"模拟代表辖区{h:03d}",
                    "ts_empl_name": f"模拟代表{h:03d}",
                    "ts_empl_adid": f"mock.ts.{h:03d}",
                    "asm_lvl_teri_code": o["sam"],
                    "asm_lvl_teri_name": f"模拟地区{o['sam'][-2:]}",
                    "asm_lvl_empl_name": f"模拟地区经理{o['sam'][-2:]}",
                    "asm_lvl_empl_adid": f"mock.asm.{o['sam'][-2:]}",
                    "rsm_lvl_teri_code": o["rd"],
                    "rsm_lvl_teri_name": o["region"],
                    "rsm_lvl_empl_name": f"模拟大区经理{o['rd'][-2:]}",
                    "rsm_lvl_empl_adid": f"mock.rsm.{o['rd'][-2:]}",
                    "sd_lvl_teri_code": o["sd"],
                    "sd_lvl_teri_name": "模拟全国",
                    "sd_lvl_empl_name": "模拟销售总监",
                    "sd_lvl_empl_adid": "mock.sd.all",
                    "bu": f"MOCKBU{(ta - 1) // 3 + 1}",
                }


def rows(table):
    if table == "prod_master":
        yield from product_rows()
    elif table == "v_ai4bi_ddi_sales":
        for _, _, r in transactions():
            yield r
    elif table == "sales_target_ai4bi":
        yield from sales_rows()
    elif table == "teri_hierachy":
        yield from territory_rows()
    elif table == "ddi_coverage":
        for b in range(1, 12):
            factor = (
                Decimal("0.114583")
                if b == 1
                else Decimal("1.004446")
                if b == 11
                else Decimal(b) / 12
            )
            yield {
                "brand_code": f"MOCKBRAND{b:03d}",
                "sales_qty_daily": Decimal(b * 20),
                "sales_qty_monthly": Decimal(b * 300),
                "coverage": factor,
            }
    elif table == "data_range_config":
        yield {"max_daily_yearmonth": LAST_CLOSED_MONTH, "max_ddi_version": str(AS_OF)}
    else:
        raise ValueError(table)


def expected_counts():
    return {
        "sales_target_ai4bi": HCO_COUNT * 13 * (32 * 2 + 1),
        "v_ai4bi_ddi_sales": ((AS_OF - date(2024, 1, 1)).days + 1) * HCO_COUNT * 2,
        "prod_master": 16,
        "teri_hierachy": len(list(months(202101, 203603))) * HCO_COUNT * 6,
        "ddi_coverage": 11,
        "data_range_config": 1,
    }
