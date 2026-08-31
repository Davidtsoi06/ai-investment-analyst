# -*- coding: utf-8 -*-
"""S10 约束规则：市场匹配 / 持仓冲突 / 资金匹配 / 风险匹配（需求文档 模块三）

- 市场匹配：仅推荐用户画像勾选的市场（A股/港股）
- 持仓冲突：已在持仓中的股票不重复推荐
- 资金匹配：单手价（价格 × 每手股数）≤ 可投资金额 × 10%
- 风险匹配：推荐风险等级不超出用户风险承受能力
"""

import re
from typing import Any

LOT_SIZE = {'A股': 100, '港股': 100}  # 每手股数（港股部分标的非整百，取近似）
RISK_ALLOW = {
    '保守型': ['低'],
    '稳健型': ['低', '中'],
    '激进型': ['低', '中', '高'],
}
VALID_RISK_LEVELS = ('低', '中', '高')


def parse_invest_amount(text: str | None) -> float | None:
    """解析可投资金额文案为元（取下限，保守匹配）；无法解析返回 None（不校验）"""
    if not text:
        return None
    nums = [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)', str(text))]
    if not nums:
        return None
    unit = 1e8 if '亿' in text else (1e4 if '万' in text else 1.0)
    lower = min(nums) if len(nums) > 1 else nums[0]
    return lower * unit


def lot_price(price: float, market: str) -> float:
    """单手价格（元）"""
    return float(price) * LOT_SIZE.get(market, 100)


def market_match(market: str, profile_markets: list[str]) -> bool:
    return market in (profile_markets or [])


def fund_match(price: float, invest_amount_text: str | None, market: str) -> bool:
    """资金匹配：单手价 ≤ 可投资金额 10%"""
    amount = parse_invest_amount(invest_amount_text)
    if amount is None or amount <= 0:
        return True
    return lot_price(price, market) <= amount * 0.10


def risk_match(risk_level: str | None, risk_tolerance: str | None) -> bool:
    allowed = RISK_ALLOW.get(risk_tolerance or '', RISK_ALLOW['稳健型'])
    return (risk_level or '中') in allowed


def apply_constraints(entries: list[dict], profile: dict[str, Any],
                      holdings: list[dict]) -> dict[str, list[dict]]:
    """对推荐条目逐条应用约束；返回 {'passed': [...], 'blocked': [{'symbol','name','rec_type','reasons':[...]}]}

    - entries: [{'symbol','name','market','rec_type','price','risk_level', ...}]
    - 市场不匹配 / 持仓冲突 / 资金不匹配 / 风险不匹配 一律拦截（附原因）
    """
    markets = profile.get('markets') or []
    invest_text = profile.get('invest_amount')
    risk_tol = profile.get('risk_tolerance')
    holding_symbols = {str(h.get('symbol')) for h in holdings}

    passed: list[dict] = []
    blocked: list[dict] = []
    for entry in entries:
        symbol = str(entry.get('symbol', ''))
        reasons: list[str] = []
        if not market_match(entry.get('market'), markets):
            reasons.append(f'市场匹配：仅推荐 {", ".join(markets) or "未勾选市场"}（{entry.get("market")} 不在其中）')
        if symbol in holding_symbols:
            reasons.append(f'持仓冲突：{entry.get("name") or symbol} 已在持仓中')
        if not fund_match(float(entry.get('price') or 0), invest_text, entry.get('market')):
            reasons.append(f'资金匹配：单手价约 {lot_price(float(entry.get("price") or 0), entry.get("market")):.0f} 元，超过可投资金额 10%')
        if not risk_match(entry.get('risk_level'), risk_tol):
            reasons.append(f'风险匹配：{entry.get("risk_level")} 风险超出 {risk_tol} 承受范围')
        if reasons:
            blocked.append({
                'symbol': symbol,
                'name': entry.get('name'),
                'rec_type': entry.get('rec_type'),
                'reasons': reasons,
            })
        else:
            passed.append(entry)
    return {'passed': passed, 'blocked': blocked}
