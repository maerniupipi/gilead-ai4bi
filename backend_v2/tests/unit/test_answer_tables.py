from xiaoying_quick.application.answer_tables import answer_tables


def test_extracts_visible_tables_with_headings_and_inline_formatting():
    answer = """## 核心指标

| 指标 | 数值 |
| --- | ---: |
| **金额** | 1,000 元 |
| 达成率 | **95%** |
| 渠道 | 医院\\|零售<br>线上 |

## 城市结构

| 城市 | 名称 |
| --- | --- |
| 北京 | [模拟药品](https://example.com) &amp; `A` |
"""
    tables = answer_tables(answer)
    assert len(tables) == 2
    assert tables[0]["title"] == "核心指标"
    assert tables[0]["data"]["columns"] == ["指标", "数值"]
    assert tables[0]["data"]["rows"] == [
        ["金额", "1,000 元"],
        ["达成率", "95%"],
        ["渠道", "医院|零售\n线上"],
    ]
    assert tables[1]["data"]["rows"] == [["北京", "模拟药品 & A"]]


def test_code_examples_do_not_change_table_indexes_and_html_is_saved_as_text():
    answer = """```markdown
| 示例 | 数值 |
|---|---|
| 不应收藏 | 999 |
```

<table><tr><th>城市</th><th>金额</th></tr><tr><td>上海</td><td><b>200</b></td></tr></table>
"""
    tables = answer_tables(answer)
    assert len(tables) == 1
    assert tables[0]["data"]["rows"] == [["上海", "200"]]


def test_html_tables_without_headers_preserve_the_first_data_row():
    tables = answer_tables("<table><tr><td>北京</td><td>100</td></tr></table>")
    assert tables[0]["data"]["columns"] == ["列 1", "列 2"]
    assert tables[0]["data"]["rows"] == [["北京", "100"]]


def test_tables_removed_by_the_answer_sanitizer_do_not_shift_visible_indexes():
    answer = """<section><table><tr><th>不可见表</th></tr><tr><td>999</td></tr></table></section>

| 城市 | 金额 |
|---|---|
| 北京 | 100 |
"""
    tables = answer_tables(answer)
    assert len(tables) == 1
    assert tables[0]["data"]["rows"] == [["北京", "100"]]


def test_large_answer_tables_use_the_same_bounded_preview():
    answer = "| 城市 | 金额 |\n|---|---|\n" + "\n".join(f"| 城市{i} | {i} |" for i in range(1010))
    data = answer_tables(answer)[0]["data"]
    assert data["row_count"] == 1010
    assert len(data["rows"]) == 1000
    assert data["preview_truncated"] is True
