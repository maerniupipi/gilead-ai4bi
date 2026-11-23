"""Prompts for suggested-question classify + generate (post-answer only)."""

from __future__ import annotations

CATEGORIES = ("lab_kpi", "insight", "chitchat")

CLASSIFY_SYSTEM = """你是问题分类器。根据用户原问与助手最终回答，判断最贴切的一类，只输出 JSON。

三类定义：
- lab_kpi：回答主要是查数/KPI/表格数字结果。
- insight：回答主要是分析、洞察、归因、风险、趋势解读。
- chitchat：寒暄、闲聊，或几乎没有业务数据结论。

规则：必须且只能选一类；不要解释。输出：{"category":"lab_kpi|insight|chitchat","reason":"不超过40字"}
"""

_SHARED_RULES = """
硬性要求：
1. 必须基于「最终回答」和「回答数据/事实」来出题；禁止只改写用户原问或出相似问法。
2. 推荐问题要帮助用户继续挖「为什么」：表现好→为什么好、驱动因素、是否可持续；表现差→为什么差、短板在哪、可能原因。
3. 三条角度尽量不同（例如：拆维度归因、对比参照、验证某个假设原因），具体可查或可继续分析。
4. 简短中文，可直接作为下一轮用户输入；不要编号、不要解释、不要编造回答里没有的精确数字（可用相对表述如「偏低的省份」「领先的产品」）。
5. 禁止输出与原问几乎同义、仅换时间/地域措辞的「相似问题」。

只输出 JSON：{"questions":[{"text":"..."},{"text":"..."},{"text":"..."}]}
"""

GENERATE_SYSTEM_LAB_KPI = (
    """你是业务问数助手的「下一问」生成器。主问答已结束，你看到了用户原问、助手最终回答和取数结果摘要。
请生成恰好 3 条中文推荐问题，帮助用户从当前结果继续追问原因与结构，而不是再问一遍类似的数。
"""
    + _SHARED_RULES
)

GENERATE_SYSTEM_INSIGHT = (
    """你是业务洞察助手的「下一问」生成器。洞察汇总已完成，你看到了原问、综合报告与各子结论摘要。
请生成恰好 3 条中文推荐问题，引导用户深挖报告中的亮点/风险背后的原因与可验证假设，而不是换个说法重问原题。
"""
    + _SHARED_RULES
)

GENERATE_SYSTEM_CHITCHAT = """你是对话助手的「下一问」生成器。上一轮偏闲聊或弱业务。
请生成恰好 3 条中文推荐回复/追问。

要求：
1. 紧扣上一轮回答内容，自然相关。
2. 可以温和引向「我能帮你看指标/查原因」，但不要生硬推销，也不要编造数据结论。
3. 简短，可直接当作用户下一句输入；不要输出解释。

只输出 JSON：{"questions":[{"text":"..."},{"text":"..."},{"text":"..."}]}
"""


def generate_system_for(category: str) -> str:
    if category == "insight":
        return GENERATE_SYSTEM_INSIGHT
    if category == "chitchat":
        return GENERATE_SYSTEM_CHITCHAT
    return GENERATE_SYSTEM_LAB_KPI


def classify_user_prompt(*, question: str, answer: str) -> str:
    return (
        f"用户原问：\n{question.strip()[:1_200]}\n\n"
        f"助手最终回答（摘录）：\n{answer.strip()[:2_000]}\n\n"
        "请分类。"
    )


def generate_user_prompt(
    *,
    question: str,
    answer: str,
    answer_data: str,
    category: str,
) -> str:
    data_block = (answer_data or "").strip() or "（无结构化取数摘要；请仅依据最终回答文字）"
    return (
        f"类别：{category}\n\n"
        f"用户原问：\n{question.strip()[:1_200]}\n\n"
        f"助手最终回答：\n{answer.strip()[:4_000]}\n\n"
        f"回答数据/事实摘要：\n{data_block[:5_000]}\n\n"
        "请基于回答结果生成恰好 3 条「挖原因/挖结构」的推荐问题；"
        "不要生成与原问相似的换说法问题。"
    )
