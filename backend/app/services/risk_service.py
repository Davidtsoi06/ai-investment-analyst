# -*- coding: utf-8 -*-
"""S14 组合风险分析：集中度 / 最大回撤 / Beta / 夏普 / VaR + 压力测试 + 预警通知

指标口径（见 docs/需求文档V1.md 模块七）：
  - 单只集中度：单只市值 / 组合总市值（>20% 预警）
  - 行业集中度（简化版）：按市场分组（A股/港股）市值占比（>40% 预警）
  - 最大回撤：持仓市值权重 × 各股日K close 构建组合净值序列 → (峰-谷)/峰
  - Beta：组合日收益率 vs 上证指数（sh000001 日K）收益率线性回归斜率；数据不足降级 None
  - 夏普：组合日收益均值/标准差 × sqrt(252)，无风险利率 2% 年化
  - VaR：95% 置信度日收益 5% 分位数 × 组合市值（历史模拟法）
  - 预警阈值：集中度>20% / 市场占比>40% / Beta>1.5 / 夏普<0 / VaR>可承受金额
    （可承受金额 = profile.invest_amount 档位中值 × 5%）
"""

import json
import math
import re
import statistics
from datetime import datetime

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection
from .logger import get_app_logger
from .profile_service import get_profile

logger = get_app_logger()

INDEX_KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'

# 压力测试场景定义：{key: (名称, 说明)}
STRESS_SCENARIOS = {
    'market_down_10': ('大盘下跌 10%', '市场系统性下跌：组合损失 ≈ Beta × 10% × 总市值'),
    'hk_tech_down_20': ('港股科技板块下跌 20%', '港股持仓按市值权重 × 20% 估算损失'),
    'cny_depreciate_5': ('人民币汇率贬值 5%', '港股资产按 5% 汇率损失折算'),
}

CONCENTRATION_WARN = 0.20      # 单只集中度预警阈值
MARKET_SHARE_WARN = 0.40       # 市场占比预警阈值
BETA_WARN = 1.5                # Beta 预警阈值
SHARPE_WARN = 0.0              # 夏普预警阈值
RISK_FREE_RATE = 0.02          # 无风险利率（年化）
VAR_CONFIDENCE = 0.05          # VaR 95% 置信度（日收益 5% 分位数）
AFFORDABLE_RATIO = 0.05        # VaR 可承受比例：可投资金额中值 × 5%
MIN_SAMPLES = 20               # Beta/回撤/夏普/VaR 最少样本数


# ---------------- 基础数据 ----------------

