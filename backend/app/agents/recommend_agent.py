# -*- coding: utf-8 -*-
"""S10 推荐 Agent：候选采集 → 技术指标快照 → 规则评分 → DeepSeek 生成（无 Key/失败降级规则）
→ 约束规则过滤 → 入库 + 通知

数据流（每只候选股）：
  quote（data_fusion） + kline 120 日（data_fusion） → indicator_snapshot
  + news_cache 关联资讯（消息面） → 短线/长线条目
规则引擎始终先生成（保底），AI 输出通过校验时以 AI 为准（source='ai'）。
"""

import json
import re
from datetime import date

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from ..services.logger import get_agent_logger
from ..services.indicators import indicator_snapshot, score_long_term, score_short_term
from ..services.recommend_constraints import apply_constraints
from ..utils.prompts.recommend_prompt import build_long_prompt, build_short_prompt

logger = get_agent_logger()

# 自选股为空时的兜底候选池（按画像市场过滤）
DEFAULT_CANDIDATES = [
    {'symbol': '600519', 'name': '贵州茅台', 'market': 'A股'},
    {'symbol': '000858', 'name': '五粮液', 'market': 'A股'},
    {'symbol': '300750', 'name': '宁德时代', 'market': 'A股'},
    {'symbol': '601318', 'name': '中国平安', 'market': 'A股'},
    {'symbol': '600036', 'name': '招商银行', 'market': 'A股'},
    {'symbol': '000333', 'name': '美的集团', 'market': 'A股'},
    {'symbol': '600900', 'name': '长江电力', 'market': 'A股'},
    {'symbol': '00700', 'name': '腾讯控股', 'market': '港股'},
    {'symbol': '09988', 'name': '阿里巴巴', 'market': '港股'},
    {'symbol': '03690', 'name': '美团', 'market': '港股'},
]

MAX_CANDIDATES = 10  # 单日最多分析的候选股数（控制 Token 与耗时）


def _load_profile() -> dict:
    from ..services.profile_service import get_profile
    return get_profile()


def _load_holdings() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT symbol, name, market FROM holdings'
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _candidate_pool(profile: dict) -> list[dict]:
    """候选池 = 自选股（按画像市场过滤）；为空时用兜底池"""
    markets = [m for m in (profile.get('markets') or []) if m in ('A股', '港股')]
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT symbol, name, market FROM watchlist ORDER BY group_name, sort_order, id'
        ).fetchall()
        pool = [dict(r) for r in rows if dict(r).get('market') in markets]
    finally:
        conn.close()
    if not pool:
        pool = [c for c in DEFAULT_CANDIDATES if c['market'] in markets]
        if not pool:
            pool = [c for c in DEFAULT_CANDIDATES if c['market'] == 'A股']
    return pool[:MAX_CANDIDATES]


