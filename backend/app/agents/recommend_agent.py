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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
MIN_POOL_SIZE = 8   # 候选池最少数量（自选股不足时用蓝筹兜底补足，避免候选太少导致空推荐）

# V1.0.9：按用户意愿推荐——行业意图词典（关键词 → 候选股票，A股+港股）
INDUSTRY_POOLS: list[dict] = [
    {'name': '白酒/酒类', 'keywords': ['白酒', '酒类', '酿酒', '酒股', '喝酒', '茅台', '五粮液', '汾酒'],
     'stocks': [('600519', '贵州茅台', 'A股'), ('000858', '五粮液', 'A股'), ('000568', '泸州老窖', 'A股'),
                ('600809', '山西汾酒', 'A股'), ('002304', '洋河股份', 'A股'), ('603369', '今世缘', 'A股')]},
    {'name': '科技/半导体', 'keywords': ['科技', '半导体', '芯片', '集成电路', '软件', '科技股', '科创'],
     'stocks': [('688981', '中芯国际', 'A股'), ('603501', '韦尔股份', 'A股'), ('688041', '海光信息', 'A股'),
                ('002371', '北方华创', 'A股'), ('688256', '寒武纪', 'A股'), ('300661', '圣邦股份', 'A股')]},
    {'name': '互联网/港股科技', 'keywords': ['互联网', '港股科技', '腾讯', '阿里', '美团', '电商', '平台'],
     'stocks': [('00700', '腾讯控股', '港股'), ('09988', '阿里巴巴', '港股'), ('03690', '美团', '港股'),
                ('01810', '小米集团', '港股'), ('09618', '京东集团', '港股'), ('01024', '快手', '港股')]},
    {'name': '银行', 'keywords': ['银行', '银行业', '银行股', '高股息', '红利'],
     'stocks': [('600036', '招商银行', 'A股'), ('601398', '工商银行', 'A股'), ('601288', '农业银行', 'A股'),
                ('601988', '中国银行', 'A股'), ('600000', '浦发银行', 'A股')]},
    {'name': '券商/金融', 'keywords': ['券商', '证券', '金融', '保险', '炒股软件'],
     'stocks': [('600030', '中信证券', 'A股'), ('300059', '东方财富', 'A股'), ('601688', '华泰证券', 'A股'),
                ('601318', '中国平安', 'A股'), ('601601', '中国太保', 'A股')]},
    {'name': '新能源车/锂电', 'keywords': ['新能源车', '新能源汽车', '电动车', '锂电', '电池', '汽车'],
     'stocks': [('300750', '宁德时代', 'A股'), ('002594', '比亚迪', 'A股'), ('300014', '亿纬锂能', 'A股'),
                ('002460', '赣锋锂业', 'A股'), ('601633', '长城汽车', 'A股'), ('000625', '长安汽车', 'A股')]},
    {'name': '光伏', 'keywords': ['光伏', '太阳能', '储能'],
     'stocks': [('601012', '隆基绿能', 'A股'), ('600438', '通威股份', 'A股'), ('688223', '晶科能源', 'A股'),
                ('300274', '阳光电源', 'A股')]},
    {'name': '医药', 'keywords': ['医药', '医疗', '制药', '创新药', '药企', '疫苗'],
     'stocks': [('600276', '恒瑞医药', 'A股'), ('300760', '迈瑞医疗', 'A股'), ('603259', '药明康德', 'A股'),
                ('600196', '复星医药', 'A股')]},
    {'name': '消费/家电', 'keywords': ['消费', '白酒以外', '家电', '食品', '饮料', '乳业', '白马'],
     'stocks': [('600887', '伊利股份', 'A股'), ('603288', '海天味业', 'A股'), ('000333', '美的集团', 'A股'),
                ('000651', '格力电器', 'A股'), ('600690', '海尔智家', 'A股')]},
    {'name': '军工', 'keywords': ['军工', '国防', '航天', '航空制造', '船舶'],
     'stocks': [('600760', '中航沈飞', 'A股'), ('002179', '中航光电', 'A股'), ('600893', '航发动力', 'A股'),
                ('000768', '中航西飞', 'A股')]},
    {'name': '人工智能/AI', 'keywords': ['人工智能', 'AI', '智能', '大模型', '机器人'],
     'stocks': [('688256', '寒武纪', 'A股'), ('300308', '中际旭创', 'A股'), ('300502', '新易盛', 'A股'),
                ('300394', '天孚通信', 'A股'), ('688017', '绿的谐波', 'A股')]},
    {'name': '算力/光模块', 'keywords': ['算力', '光模块', '光通信', 'CPO', '服务器', '数据中心'],
     'stocks': [('300308', '中际旭创', 'A股'), ('300502', '新易盛', 'A股'), ('002281', '光迅科技', 'A股'),
                ('688041', '海光信息', 'A股'), ('000977', '浪潮信息', 'A股')]},
    {'name': '黄金/有色', 'keywords': ['黄金', '有色', '铜', '稀土', '矿业'],
     'stocks': [('601899', '紫金矿业', 'A股'), ('600547', '山东黄金', 'A股'), ('600988', '赤峰黄金', 'A股'),
                ('000630', '铜陵有色', 'A股')]},
    {'name': '地产', 'keywords': ['地产', '房地产', '房产', '物业'],
     'stocks': [('000002', '万科A', 'A股'), ('600048', '保利发展', 'A股'), ('001979', '招商蛇口', 'A股')]},
    {'name': '电力/公用', 'keywords': ['电力', '公用事业', '水电', '核电', '燃气'],
     'stocks': [('600900', '长江电力', 'A股'), ('601985', '中国核电', 'A股'), ('600886', '国投电力', 'A股')]},
    {'name': '能源/石油', 'keywords': ['石油', '煤炭', '能源', '油气', '石化'],
     'stocks': [('601857', '中国石油', 'A股'), ('600028', '中国石化', 'A股'), ('601088', '中国神华', 'A股')]},
    {'name': '航空', 'keywords': ['航空', '民航', '机场', '出行'],
     'stocks': [('600029', '南方航空', 'A股'), ('601111', '中国国航', 'A股'), ('600115', '东方航空', 'A股')]},
]