def _load_holdings() -> list[dict]:
    conn = get_connection()
    try:
        from .portfolio_sync import get_mode
        src = 'portfolio_app' if get_mode() == 'snapshot' else 'manual'
        rows = conn.execute(
            'SELECT symbol, name, market, quantity, cost_price, current_price FROM holdings WHERE source = ?',
            (src,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_position_price(symbol: str, market: str, current_price) -> float | None:
    """持仓现价：实时行情优先（data_fusion.get_quote），获取失败回退 current_price 字段"""
    try:
        q = data_fusion.get_quote(symbol, market)
        if q is not None and q.price and q.price > 0:
            return float(q.price)
    except Exception as e:  # noqa: BLE001
        logger.warning('持仓 %s 实时行情失败: %s', symbol, str(e)[:100])
    if current_price:
        try:
            p = float(current_price)
            if p > 0:
                return p
        except (TypeError, ValueError):
            pass
    return None


def _index_kline(symbol: str, days: int = 90) -> list[dict] | None:
    """指数日K（腾讯源，支持 sh000001 / hkHSI 等），返回 [{date, close}]；失败返回 None"""
    try:
        from ..data_sources.market.http_client import get
        import json
        text = get(INDEX_KLINE_URL, params={'param': f'{symbol},day,,,{days},qfq'})
        data = json.loads(text)
        node = (data.get('data') or {}).get(symbol) or {}
        arr = node.get('qfqday') or node.get('day') or []
        bars = []
        for row in arr[-days:]:
            if not row or len(row) < 3:
                continue
            try:
                bars.append({'date': str(row[0]), 'close': float(row[2])})
            except (TypeError, ValueError):
                continue
        return bars or None
    except Exception as e:  # noqa: BLE001
        logger.warning('指数K线 %s 获取失败: %s', symbol, str(e)[:100])
        return None


def _closes_to_returns(closes: list[dict], key: str = 'close') -> dict[str, float]:
    """收盘序列 → {date: 日收益率}"""
    out: dict[str, float] = {}
    prev = None
    for row in closes:
        try:
            close = float(row[key])
        except (TypeError, ValueError):
            continue
        if prev is not None and prev > 0:
            out[str(row['date'])] = close / prev - 1
        prev = close
    return out


# ---------------- 指标计算 ----------------

def _invest_amount_mid(text: str | None) -> float | None:
    """解析可投资金额文案为档位中值（元）：'10-50万' → 30万；'10万' → 10万；无法解析 None"""
    if not text:
        return None
    nums = [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)', str(text))]
    if not nums:
        return None
    unit = 1e8 if '亿' in str(text) else (1e4 if '万' in str(text) else 1.0)
    if len(nums) >= 2:
        return (min(nums) + max(nums)) / 2 * unit
    return nums[0] * unit


def _portfolio_returns(positions: list[dict]) -> list[tuple[str, float]]:
    """组合日收益率：按日对持仓收益率加权（当日无数据的持仓剔除并按剩余权重归一）"""
    series = [p['returns'] for p in positions]
    if not series:
        return []
    dates = sorted(set().union(*(set(s.keys()) for s in series)))
    out: list[tuple[str, float]] = []
    for d in dates:
        ws = [p['weight'] for p, s in zip(positions, series) if d in s]
        rs = [s[d] for s in series if d in s]
        if not ws:
            continue
        tot = sum(ws)
        if tot <= 0:
            continue
        out.append((d, sum(w / tot * rv for w, rv in zip(ws, rs))))
    return out


def _max_drawdown(rets: list[tuple[str, float]]) -> float | None:
    """组合净值 (峰-谷)/峰 最大回撤；样本不足返回 None"""
    if len(rets) < MIN_SAMPLES:
        return None
    nav = 1.0
    peak = 1.0
    mdd = 0.0
    for _, r in rets:
        nav *= (1 + r)
        if nav > peak:
            peak = nav
        if peak > 0:
            mdd = max(mdd, (peak - nav) / peak)
    return round(mdd, 4)


def _beta_vs_index(port_rets: list[tuple[str, float]]) -> float | None:
    """组合日收益 vs 上证指数日收益 线性回归斜率；样本不足返回 None"""
    idx = _index_kline('sh000001', 120)
    if not idx:
        return None
    idx_rets = _closes_to_returns(idx)
    pairs = [(r, idx_rets[d]) for d, r in port_rets if d in idx_rets]
    if len(pairs) < MIN_SAMPLES:
        return None
    n = len(pairs)
    mx = sum(x for _, x in pairs) / n
    my = sum(y for y, _ in pairs) / n
    cov = sum((y - my) * (x - mx) for y, x in pairs) / n
    var_x = sum((x - mx) ** 2 for _, x in pairs) / n
    if var_x <= 0:
        return None
    return round(cov / var_x, 4)


def _sharpe(rets: list[tuple[str, float]]) -> float | None:
    """年化夏普：(日收益均值 - 日无风险) / 日收益标准差 × sqrt(252)"""
    if len(rets) < MIN_SAMPLES:
        return None
    rs = [r for _, r in rets]
    mean = sum(rs) / len(rs)
    if len(rs) < 2:
        return None
    sd = statistics.stdev(rs)
    if sd == 0:
        return None
    return round((mean - RISK_FREE_RATE / 252) / sd * math.sqrt(252), 4)


def _var_amount(rets: list[tuple[str, float]], total_value: float) -> float | None:
    """VaR（95%）：日收益 5% 分位数 × 组合市值（历史模拟法，正数表示可能日损失）"""
    if not rets or total_value <= 0:
        return None
    rs = sorted(r for _, r in rets)
    idx = max(0, min(len(rs) - 1, int(math.ceil(VAR_CONFIDENCE * len(rs))) - 1))
    q05 = rs[idx]
    return round(max(0.0, -q05 * total_value), 2)


def _build_alerts(indicators: dict, total_value: float, affordable: float | None) -> list[dict]:
    """预警判定：集中度>20% / 市场占比>40% / Beta>1.5 / 夏普<0 / VaR>可承受金额"""
    alerts: list[dict] = []

    def add(indicator: str, value, threshold, level: str):
        alerts.append({'indicator': indicator, 'value': value,
                       'threshold': threshold, 'level': level})

    cmax = indicators.get('concentration_max') or 0
    if cmax > CONCENTRATION_WARN:
        add('单只集中度', cmax, CONCENTRATION_WARN,
            'danger' if cmax > CONCENTRATION_WARN * 1.5 else 'warning')
    for market, share in (indicators.get('market_share') or {}).items():
        if share > MARKET_SHARE_WARN:
            add(f'{market}占比', share, MARKET_SHARE_WARN,
                'danger' if share > MARKET_SHARE_WARN * 1.5 else 'warning')
    beta = indicators.get('beta')
    if beta is not None and beta > BETA_WARN:
        add('Beta', beta, BETA_WARN, 'danger' if beta > BETA_WARN * 1.3 else 'warning')
    sharpe = indicators.get('sharpe')
    if sharpe is not None and sharpe < SHARPE_WARN:
        add('夏普比率', sharpe, SHARPE_WARN, 'warning')
    var = indicators.get('var')
    if var is not None and var > 0 and affordable is not None and var > affordable:
        add('VaR(95%)', var, affordable, 'danger')
    return alerts


# ---------------- 主入口 ----------------

def compute_risk_overview(notify: bool = True) -> dict:
    """组合风险总览：{total_value, indicators:{concentration_max, concentration_detail,
    market_share, max_drawdown, beta, sharpe, var}, alerts, positions, updated_at}

    空持仓：total_value=0、集中度为 0、其余指标 None、alerts=[]，不崩溃。
    """
    holdings = _load_holdings()
    positions: list[dict] = []
    for h in holdings:
        price = get_position_price(h['symbol'], h['market'], h.get('current_price'))
        if price is None:
            continue
        quantity = float(h['quantity'] or 0)
        if quantity <= 0:
            continue
        positions.append({
            'symbol': h['symbol'], 'name': h['name'], 'market': h['market'],
            'price': round(price, 4), 'quantity': quantity,
            'value': round(price * quantity, 2),
        })

    total_value = round(sum(p['value'] for p in positions), 2)

    # 集中度（单只）
    concentration_detail = []
    for p in positions:
        weight = (p['value'] / total_value) if total_value > 0 else 0.0
        p['weight'] = round(weight, 4)
        concentration_detail.append({
            'symbol': p['symbol'], 'name': p['name'], 'market': p['market'],
            'value': p['value'], 'weight': round(weight, 4),
        })
    concentration_max = round(max((c['weight'] for c in concentration_detail), default=0.0), 4)

    # 市场占比（A股/港股）
    market_share = {'A股': 0.0, '港股': 0.0}
    if total_value > 0:
        for p in positions:
            market_share[p['market']] = market_share.get(p['market'], 0.0) + p['value']
        for m in market_share:
            market_share[m] = round(market_share[m] / total_value, 4)

    # 日收益率序列（K线 60 条 close）
    for p in positions:
        p['returns'] = {}
        try:
            bars = data_fusion.get_kline(p['symbol'], p['market'], 60)
            if bars:
                p['returns'] = _closes_to_returns(
                    [{'date': b.date, 'close': b.close} for b in bars])
        except Exception as e:  # noqa: BLE001
            logger.warning('持仓 %s K线获取失败: %s', p['symbol'], str(e)[:100])
    rets = _portfolio_returns([p for p in positions if p['returns']])

    indicators = {
        'concentration_max': concentration_max,
        'concentration_detail': concentration_detail,
        'market_share': market_share,
        'max_drawdown': _max_drawdown(rets),
        'beta': _beta_vs_index(rets),
        'sharpe': _sharpe(rets),
        'var': _var_amount(rets, total_value),
    }

    # 可承受金额 = 可投资金额档位中值 × 5%
    affordable = None
    try:
        mid = _invest_amount_mid(get_profile().get('invest_amount'))
        if mid:
            affordable = round(mid * AFFORDABLE_RATIO, 2)
    except Exception as e:  # noqa: BLE001
        logger.warning('可承受金额解析失败: %s', str(e)[:100])

    alerts = _build_alerts(indicators, total_value, affordable)
    if notify and alerts:
        try:
            from .notification import send_notification
            content = '；'.join(
                f"{a['indicator']} {a['value']}（阈值 {a['threshold']}）" for a in alerts)
            send_notification('risk', '⚠️ 组合风险预警', content, level='关注')
        except Exception as e:  # noqa: BLE001
            logger.warning('风险预警通知发送失败: %s', str(e)[:100])

    # V1.0.6：新手友好的白话操作建议（规则文本，无 AI 依赖、即时稳定）
    advice = _build_advice(indicators, affordable, concentration_detail, positions, total_value)

    return {
        'total_value': total_value,
        'indicators': indicators,
        'alerts': alerts,
        'advice': advice,
        'positions': [{'symbol': p['symbol'], 'name': p['name'], 'market': p['market'],
                       'price': p['price'], 'quantity': p['quantity'],
                       'value': p['value'], 'weight': p['weight']} for p in positions],
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def _build_advice(indicators: dict, affordable: float | None,
                  concentration_detail: list[dict], positions: list[dict],
                  total_value: float) -> list[str]:
    """根据风险指标生成可执行操作建议（大白话，供新手理解如何规避风险）"""
    advice: list[str] = []
    if not positions or total_value <= 0:
        return ['当前没有可分析的有效持仓：请先在「持仓总览」录入或同步持仓，再查看组合风险与建议。']

    def pct_of(v) -> float:
        return round(float(v or 0) * 100, 1)

    top_name = ''
    for c in concentration_detail:
        if c.get('name') or c.get('symbol'):
            top_name = c['name'] or c['symbol']
            break

    cmax = float(indicators.get('concentration_max') or 0)
    if cmax > 0.20:
        advice.append(
            f'单只集中度过高：「{top_name or "最大持仓"}」占组合 {pct_of(cmax)}%，超过 20% 警戒线。'
            '建议逐步把仓位分散到 2~3 只相关性较低的标的（如不同行业/市场），单只控制在 20% 以内，'
            '避免一只股票大跌拖垮整个组合。')

    ms = indicators.get('market_share') or {}
    top_market, top_share = '', 0.0
    if isinstance(ms, dict):
        for mk, v in ms.items():
            s = float(v or 0)
            if s > top_share:
                top_market, top_share = mk, s
    if top_share > 0.40:
        advice.append(
            f'市场占比偏高：{top_market or ""}资产占组合 {pct_of(top_share)}%，超过 40% 警戒线。'
            f'建议增配另一市场的标的或现金类资产做跨市场分散，单一市场系统性下跌时损失会更可控。')

    mdd = float(indicators.get('max_drawdown') or 0)
    if mdd >= 0.15:
        advice.append(
            f'最大回撤达 {pct_of(mdd)}%（近 60 个交易日从高点回落幅度较大）。'
            '建议：降低总仓位到心理可承受水平；每笔设置止损纪律（如 -8% 无条件离场），'
            '不要在市场急跌时情绪化补仓。')
    elif mdd >= 0.08:
        advice.append(
            f'组合最大回撤约 {pct_of(mdd)}%，波动中等。建议保持止损纪律，回撤扩大时先减仓再观察。')

    beta = indicators.get('beta')
    if beta is not None and float(beta) > 1.5:
        advice.append(
            f'Beta {float(beta):.2f}：组合波动显著大于大盘（涨跌都会被放大）。'
            '建议降低仓位或增配低波动资产（红利/债券类），防止大盘回调时组合跌幅过大。')

    sharpe = indicators.get('sharpe')
    if sharpe is not None and float(sharpe) < 0:
        advice.append(
            '夏普比率为负：组合收益跑不赢无风险利率，说明持仓质量或入场时机欠佳。'
            '建议审视每只持仓的上涨逻辑是否还在，把资金逐步换入趋势向上、基本面更扎实的标的。')

    var_amt = indicators.get('var')
    if var_amt is not None and float(var_amt) > 0:
        if affordable is not None and float(var_amt) > affordable:
            advice.append(
                f'单日 VaR（{fmt_money_str(float(var_amt))}）已超过你的可承受额度'
                f'（约 {fmt_money_str(affordable)}）。建议直接降低仓位/减少杠杆，把潜在单日亏损压回可承受范围。')

    if not advice:
        advice.append(
            '各项指标均在健康范围内：集中度、回撤、波动与潜在损失都可控。'
            '建议维持现有纪律：按计划定投/分批、设好止损、定期复盘，不要频繁追涨杀跌。')
    return advice[:5]


def fmt_money_str(v: float) -> str:
    """金额简写：≥1亿 → x.x 亿；≥1万 → x.x 万；否则元"""
    if v >= 1e8:
        return f'{v / 1e8:.1f} 亿元'
    if v >= 1e4:
        return f'{v / 1e4:.1f} 万元'
    return f'{v:.0f} 元'


# ---------------- 压力测试 ----------------

def stress_test(scenario: str) -> dict:
    """压力测试：{scenario, estimated_loss, estimated_loss_pct, detail}
    场景：
      market_down_10   — 组合损失 ≈ Beta × 10% × 总市值（Beta 缺失按 1.0 估算）
      hk_tech_down_20  — 港股持仓按权重 × 20%
      cny_depreciate_5 — 港股资产按 5% 汇率损失
    """
    if scenario not in STRESS_SCENARIOS:
        raise ValueError(f"未知场景: {scenario}，可选 {', '.join(STRESS_SCENARIOS)}")
    name, desc = STRESS_SCENARIOS[scenario]

    overview = compute_risk_overview(notify=False)
    total = overview['total_value']
    positions = overview['positions']
    hk_positions = [p for p in positions if p['market'] == '港股']
    hk_value = round(sum(p['value'] for p in hk_positions), 2)

    if total <= 0:
        return {'scenario': scenario, 'name': name, 'estimated_loss': 0.0,
                'estimated_loss_pct': 0.0,
                'detail': {'description': desc, 'note': '当前无有效持仓'}}

    if scenario == 'market_down_10':
        beta = overview['indicators'].get('beta')
        factor = float(beta) if beta is not None else 1.0
        loss_pct = factor * 10.0
        detail = {
            'description': desc,
            'beta': beta,
            'note': 'Beta 缺失时按 1.0 估算' if beta is None else '损失 = Beta × 10%',
        }
    elif scenario == 'hk_tech_down_20':
        loss_pct = (hk_value / total * 20.0) if total > 0 else 0.0
        detail = {
            'description': desc,
            'hk_value': hk_value,
            'hk_positions': [{'symbol': p['symbol'], 'name': p['name'],
                              'value': p['value']} for p in hk_positions],
        }
    else:  # cny_depreciate_5
        loss_pct = (hk_value / total * 5.0) if total > 0 else 0.0
        detail = {
            'description': desc,
            'hk_value': hk_value,
            'note': '损失 = 港股资产 × 5%（汇率折算）',
        }

    loss = round(total * loss_pct / 100.0, 2)
    return {
        'scenario': scenario,
        'name': name,
        'estimated_loss': loss,
        # 统一为小数比例（0.15 = 15%），与 overview indicators 口径一致，前端统一 ×100
        'estimated_loss_pct': round(loss_pct / 100.0, 6),
        'detail': detail,
    }


# ---------------- 预警记录 ----------------

def list_risk_alerts(limit: int = 20) -> list[dict]:
    """最近风险预警通知（notification_log type='risk'）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT id, type, level, title, content, sent_at FROM notification_log '
            "WHERE type = 'risk' ORDER BY sent_at DESC LIMIT ?",
            (min(int(limit), 100),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
