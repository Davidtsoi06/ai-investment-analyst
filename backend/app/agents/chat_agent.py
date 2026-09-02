# -*- coding: utf-8 -*-
"""S13 智能问答 Agent：问题分类 → 上下文构建（实时行情/技术指标/用户画像/持仓/资讯）
→ DeepSeek 回答（无 Key 或失败自动降级规则模板）→ 对话历史落库（chat_history）

回答一律基于提供的数据，并说明数据时间与免责声明。
"""

import json
import re

from ..data_sources.market.data_fusion import data_fusion
from ..models.database import get_connection, utc_now
from ..services.indicators import indicator_snapshot
from ..services.logger import get_agent_logger
from ..services.profile_service import get_profile
from ..utils.prompts.chat_prompt import build_chat_messages

logger = get_agent_logger()

DISCLAIMER = '以上内容仅供参考，不构成投资建议。'

# ---------------- 问题分类（关键词规则） ----------------

# (类别, 关键词列表)：按优先级从上到下，命中即返回
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ('对比分析', ['对比', '比较', '哪个更好', '哪个好', '哪只好', 'vs', 'VS', '区别']),
    ('持仓诊断', ['我的持仓', '持仓', '我的股票', '我买的', '被套', '亏了', '要不要卖', '该不该卖']),
    ('行业分析', ['行业', '板块', '赛道', '概念股', '产业链']),
    ('策略', ['大盘', '策略', '该不该买', '买点', '卖点', '后市', '牛市', '熊市', '仓位', '抄底', '追高']),
    ('数据查询', ['pe', 'PE', '市盈率', 'roe', 'ROE', '市净率', 'pb', 'PB', '市值', '换手率', '成交量', '是多少', '多少']),
]

# 常见 A 股名称 → 代码（离线兜底；用户持仓名称优先匹配，见 _extract_symbols）
COMMON_STOCKS: dict[str, str] = {
    '贵州茅台': '600519', '五粮液': '000858', '宁德时代': '300750', '招商银行': '600036',
    '中国平安': '601318', '比亚迪': '002594', '隆基绿能': '601012', '药明康德': '603259',
    '美的集团': '000333', '格力电器': '000651', '海天味业': '603288', '伊利股份': '600887',
    '工商银行': '601398', '建设银行': '601939', '农业银行': '601288', '中国银行': '601988',
    '中信证券': '600030', '东方财富': '300059', '万科A': '000002', '保利发展': '600048',
    '恒瑞医药': '600276', '迈瑞医疗': '300760', '中芯国际': '688981', '韦尔股份': '603501',
    '紫金矿业': '601899', '赣锋锂业': '002460', '天齐锂业': '002466', '通威股份': '600438',
    '阳光电源': '300274', '汇川技术': '300124', '海康威视': '002415', '立讯精密': '002475',
    '京东方A': '000725', '三一重工': '600031', '中国中免': '601888', '长江电力': '600900',
}


def classify_question(question: str) -> str:
    """关键词规则分类：对比/持仓诊断/行业/策略/数据查询；默认按是否识别到股票返回 个股分析/综合"""
    for category, keywords in CATEGORY_RULES:
        if any(kw in question for kw in keywords):
            return category
    return '个股分析' if _extract_symbols(question) else '综合'


