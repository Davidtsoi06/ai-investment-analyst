# -*- coding: utf-8 -*-
"""S10 推荐 Prompt 模板：短线（技术面+资金面+消息面）/ 长线（基本面+行业面+趋势面）

输出要求：严格 JSON 数组，便于解析；字段缺失时调用方以规则引擎结果兜底。
"""

SHORT_PROMPT = """你是资深 A 股/港股短线交易分析师。基于以下候选股票的技术指标、量能与相关资讯，选出 1~5 只短线机会，输出**入场区间 / 止损 / 目标价 / 置信度 / 逻辑 / 风险等级**。

筛选原则：
- 优先：放量突破、MACD/KDJ 金叉、均线多头、量比放大、RSI 处于 45~75 强势区
- 排除：破位下行、缩量阴跌、RSI 超买（>80）或超卖趋势未反转
- 只输出你认为值得关注的标的；没有把握就少输出

输出格式：严格 JSON 数组，不要任何其他文字，例如：
[{"symbol":"600519","entry_min":1280.0,"entry_max":1310.0,"stop_loss":1240.0,"target":1400.0,"confidence":72,"logic":"放量突破20日高点，MACD金叉，短线动量强","risk_level":"中"}]

字段说明：
- entry_min/entry_max：入场区间（元）；stop_loss：止损价；target：目标价
- confidence：置信度 0~100 整数；logic：一句话中文逻辑（40 字内）
- risk_level：低 / 中 / 高
- 价格均为正数且 entry_min < entry_max；stop_loss < entry_min；target > entry_max

候选数据：
{candidates}
"""

LONG_PROMPT = """你是资深 A 股/港股价值投资分析师。基于以下候选股票的基本面与中长期趋势，选出 1~5 只长线标的，输出**估值区间 / 长线逻辑 / 风险等级 / 置信度**。

筛选原则：
- 优先：估值合理偏低（PE/PB 适中）、周/月线趋势向上、中期走势稳健
- 排除：估值过高、趋势持续走弱、近期暴涨透支
- 只输出你认为值得长线持有的标的

输出格式：严格 JSON 数组，不要任何其他文字，例如：
[{"symbol":"600519","valuation_min":1200.0,"valuation_max":1500.0,"confidence":75,"logic":"高端白酒龙头，PE 19 估值合理，月线趋势向上，现金流优秀","risk_level":"低"}]

字段说明：
- valuation_min/valuation_max：合理估值区间（元）；confidence：置信度 0~100 整数
- logic：一句话中文逻辑（50 字内）；risk_level：低 / 中 / 高
- 价格均为正数且 valuation_min < valuation_max

候选数据：
{candidates}
"""


def _fmt_candidates(candidates: list[dict]) -> str:
    """压缩候选数据为紧凑 JSON 行（控制 Token 量）"""
    lines = []
    for c in candidates:
        lines.append(__import__('json').dumps(c, ensure_ascii=False))
    return chr(10).join(lines)


def build_short_prompt(candidates: list[dict]) -> str:
    return SHORT_PROMPT.format(candidates=_fmt_candidates(candidates))


def build_long_prompt(candidates: list[dict]) -> str:
    return LONG_PROMPT.format(candidates=_fmt_candidates(candidates))
