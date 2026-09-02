# -*- coding: utf-8 -*-
"""S13 研报解读 Prompt：AI 提取核心观点（目标价/评级变化/关键假设/风险提示，300 字摘要）"""

import json

INTERPRET_PROMPT = (
    '你是研报解读专家。请基于以下研报信息，输出结构化解读（Markdown 格式，前端按分段渲染）：\n'
    '**核心观点**：目标价与评级变化（如数据缺失请说明）；\n'
    '**关键假设**：（如数据缺失请说明）；\n'
    '**风险提示**：；\n'
    '**持仓关联**：与用户持仓的关联（若持仓包含该标的请明确指出，否则说明无持仓重叠）。\n'
    '要求：总字数 300 字以内；只输出解读正文（以上四个 Markdown 分段），不要输出其他前缀；'
    '若信息不足请如实说明，不要编造；结尾提醒不构成投资建议。\n\n'
    '研报信息：\n{research}\n\n'
    '用户持仓：\n{holdings}'
)


def build_interpret_prompt(item: dict) -> str:
    """构建研报解读 user prompt"""
    from ...models.database import get_connection
    from ...services.portfolio_sync import get_mode
    src = 'portfolio_app' if get_mode() == 'snapshot' else 'manual'
    conn = get_connection()
    try:
        rows = conn.execute('SELECT symbol, name FROM holdings WHERE source = ?', (src,)).fetchall()
    finally:
        conn.close()
    holdings_txt = '、'.join(f"{r['name']}（{r['symbol']}）" for r in rows) if rows else '无持仓记录'
    research_txt = json.dumps(item, ensure_ascii=False, default=str)
    return INTERPRET_PROMPT.format(research=research_txt, holdings=holdings_txt)