def _load_holding_rows() -> list[dict]:
    """持仓原始行（名称/代码/市场/成本）"""
    conn = get_connection()
    try:
        from ..services.portfolio_sync import get_mode
        src = 'portfolio_app' if get_mode() == 'snapshot' else 'manual'
        rows = conn.execute(
            'SELECT symbol, name, market, quantity, cost_price, current_price FROM holdings WHERE source = ? ORDER BY market, symbol',
            (src,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _extract_symbols(question: str, allow_external: bool = False) -> list[dict]:
    """识别问题中的股票：6 位 A 股代码 / 5 位港股代码 / 持仓名称 / 常见股票名称；
    allow_external=True 且本地无命中时，主动搜索外部行情源（东财 suggest，#8）"""
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(symbol: str, name: str, market: str) -> None:
        key = (market, symbol)
        if key not in seen:
            seen.add(key)
            found.append({'symbol': symbol, 'name': name, 'market': market})

    for code in re.findall(r'(?<!\d)\d{6}(?!\d)', question):
        _add(code, '', 'A股')
    for code in re.findall(r'(?<!\d)\d{5}(?!\d)', question):
        _add(code, '', '港股')

    holding_names = {h['name']: h for h in _load_holding_rows()}
    for name, h in holding_names.items():
        if name and name in question:
            _add(h['symbol'], h['name'], h['market'])
    for name, code in COMMON_STOCKS.items():
        if name in question:
            _add(code, name, 'A股')

    # #8：本地无命中（非持仓/非常见股）时主动搜索外部，避免「无相关数据」式空答
    if allow_external and not found:
        for s in _search_external(question):
            _add(s['symbol'], s['name'], s['market'])
    return found


# ---------------- 外部搜索（#8：非持仓股票主动识别） ----------------

_NAME_LEADS = (
    '帮我看看', '帮忙看看', '帮我分析', '帮忙分析', '帮我查查', '帮我查', '想问问', '想了解',
    '想查查', '请问', '查一下', '看下', '看一下', '了解下', '了解', '分析下', '分析一下',
    '介绍下', '说下', '讲讲', '评价下', '问下', '咨询下', '有没有',
)
_STOCK_SUFFIX = (
    '怎么样', '如何', '可以买吗', '能买吗', '值得买吗', '值得买', '买不买', '该不该买',
    '该不该卖', '要不要卖', '什么情况', '怎么看', '走势如何', '后市如何', '后市', '还能买吗',
    '还能买', '还能拿吗', '还能涨吗', '现在能买', '现在买', '可以买', '适合买', '贵不贵',
    '有没有投资价值', '这只股票', '这股票', '这只票', '这票', '股票怎么样', '表现如何',
    '行情如何', '基本面', '估值', '财报', '业绩',
)


def _guess_stock_keywords(question: str) -> list[str]:
    """从问句提取「股票名」候选（中文 2~10 字后紧跟意图词），如：
    『帮我看看小米集团怎么样』→ ['小米集团']；『比亚迪现在能买吗』→ ['比亚迪']"""
    q = question.strip()
    for lead in _NAME_LEADS:
        if q.startswith(lead):
            q = q[len(lead):]
            break
    suffix_pat = '|'.join(_STOCK_SUFFIX)
    out: list[str] = []
    for m in re.finditer(r'([一-龥A-Za-z]{2,10}?)(?=' + suffix_pat + ')', q):
        kw = m.group(1).strip()
        # 过滤通用词（非股票名）
        if kw in ('怎么', '什么', '可以', '现在', '今天', '最近', '还有', '应该', '没有', '这个'):
            continue
        if any(lead in kw for lead in ('帮我', '请问', '看看', '分析')):
            continue
        if kw not in out:
            out.append(kw)
    return out[:3]


def _search_external(question: str) -> list[dict]:
    """东财 suggest 名称→代码兜底搜索（网络失败静默返回空，不阻塞主流程）"""
    try:
        from ..data_sources.market.stock_search import search_stocks, normalize_name
        results: list[dict] = []
        for kw in _guess_stock_keywords(question):
            for s in search_stocks(kw, 3):
                nm = normalize_name(s.get('name') or '') or s.get('name') or ''
                # 结果名称必须与问句相关（名称出现在问句中，或关键词出现在结果名中）
                if kw in question and (kw in nm or nm in question or s.get('symbol') in question):
                    results.append(s)
        seen: set[tuple[str, str]] = set()
        dedup: list[dict] = []
        for s in results:
            k = (s.get('market'), s.get('symbol'))
            if k not in seen:
                seen.add(k)
                dedup.append(s)
        if dedup:
            logger.info('外部搜索识别到股票: %s', '、'.join(f"{s['name']}({s['symbol']})" for s in dedup))
        return dedup[:3]
    except Exception as e:  # noqa: BLE001
        logger.warning('外部股票搜索兜底失败: %s', str(e)[:100])
        return []


# ---------------- 上下文构建 ----------------

def _quote_of(symbol: str, market: str) -> dict | None:
    """实时行情（数据源失败返回 None）"""
    try:
        q = data_fusion.get_quote(symbol, market)
    except Exception as e:  # noqa: BLE001
        logger.warning('行情获取失败 %s/%s: %s', market, symbol, str(e)[:80])
        return None
    if q is None:
        return None
    return {
        'symbol': q.symbol,
        'name': q.name or symbol,
        'market': q.market,
        'price': q.price,
        'change_pct': q.change_pct,
        'change': q.change,
        'turnover': q.turnover,
        'pe': q.pe,
        'pb': q.pb,
        'total_market_cap': q.total_market_cap,
        'timestamp': q.timestamp,
        'source': q.source,
    }


def _kline_summary_of(symbol: str, market: str) -> dict | None:
    """日 K → 技术指标摘要（MA/MACD/RSI/量能/趋势）。
    拉 60 根保证 MACD(26,9)/RSI(14) 等有足够预热期，摘要只取最新值"""
    try:
        bars = data_fusion.get_kline(symbol, market, 60)
    except Exception as e:  # noqa: BLE001
        logger.warning('K线获取失败 %s/%s: %s', market, symbol, str(e)[:80])
        return None
    if not bars:
        return None
    snap = indicator_snapshot(bars)
    if not snap:
        return None
    return {
        'date': snap.get('date'),
        'close': snap.get('close'),
        'chg_pct_5d': snap.get('chg_pct_5d'),
        'chg_pct_20d': snap.get('chg_pct_20d'),
        'ma5': snap.get('ma5'),
        'ma10': snap.get('ma10'),
        'ma20': snap.get('ma20'),
        'ma_status': snap.get('ma_status'),
        'macd': {'dif': snap.get('dif'), 'dea': snap.get('dea'), 'hist': snap.get('hist'),
                 'golden_cross': snap.get('macd_golden_cross')},
        'rsi14': snap.get('rsi14'),
        'kdj': {'k': snap.get('kdj_k'), 'd': snap.get('kdj_d'), 'j': snap.get('kdj_j')},
        'boll_pos': snap.get('boll_pos'),
        'vol_ratio': snap.get('vol_ratio'),
        'weekly_trend': snap.get('weekly_trend'),
        'monthly_trend': snap.get('monthly_trend'),
    }


def _load_holdings_with_pnl() -> list[dict]:
    """持仓 + 实时行情（名称/代码/盈亏%）：行情失败时 price/pnl 为 None"""
    result: list[dict] = []
    for h in _load_holding_rows():
        q = _quote_of(h['symbol'], h['market'])
        if q is None:
            result.append({'symbol': h['symbol'], 'name': h['name'], 'market': h['market'],
                           'price': None, 'change_pct': None, 'pnl_pct': None})
            continue
        price = float(q['price'])
        pnl = None
        cost = float(h.get('cost_price') or 0)
        if cost > 0:
            pnl = round((price / cost - 1) * 100, 2)
        result.append({'symbol': h['symbol'], 'name': h['name'], 'market': h['market'],
                       'price': price, 'change_pct': round(float(q['change_pct'] or 0), 2),
                       'pnl_pct': pnl})
    return result


def _load_news(limit: int = 5) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT title, source, level, summary, published_at FROM news_cache ORDER BY id DESC LIMIT ?',
            (min(limit, 20),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def build_context(question: str) -> dict:
    """构建问答上下文：问题分类 + 识别股票（行情/指标摘要，含外部搜索兜底）+ 用户画像 + 持仓 + 最近资讯"""
    category = classify_question(question)
    symbols = _extract_symbols(question, allow_external=True)
    # 外部搜索兜底命中具体股票时，把笼统分类细化为个股分析（降级回答可输出行情）
    if category == '综合' and symbols:
        category = '个股分析'
    symbol_ctx: list[dict] = []
    for s in symbols:
        symbol_ctx.append({
            'symbol': s['symbol'],
            'name': s['name'],
            'market': s['market'],
            'quote': _quote_of(s['symbol'], s['market']),
            'kline_summary': _kline_summary_of(s['symbol'], s['market']),
        })
    profile = get_profile()
    holdings = _load_holdings_with_pnl()
    news = _load_news(5)
    return {
        'category': category,
        'symbols': symbol_ctx,
        'profile': {k: profile.get(k) for k in ('risk_tolerance', 'invest_amount', 'markets', 'holding_period', 'experience')},
        'holdings': holdings,
        'news': news,
    }


# ---------------- 降级回答（规则模板） ----------------

def _fmt_quote(q: dict) -> str:
    name = q.get('name') or q.get('symbol')
    mcap = q.get('total_market_cap')
    mcap_txt = f'{mcap / 1e8:.0f} 亿元' if mcap else '—'
    return (f"{name}（{q.get('symbol')}，{q.get('market')}）：最新价 {q.get('price')} 元，"
            f"涨跌幅 {q.get('change_pct')}%，换手率 {q.get('turnover')}%，"
            f"PE(TTM) {q.get('pe') or '—'}，总市值 {mcap_txt}")


def _fmt_kline(ks: dict) -> str:
    if not ks:
        return '技术指标：暂无K线数据'
    return (f"技术指标（截至 {ks.get('date')}）：MA5={ks.get('ma5')} MA20={ks.get('ma20')}（{ks.get('ma_status')}），"
            f"MACD DIF={ks.get('macd', {}).get('dif')} DEA={ks.get('macd', {}).get('dea')}，"
            f"RSI14={ks.get('rsi14')}，量比={ks.get('vol_ratio')}，"
            f"周线趋势={ks.get('weekly_trend')}，月线趋势={ks.get('monthly_trend')}，"
            f"近5日涨跌 {ks.get('chg_pct_5d')}%，近20日涨跌 {ks.get('chg_pct_20d')}%")


def _rule_answer(ctx: dict, ai_unavailable_reason: str) -> str:
    """无 Key / AI 调用失败时的规则降级回答（按分类返回基础答案）"""
    cat = ctx['category']
    head = f'【{cat}｜{ai_unavailable_reason}】'
    lines = [head]
    symbols = ctx.get('symbols') or []
    holdings = ctx.get('holdings') or []
    news = ctx.get('news') or []

    if cat == '数据查询' and symbols:
        for s in symbols:
            if s.get('quote'):
                lines.append('· ' + _fmt_quote(s['quote']))
                lines.append('· ' + _fmt_kline(s.get('kline_summary')))
            else:
                lines.append(f"· {s['symbol']}（{s['market']}）：行情数据暂不可用")
    elif cat == '个股分析' and symbols:
        for s in symbols:
            if s.get('quote'):
                lines.append('· ' + _fmt_quote(s['quote']))
                lines.append('· ' + _fmt_kline(s.get('kline_summary')))
            else:
                lines.append(f"· {s['symbol']}（{s['market']}）：行情数据暂不可用")
    elif cat == '持仓诊断':
        if holdings:
            lines.append(f'当前持仓 {len(holdings)} 只：')
            for h in holdings:
                pnl = f"{h['pnl_pct']:+.2f}%" if h.get('pnl_pct') is not None else '—'
                lines.append(f"· {h['name']}（{h['symbol']}）：现价 {h.get('price') or '—'}，盈亏 {pnl}")
            lines.append('通用建议：盈利仓位注意分批止盈与回撤保护；亏损仓位结合成本、行业逻辑与仓位占比决定去留，避免单只集中度过高。')
        else:
            lines.append('当前暂无持仓记录。')
    elif cat == '对比分析':
        if symbols:
            for s in symbols:
                if s.get('quote'):
                    lines.append('· ' + _fmt_quote(s['quote']))
                    lines.append('· ' + _fmt_kline(s.get('kline_summary')))
                else:
                    lines.append(f"· {s['symbol']}（{s['market']}）：行情数据暂不可用")
            lines.append('以上为各标的实时数据对比。可配置 AI Key 后获得深度对比分析（估值、业绩、行业地位等）。')
        else:
            lines.append('未识别到具体股票代码或名称。')
    else:
        # 行业分析 / 策略 / 综合
        if holdings:
            lines.append(f'当前持仓 {len(holdings)} 只：' + '、'.join(h['name'] for h in holdings))
        if symbols:
            lines.append('涉及标的：' + '、'.join(f"{s['symbol']}（{s['market']}）" for s in symbols))
        if news:
            lines.append('最近相关资讯：')
            for n in news[:3]:
                lines.append(f"· [{n.get('level') or '一般'}] {n.get('title')}")
        if not holdings and not symbols and not news:
            lines.append('当前无可用本地数据。')

    lines.append('数据说明：行情/指标为最近交易日或实时快照，资讯为本地缓存最新条目；' + DISCLAIMER)
    return '\n'.join(lines)


# ---------------- 主入口 ----------------

def ask(question: str) -> dict:
    """问答主入口：构建上下文 → AI 或降级回答 → 历史落库。
    返回 {answer, category, used_data, degraded}"""
    question = (question or '').strip()
    ctx = build_context(question)
    used_data = {
        'quotes': [s['quote'] for s in ctx['symbols'] if s.get('quote')] or None,
        'kline_summary': {s['symbol']: s['kline_summary'] for s in ctx['symbols'] if s.get('kline_summary')} or None,
        'holdings': ctx['holdings'],
        'news': ctx['news'],
    }
    degraded = True
    answer = ''
    try:
        from ..services.llm_client import chat
        from ..services.settings_service import ai_key_configured
        if ai_key_configured():
            messages = build_chat_messages(question, ctx)
            answer = chat(messages, temperature=0.5, max_tokens=1200)
            answer = (answer or '').strip()
            if answer:
                degraded = False
    except Exception as e:  # noqa: BLE001
        logger.warning('AI 回答失败，降级规则: %s', str(e)[:120])
    if not answer:
        reason = '未配置有效 AI Key 或 AI 服务暂不可用'
        answer = _rule_answer(ctx, reason)
        degraded = True

    save_history(question, ctx['category'], answer, used_data, degraded)
    return {'answer': answer, 'category': ctx['category'], 'used_data': used_data, 'degraded': degraded}


def save_history(question: str, category: str, answer: str, used_data: dict, degraded: bool) -> int:
    """保存一次问答到 chat_history；返回新记录 id"""
    conn = get_connection()
    try:
        cur = conn.execute(
            'INSERT INTO chat_history (question, category, answer, used_data_json, degraded, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (question, category, answer, json.dumps(used_data, ensure_ascii=False), 1 if degraded else 0, utc_now()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_history(limit: int = 30) -> list[dict]:
    """对话历史（按时间倒序）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT id, question, category, answer, used_data_json, degraded, created_at '
            'FROM chat_history ORDER BY id DESC LIMIT ?',
            (min(limit, 100),),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d['used_data'] = json.loads(d.pop('used_data_json') or '{}')
        except (ValueError, TypeError):
            d['used_data'] = {}
        d['degraded'] = bool(d.get('degraded'))
        out.append(d)
    return out