def resolve_intent_pool(intent: str) -> list[dict]:
    """解析用户意愿文本（如「酒类和科技股」）→ 候选股票池（按意图组去重合并，上限 MAX_CANDIDATES）"""
    text = (intent or '').strip()
    if not text:
        return []
    text_l = text.lower()
    seen: dict[tuple, dict] = {}
    hits: list[str] = []
    for group in INDUSTRY_POOLS:
        if any(kw.lower() in text_l for kw in group['keywords']):
            hits.append(group['name'])
            for sym, name, mkt in group['stocks']:
                seen.setdefault((sym, mkt), {'symbol': sym, 'name': name, 'market': mkt})
    if not seen:
        return []
    logger.info('用户意愿解析命中行业: %s', '、'.join(hits))
    return list(seen.values())[:MAX_CANDIDATES]


def _load_profile() -> dict:
    from ..services.profile_service import get_profile
    return get_profile()


def _load_holdings() -> list[dict]:
    from ..services.portfolio_sync import get_mode
    src = 'portfolio_app' if get_mode() == 'snapshot' else 'manual'
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT symbol, name, market FROM holdings WHERE source = ?', (src,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _candidate_pool(profile: dict, intent: str = '') -> list[dict]:
    """候选池（V1.0.9）：
    1. 用户指定意愿（intent）→ 行业词典解析出的股票优先；
    2. 否则用自选股（按画像市场过滤）；
    3. 数量不足 MIN_POOL_SIZE 时用蓝筹兜底池补足（避免候选太少导致空推荐）。"""
    markets = [m for m in (profile.get('markets') or []) if m in ('A股', '港股')]
    if not markets:
        markets = ['A股']

    pool: list[dict] = []
    seen: set[tuple] = set()

    def _add(c: dict) -> None:
        k = (c['symbol'], c.get('market', ''))
        if k not in seen and c.get('market') in markets:
            seen.add(k)
            pool.append(c)

    # 1) 用户意愿（intent）优先
    if (intent or '').strip():
        for c in resolve_intent_pool(intent):
            _add(c)

    # 2) 自选股
    if len(pool) < MIN_POOL_SIZE:
        conn = get_connection()
        try:
            rows = conn.execute(
                'SELECT symbol, name, market FROM watchlist ORDER BY group_name, sort_order, id'
            ).fetchall()
        finally:
            conn.close()
        for r in rows:
            _add(dict(r))

    # 3) 蓝筹兜底补足到 MIN_POOL_SIZE
    if len(pool) < MIN_POOL_SIZE:
        for c in DEFAULT_CANDIDATES:
            _add(dict(c))
    if not pool:  # 极端情况（市场偏好不含兜底池时）
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
    fence = chr(96) * 3  # 移除可能的 markdown 代码围栏（围栏前后允许任意空白）
    text = re.sub(rf'^\s*{fence}json\s*', '', text.strip())
    text = re.sub(rf'{fence}\s*$', '', text)
    # 模型输出若带解释前缀，提取首个 [ 或 { 起的内容（容错）
    text = text.strip()
    if not text.startswith(('[', '{')):
        idxs = [i for i in (text.find('['), text.find('{')) if i >= 0]
        if idxs:
            text = text[min(idxs):]
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
    """AI 生成短线 + 长线条目。
    返回状态：'ai'=AI成功且有条目；'ai_empty'=AI成功但认为无合适标的；'rules'=未配置/调用失败降级"""
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
    ai_ok = True
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
        ai_ok = False
        logger.warning('AI 推荐失败，降级规则引擎: %s', str(e)[:120])
    if entries:
        return entries, 'ai'
    # AI 调用成功但未给出标的（正常业务判断）→ ai_empty；调用失败/未配置 → rules
    return [], ('ai_empty' if ai_ok else 'rules')


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