def _related_news(name: str, symbol: str, limit: int = 3) -> list[str]:
    """关联资讯（消息面）：news_cache 标题 LIKE 匹配股票名/代码"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT title FROM news_cache WHERE title LIKE ? OR title LIKE ? ORDER BY id DESC LIMIT ?",
            (f'%{name}%', f'%{symbol}%', limit),
        ).fetchall()
        return [r['title'] for r in rows]
    finally:
        conn.close()


def _short_rule(symbol: str, name: str, market: str, quote, snap: dict) -> dict | None:
    """规则引擎短线推荐（评分不足返回 None）"""
    score = score_short_term(snap)
    if score < 40:
        return None
    close = float(quote.price)
    entry_min = round(close * 0.99, 2)
    entry_max = round(close * 1.02, 2)
    stop_loss = round(min(snap.get('low_5d') or close * 0.95, close * 0.95), 2)
    target = round(close * (1.08 if score >= 70 else 1.05), 2)
    signals = []
    if snap.get('breakout', {}).get('hit'):
        signals.append(f"放量突破{snap['breakout']['ref_high']}")
    if snap.get('macd_golden_cross'):
        signals.append('MACD金叉')
    if snap.get('kdj_golden_cross'):
        signals.append('KDJ金叉')
    if snap.get('ma_status') == '多头排列':
        signals.append('均线多头排列')
    if not signals:
        signals.append('技术形态偏强')
    risk = '低' if score >= 75 else ('中' if score >= 55 else '高')
    return {
        'symbol': symbol, 'name': name, 'market': market, 'rec_type': '短线',
        'entry_min': entry_min, 'entry_max': entry_max,
        'stop_loss': stop_loss, 'target': target,
        'valuation_min': None, 'valuation_max': None,
        'confidence': min(90, 55 + score // 2),
        'logic': '；'.join(signals) + f'（规则评分 {score}）',
        'risk_level': risk,
        'price': close,
    }


def _long_rule(symbol: str, name: str, market: str, quote, snap: dict) -> dict | None:
    """规则引擎长线推荐（评分不足返回 None）"""
    pe = float(quote.pe or 0)
    pb = float(quote.pb or 0)
    score = score_long_term(snap, pe, pb)
    if score < 45:
        return None
    close = float(quote.price)
    valuation_min = round(close * 0.92, 2)
    valuation_max = round(close * 1.08, 2)
    if pe > 0 and pe < 30:
        valuation_min = round(close * 0.95, 2)
    if pe > 0 and pe > 50:
        valuation_max = round(close * 1.04, 2)
    if pe > 0 and pe < 20 and snap.get('ma_status') == '多头排列':
        risk = '低'
    elif pe <= 0 or pe < 40:
        risk = '中'
    else:
        risk = '高'
    logic_parts = []
    if snap.get('weekly_trend') == '多头':
        logic_parts.append('周线趋势向上')
    if snap.get('monthly_trend') == '多头':
        logic_parts.append('月线趋势向上')
    if snap.get('ma_status') == '多头排列':
        logic_parts.append('均线多头排列')
    if pe > 0:
        logic_parts.append(f'PE {pe:.1f}' + (' 估值合理' if pe <= 30 else ' 估值偏高'))
    if pb > 0:
        logic_parts.append(f'PB {pb:.1f}')
    if not logic_parts:
        logic_parts.append('中长期形态稳健')
    return {
        'symbol': symbol, 'name': name, 'market': market, 'rec_type': '长线',
        'entry_min': None, 'entry_max': None,
        'stop_loss': None, 'target': None,
        'valuation_min': valuation_min, 'valuation_max': valuation_max,
        'confidence': min(85, 50 + score // 2),
        'logic': '；'.join(logic_parts) + f'（规则评分 {score}）',
        'risk_level': risk,
        'price': close,
    }


# ---------------- AI 生成与解析 ----------------

def _ai_configured() -> bool:
    from ..services.settings_service import ai_key_configured
    return ai_key_configured()


def _call_ai(prompt: str) -> list[dict] | None:
    """调用 DeepSeek（reasoner）返回 JSON 数组；失败返回 None"""
    from ..services.llm_client import chat
    from ..config import settings
    text = chat([{'role': 'user', 'content': prompt}],
                model=settings.model_reasoner, temperature=0.3, max_tokens=3000)
    fence = chr(96) * 3  # 移除可能的 markdown 代码围栏
    text = re.sub(rf'^s*{fence}jsons*|{fence}s*$', '', text.strip())
    data = json.loads(text)
    return data if isinstance(data, list) else None


def _sanitize_ai_item(item: dict, candidates_by_symbol: dict) -> dict | None:
    """校验 AI 单条输出；非法字段回退/丢弃"""
    symbol = str(item.get('symbol', '')).strip()
    cand = candidates_by_symbol.get(symbol)
    if not cand:
        return None
    rec_type = item.get('rec_type')
    if rec_type not in ('短线', '长线'):
        return None

    def f(v, default=None):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    entry_min = f(item.get('entry_min'))
    entry_max = f(item.get('entry_max'))
    stop_loss = f(item.get('stop_loss'))
    target = f(item.get('target'))
    val_min = f(item.get('valuation_min'))
    val_max = f(item.get('valuation_max'))
    confidence = int(f(item.get('confidence'), 60) or 60)
    confidence = max(0, min(100, confidence))
    risk = item.get('risk_level') if item.get('risk_level') in ('低', '中', '高') else '中'

    if rec_type == '短线':
        if not (entry_min and entry_max and entry_min > 0 and entry_max > entry_min):
            return None
        if stop_loss and stop_loss >= entry_min:
            stop_loss = None
        if target and target <= entry_max:
            target = None
    else:
        if not (val_min and val_max and val_min > 0 and val_max > val_min):
            return None
    return {
        'symbol': symbol, 'name': cand['name'], 'market': cand['market'], 'rec_type': rec_type,
        'entry_min': entry_min, 'entry_max': entry_max,
        'stop_loss': stop_loss, 'target': target,
        'valuation_min': val_min, 'valuation_max': val_max,
        'confidence': confidence,
        'logic': str(item.get('logic') or '')[:200] or ('AI 综合研判' + rec_type + '机会'),
        'risk_level': risk,
        'price': cand['price'],
    }


def _ai_entries(candidates: list[dict]) -> tuple[list[dict], str]:
    """AI 生成短线 + 长线条目；失败返回 ([], 'rules')"""
    if not _ai_configured():
        return [], 'rules'
    candidates_by_symbol = {c['symbol']: c for c in candidates}
    short_cands = [{
        'symbol': c['symbol'], 'name': c['name'], 'market': c['market'],
        'price': c['price'], 'change_pct': c['change_pct'],
        'vol_ratio': c['snap'].get('vol_ratio'),
        'breakout': c['snap'].get('breakout', {}).get('hit'),
        'ma_status': c['snap'].get('ma_status'),
        'dif': c['snap'].get('dif'), 'hist': c['snap'].get('hist'),
        'macd_golden_cross': c['snap'].get('macd_golden_cross'),
        'kdj_golden_cross': c['snap'].get('kdj_golden_cross'),
        'rsi14': c['snap'].get('rsi14'),
        'boll_pos': c['snap'].get('boll_pos'),
        'chg_5d': c['snap'].get('chg_pct_5d'),
        'news': c['news'],
    } for c in candidates]
    long_cands = [{
        'symbol': c['symbol'], 'name': c['name'], 'market': c['market'],
        'price': c['price'], 'pe': c['quote'].pe, 'pb': c['quote'].pb,
        'total_market_cap': c['quote'].total_market_cap,
        'weekly_trend': c['snap'].get('weekly_trend'),
        'monthly_trend': c['snap'].get('monthly_trend'),
        'ma_status': c['snap'].get('ma_status'),
        'chg_20d': c['snap'].get('chg_pct_20d'),
        'chg_60d': c['snap'].get('chg_pct_60d'),
    } for c in candidates]

    entries: list[dict] = []
    try:
        short_raw = _call_ai(build_short_prompt(short_cands))
        for it in short_raw or []:
            it['rec_type'] = '短线'
            e = _sanitize_ai_item(it, candidates_by_symbol)
            if e:
                entries.append(e)
        long_raw = _call_ai(build_long_prompt(long_cands))
        for it in long_raw or []:
            it['rec_type'] = '长线'
            e = _sanitize_ai_item(it, candidates_by_symbol)
            if e:
                entries.append(e)
    except Exception as e:  # noqa: BLE001
        logger.warning('AI 推荐失败，降级规则引擎: %s', str(e)[:120])
        return [], 'rules'
    if not entries:
        return [], 'rules'
    return entries, 'ai'


# ---------------- 主流程 ----------------

def _load_today(today: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, symbol, name, market, rec_type, entry_min, entry_max, stop_loss, target, "
            "valuation_min, valuation_max, confidence, logic, risk_level, rec_date, rec_price, status "
            "FROM recommendations WHERE rec_date = ? ORDER BY rec_type, id",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _save_entries(entries: list[dict], today: str) -> int:
    conn = get_connection()
    now = utc_now()
    try:
        conn.execute("DELETE FROM recommendations WHERE rec_date = ? AND status = 'open'", (today,))
        for e in entries:
            conn.execute(
                '''INSERT INTO recommendations
                (symbol, name, market, rec_type, entry_min, entry_max, stop_loss, target,
                 valuation_min, valuation_max, confidence, logic, risk_level, rec_date, rec_price, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)''',
                (e['symbol'], e['name'], e['market'], e['rec_type'],
                 e.get('entry_min'), e.get('entry_max'), e.get('stop_loss'), e.get('target'),
                 e.get('valuation_min'), e.get('valuation_max'),
                 e['confidence'], e['logic'], e['risk_level'], today, e['price'], now),
            )
        conn.commit()
        return len(entries)
    finally:
        conn.close()


def _notify(items: list[dict], source: str) -> None:
    from ..services.notification import send_notification
    n_short = sum(1 for it in items if it['rec_type'] == '短线')
    n_long = sum(1 for it in items if it['rec_type'] == '长线')
    content = (f'短线 {n_short} 条 / 长线 {n_long} 条（来源：{"AI" if source == "ai" else "规则引擎"}）'
               + chr(10) + '；'.join(f"{it['name']}({it['confidence']}%)" for it in items[:6]))
    try:
        send_notification('recommendation', '🎯 今日推荐已生成', content, level='提示', force=True)
    except Exception as e:  # noqa: BLE001
        logger.warning('推荐通知发送失败: %s', str(e)[:100])


def _macro_constraint(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """S14 宏观信号约束：🔴 暂停短线推荐；⚫ 暂停全部买入。
    无信号 / 🟢 / 🟡 不拦截，不破坏现有推荐流程。"""
    from ..services.settings_service import get_setting
    signal = get_setting('macro_signal') or {}
    level = signal.get('level')
    if level not in ('red', 'black'):
        return entries, []
    signal_text = signal.get('signal', level)
    blocked: list[dict] = []
    passed: list[dict] = []
    for e in entries:
        if level == 'black':
            blocked.append({
                'symbol': e.get('symbol'), 'name': e.get('name'),
                'rec_type': e.get('rec_type'),
                'reasons': [f'宏观信号 {signal_text}：系统性风险，暂停全部买入'],
            })
        elif level == 'red' and e.get('rec_type') == '短线':
            blocked.append({
                'symbol': e.get('symbol'), 'name': e.get('name'),
                'rec_type': e.get('rec_type'),
                'reasons': [f'宏观信号 {signal_text}：风险偏高，暂停短线推荐'],
            })
        else:
            passed.append(e)
    if blocked:
        logger.info('宏观信号 %s 拦截推荐 %d 条', signal_text, len(blocked))
    return passed, blocked


def generate_recommendations(force: bool = False) -> dict:
    """生成当日推荐。force=False 且当日已有推荐时直接返回缓存结果。

    返回：{ok, date, cached, source, items, blocked, errors}
    """
    profile = _load_profile()
    today = date.today().isoformat()

    if not force:
        existing = _load_today(today)
        if existing:
            return {'ok': True, 'date': today, 'cached': True,
                    'source': 'ai' if any('AI' in (it.get('logic') or '') for it in existing) else 'rules',
                    'items': existing, 'blocked': [], 'errors': []}

    candidates = _candidate_pool(profile)
    holdings = _load_holdings()
    enriched: list[dict] = []
    errors: list[str] = []
    for cand in candidates:
        try:
            quote = data_fusion.get_quote(cand['symbol'], cand['market'])
            if quote is None:
                errors.append(f"{cand['symbol']}：行情获取失败")
                continue
            bars = data_fusion.get_kline(cand['symbol'], cand['market'], 120)
            if not bars:
                errors.append(f"{cand['symbol']}：K线获取失败")
                continue
            snap = indicator_snapshot(bars)
            if not snap:
                errors.append(f"{cand['symbol']}：指标计算失败")
                continue
            enriched.append({
                'symbol': cand['symbol'], 'name': quote.name or cand['name'],
                'market': cand['market'], 'price': float(quote.price),
                'change_pct': quote.change_pct,
                'quote': quote, 'snap': snap,
                'news': _related_news(quote.name or cand['name'], cand['symbol']),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning('候选股 %s 分析失败: %s', cand['symbol'], str(e)[:100])
            errors.append(f"{cand['symbol']}：{str(e)[:60]}")

    # 1) 规则引擎保底
    rule_entries: list[dict] = []
    for c in enriched:
        s = _short_rule(c['symbol'], c['name'], c['market'], c['quote'], c['snap'])
        if s:
            rule_entries.append(s)
        l = _long_rule(c['symbol'], c['name'], c['market'], c['quote'], c['snap'])
        if l:
            rule_entries.append(l)

    # 2) AI 生成（失败降级规则）
    ai_entries, source = _ai_entries(enriched)
    if ai_entries:
        by_key = {(e['symbol'], e['rec_type']): e for e in ai_entries}
        for r in rule_entries:
            by_key.setdefault((r['symbol'], r['rec_type']), r)
        merged = list(by_key.values())
    else:
        merged = rule_entries

    # 3) 约束过滤
    result = apply_constraints(merged, profile, holdings)

    # 4) 宏观信号约束（S14）：🔴 暂停短线 / ⚫ 暂停全部买入
    macro_passed, macro_blocked = _macro_constraint(result['passed'])
    result['passed'] = macro_passed
    result['blocked'] = result['blocked'] + macro_blocked

    saved = _save_entries(result['passed'], today) if result['passed'] else 0
    if saved:
        _notify(result['passed'], source)
    logger.info('推荐生成完成: 候选 %d → 规则 %d / AI %s → 通过约束 %d / 拦截 %d',
                len(enriched), len(rule_entries), source, saved, len(result['blocked']))

    return {
        'ok': True,
        'date': today,
        'cached': False,
        'source': source,
        'items': _load_today(today),
        'blocked': result['blocked'],
        'errors': errors,
    }
