# -*- coding: utf-8 -*-
"""盘前资讯分级与摘要 Prompt"""

NEWS_CLASSIFY_PROMPT = """你是专业的财经资讯分析师。请对以下财经资讯逐条进行分级，并为每条生成一句话核心要点摘要。

分级标准：
- 重大：影响大盘或用户持仓的重大事件（宏观政策、央行决议、重大财报、并购重组、监管大动作等）
- 中等：行业/板块级别的重要消息
- 一般：常规资讯

要求：
1. 只输出 JSON 数组，不要任何其他文字
2. 每条格式：{{"index": 序号, "level": "重大|中等|一般", "summary": "一句话核心要点（20字内）"}}
3. 用户持仓相关（持仓名称出现在标题或摘要中）时，summary 以【持仓相关】开头

用户持仓：{holdings}

资讯列表：
{news_list}
"""

def build_classify_prompt(items: list, holdings: list[str]) -> str:
    news_list = chr(10).join(f"{i + 1}. {it.title}（{it.summary[:60]}）" for i, it in enumerate(items))
    holdings_text = '、'.join(holdings) if holdings else '无持仓记录'
    return NEWS_CLASSIFY_PROMPT.format(holdings=holdings_text, news_list=news_list)