def generate_recommendations(force: bool = False, intent: str = '') -> dict:
    """生成当日推荐（V1.0.9 支持按用户意愿 intent）。
    force=False 且当日已有推荐时直接返回缓存结果（intent 为空时读取缓存；指定 intent 强制按新意愿重算）。

    返回：{ok, date, cached, source, intent, items, blocked, errors}
    source: ai=AI生成 ai_empty=AI已分析但无合适标的 rules=规则引擎（AI不可用降级）
    """
    profile = _load_profile()
    today = date.today().isoformat()
    intent = (intent or '').strip()

    # 记录本次意愿（供 today/cached 响应回显；空意愿则清除）
    _save_intent(intent, today)

    if not force and not intent:
        existing = _load_today(today)
        if existing:
            return {'ok': True, 'date': today, 'cached': True,
                    'source': 'ai' if any('AI' in (it.get('logic') or '') for it in existing) else 'rules',
                    'items': existing, 'blocked': [], 'errors': [],
                    'candidate_count': 0, 'pool_size': 0, 'empty_reason': None,
                    'intent': _load_intent()}

    candidates = _candidate_pool(profile, intent)
    holdings = _load_holdings()
    enriched: list[dict] = []
    errors: list[str] = []

    def _enrich_one(cand: dict) -> tuple[dict | None, str | None]:
        """单只候选分析（供并行执行）"""
        try:
            quote = data_fusion.get_quote(cand['symbol'], cand['market'])
            if quote is None:
                return None, f"{cand['symbol']}：行情获取失败"
            bars = data_fusion.get_kline(cand['symbol'], cand['market'], 120)
            if not bars:
                return None, f"{cand['symbol']}：K线获取失败"
            snap = indicator_snapshot(bars)
            if not snap:
                return None, f"{cand['symbol']}：指标计算失败"
            return {
                'symbol': cand['symbol'], 'name': quote.name or cand['name'],
                'market': cand['market'], 'price': float(quote.price),
                'change_pct': quote.change_pct,
                'quote': quote, 'snap': snap,
                'news': _related_news(quote.name or cand['name'], cand['symbol']),
            }, None
        except Exception as e:  # noqa: BLE001
            logger.warning('候选股 %s 分析失败: %s', cand['symbol'], str(e)[:100])
            return None, f"{cand['symbol']}：{str(e)[:60]}"

    # D: 并行拉取行情与 K 线（串行 23s -> 并行 ~5s）
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(candidates)))) as ex:
        futures = {ex.submit(_enrich_one, cand): cand for cand in candidates}
        for fut in as_completed(futures):
            entry, err = fut.result()
            if entry is not None:
                enriched.append(entry)
            elif err:
                errors.append(err)

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

    # 最终来源语义（V1.0.9 三态）：
    # ai = AI 产出条目；rules = AI 不可用降级规则产出（或仅规则条目）；ai_empty = AI 正常但无合适标的
    if ai_entries:
        final_source = 'ai'
    elif merged:
        final_source = 'rules'
    elif source == 'ai_empty':
        final_source = 'ai_empty'
    else:
        final_source = 'rules'

    saved = _save_entries(result['passed'], today) if result['passed'] else 0
    if saved:
        _notify(result['passed'], final_source)
    logger.info('推荐生成完成: 候选 %d → 规则 %d / AI %s(最终%s) → 通过约束 %d / 拦截 %d',
                len(enriched), len(rule_entries), source, final_source, saved, len(result['blocked']))

    # 无推荐时的可读原因（供前端展示）
    empty_reason = None
    if not result['passed']:
        if not enriched:
            empty_reason = ('候选股票行情获取全部失败，未能完成分析' if errors
                            else '候选池为空（自选股未添加且无可用兜底），无法生成推荐')
        elif final_source == 'ai_empty':
            empty_reason = (f'AI 已分析 {len(enriched)} 只候选（{_load_intent() or "未指定范围"}），'
                            '当前均未达到推荐标准——这是正常结果，可换个行业范围或改天再试')
        elif rule_entries and result['blocked']:
            empty_reason = f'分析了 {len(enriched)} 只候选：{len(rule_entries)} 条初选全部被约束规则拦截'
        else:
            empty_reason = f'分析了 {len(enriched)} 只候选股票，均未达到推荐标准（技术/估值评分不足），今日不生成推荐'

    return {
        'ok': True,
        'date': today,
        'cached': False,
        'source': final_source,
        'intent': _load_intent(),
        'items': _load_today(today),
        'blocked': result['blocked'],
        'errors': errors,
        'candidate_count': len(enriched),
        'pool_size': len(candidates),
        'empty_reason': empty_reason,
    }


INTENT_KEY = 'recommend_intent_today'


def _save_intent(intent: str, today: str) -> None:
    """记录当日生成意愿（intent 为空则清除）"""
    from ..services.settings_service import set_setting
    try:
        if intent:
            set_setting(INTENT_KEY, json.dumps({'intent': intent, 'date': today}, ensure_ascii=False))
        else:
            set_setting(INTENT_KEY, '')
    except Exception as e:  # noqa: BLE001
        logger.warning('意愿记录失败: %s', str(e)[:100])


def _load_intent() -> str:
    """最近一次生成意愿文本（供前端回显「本次范围」）"""
    from ..services.settings_service import get_setting
    try:
        v = get_setting(INTENT_KEY) or ''
        if isinstance(v, dict):
            return str(v.get('intent') or '')
        return str(v or '')
    except Exception:  # noqa: BLE001
        return ''
