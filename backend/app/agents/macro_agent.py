# -*- coding: utf-8 -*-
"""S14 宏观研判 Agent：全球（yfinance）+ 中国（东财）+ 市场情绪（快照）+ 四色信号

数据源（免费接口，单指标失败降级不影响整体）：
  - 全球：yfinance ^VIX 恐慌指数 / DX-Y.NYB 美元指数 / CL=F 原油 / GC=F 黄金
  - 中国：东财数据中心 RPT_ECONOMY_CPI / RPT_ECONOMY_PMI（全部不可用则 source='unavailable'）
  - 情绪：snapshot_client 涨跌家数 + 沪深两市成交额

四色信号判定（优先级：⚫ > 🔴 > 🟡 > 🟢）：
  - ⚫ 系统性风险：VIX≥40 或 原油单日>5%
  - 🔴 风险偏高：VIX≥30
  - 🟡 中性偏谨慎：VIX≥25 或 美元指数>110 或 美元指数单日>1%
  - 🟢 环境友好：VIX<20（其余 20≤VIX<25 默认 🟢）

保存：macro_indicators 表（indicator/region/value/date/source）+ system_settings key='macro_signal'
"""

import json
from datetime import datetime

from ..data_sources.market.http_client import get
from ..data_sources.market.snapshot_client import get_a_breadth
from ..models.database import get_connection, utc_now
from ..services.logger import get_agent_logger
from ..services.settings_service import get_setting, set_setting

logger = get_agent_logger()

MACRO_SIGNAL_KEY = 'macro_signal'

# 全球指标（yfinance 代码, 显示名, 区域, 单位, 备注）
GLOBAL_INDICATORS = [
    ('^VIX', 'VIX恐慌指数', '全球', None, '恐慌情绪'),
    ('DX-Y.NYB', '美元指数', '全球', None, '美元强弱'),
    ('CL=F', 'WTI原油', '全球', '美元/桶', '能源价格'),
    ('GC=F', 'COMEX黄金', '全球', '美元/盎司', '避险资产'),
]

# 中国宏观（东财数据中心 reportName, 取值字段, 显示名, 区域, 单位）
EM_MACRO_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
CHINA_INDICATORS = [
    ('RPT_ECONOMY_CPI', 'NATIONAL_SAME', 'CPI同比', '中国', '%'),
    ('RPT_ECONOMY_PMI', 'MAKE_INDEX', '制造业PMI', '中国', None),
    ('RPT_ECONOMY_PPI', 'BASE_SAME', 'PPI同比', '中国', '%'),
]

SIGNAL_META = {
    'green': '🟢',
    'yellow': '🟡',
    'red': '🔴',
    'black': '⚫',
}


# ---------------- 数据采集 ----------------

def _yf_last(symbol: str) -> dict | None:
    """yfinance 最近收盘：{value, change_pct, date}；失败返回 None"""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        df = t.history(period='5d')
        if df is None or df.empty:
            return None
        closes = [float(x) for x in df['Close'] if float(x) > 0]
        if not closes:
            return None
        last = closes[-1]
        prev = closes[-2] if len(closes) > 1 else None
        change_pct = round((last / prev - 1) * 100, 2) if prev else None
        return {
            'value': round(last, 2),
            'change_pct': change_pct,
            'date': df.index[-1].strftime('%Y-%m-%d'),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning('yfinance %s 获取失败: %s', symbol, str(e)[:100])
        return None


def _em_macro(report_name: str, value_key: str) -> dict | None:
    """东财数据中心宏观指标最新值：{value, date}；失败返回 None"""
    try:
        text = get(EM_MACRO_URL, params={
            'reportName': report_name, 'columns': 'ALL',
            'pageNumber': 1, 'pageSize': 1,
            'sortColumns': 'REPORT_DATE', 'sortTypes': -1,
        }, retries=1)
        data = json.loads(text)
        rows = (data.get('result') or {}).get('data') or []
        if not rows:
            return None
        row = rows[0]
        v = row.get(value_key)
        if v is None or v == '-':
            return None
        return {
            'value': float(v),
            'date': str(row.get('REPORT_DATE') or '')[:10],
        }
    except Exception as e:  # noqa: BLE001
        logger.warning('东财宏观 %s 获取失败: %s', report_name, str(e)[:100])
        return None


def _sentiment() -> dict | None:
    """A股市场情绪：涨跌家数 + 两市成交额"""
    try:
        breadth = get_a_breadth()
        if not breadth:
            return None
        return {
            'up': breadth.get('up'), 'down': breadth.get('down'),
            'flat': breadth.get('flat'),
            'turnover': breadth.get('turnover'),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning('市场情绪获取失败: %s', str(e)[:100])
        return None


# ---------------- 四色信号 ----------------

def _decide_signal(factors: dict) -> tuple[str, list[dict]]:
    """四色信号判定；返回 (level, notes)"""
    notes: list[dict] = []
    vix = factors.get('vix') or {}
    usd = factors.get('usd') or {}
    oil = factors.get('oil') or {}

    vix_val = vix.get('value')
    usd_val = usd.get('value')
    usd_chg = usd.get('change_pct')
    oil_chg = oil.get('change_pct')

    if vix_val is not None and vix_val >= 40:
        notes.append({'name': 'VIX恐慌指数', 'value': vix_val, 'note': 'VIX≥40，市场恐慌极端'})
        return 'black', notes
    if oil_chg is not None and oil_chg > 5:
        notes.append({'name': 'WTI原油', 'value': oil.get('value'), 'note': f'原油单日 {oil_chg}%>5%，能源冲击'})
        return 'black', notes
    if vix_val is not None and vix_val >= 30:
        notes.append({'name': 'VIX恐慌指数', 'value': vix_val, 'note': 'VIX≥30，风险偏高'})
        return 'red', notes
    if vix_val is not None and vix_val >= 25:
        notes.append({'name': 'VIX恐慌指数', 'value': vix_val, 'note': 'VIX≥25，中性偏谨慎'})
        return 'yellow', notes
    if usd_val is not None and usd_val > 110:
        notes.append({'name': '美元指数', 'value': usd_val, 'note': '美元指数>110，异常走强'})
        return 'yellow', notes
    if usd_chg is not None and usd_chg > 1:
        notes.append({'name': '美元指数', 'value': usd_val, 'note': f'美元指数单日 {usd_chg}%>1%'})
        return 'yellow', notes
    if vix_val is not None and vix_val < 20:
        notes.append({'name': 'VIX恐慌指数', 'value': vix_val, 'note': 'VIX<20，环境友好'})
        return 'green', notes
    notes.append({'name': 'VIX恐慌指数', 'value': vix_val, 'note': 'VIX 20~25，中性'})
    return 'green', notes


# ---------------- 主流程 ----------------

def _save_indicator(indicator: str, region: str, value, unit, date: str, source: str) -> None:
    if value is None or date is None:
        return
    conn = get_connection()
    try:
        # 幂等：同日同指标先删后插，refresh 不产生重复记录
        conn.execute(
            'DELETE FROM macro_indicators WHERE indicator = ? AND region = ? AND date = ?',
            (indicator, region, date),
        )
        conn.execute(
            'INSERT INTO macro_indicators (indicator, region, value, unit, date, source, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (indicator, region, value, unit, date, source, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def collect_macro() -> dict:
    """采集全部宏观指标并判定四色信号；单指标失败降级。返回总览 dict。"""
    today = datetime.now().strftime('%Y-%m-%d')
    factors: list[dict] = []
    factor_map: dict[str, dict] = {}
    indicators: list[dict] = []

    # 1) 全球（yfinance）
    for code, name, region, unit, note in GLOBAL_INDICATORS:
        data = _yf_last(code)
        if data is None:
            factors.append({'name': name, 'value': None, 'note': '数据源不可用'})
            continue
        key = {'^VIX': 'vix', 'DX-Y.NYB': 'usd', 'CL=F': 'oil', 'GC=F': 'gold'}[code]
        factor_map[key] = data
        chg = f"，单日 {data['change_pct']}%" if data.get('change_pct') is not None else ''
        factors.append({'name': name, 'value': data['value'],
                        'note': f'{note}{chg}'})
        _save_indicator(name, region, data['value'], unit, data.get('date') or today, 'yfinance')
        indicators.append({'indicator': name, 'region': region, 'value': data['value'],
                           'unit': unit, 'date': data.get('date') or today, 'source': 'yfinance'})

    # 2) 中国宏观（东财）
    china_ok = False
    for report, key, name, region, unit in CHINA_INDICATORS:
        data = _em_macro(report, key)
        if data is None:
            continue
        china_ok = True
        factors.append({'name': name, 'value': data['value'],
                        'note': f"最新 {data.get('date') or '—'}"})
        _save_indicator(name, region, data['value'], unit, data.get('date') or today, 'eastmoney')
        indicators.append({'indicator': name, 'region': region, 'value': data['value'],
                           'unit': unit, 'date': data.get('date') or today, 'source': 'eastmoney'})
    if not china_ok:
        factors.append({'name': '中国宏观(CPI/PMI)', 'value': None,
                        'note': '数据源不可用', 'source': 'unavailable'})

    # 3) 市场情绪（快照）
    senti = _sentiment()
    if senti:
        up = senti.get('up'); down = senti.get('down')
        turnover = senti.get('turnover')
        if up is not None and down is not None:
            factors.append({'name': '市场情绪', 'value': None,
                            'note': f'上涨 {up} 家 / 下跌 {down} 家'})
            _save_indicator('上涨家数', 'A股', up, '家', today, 'snapshot')
            _save_indicator('下跌家数', 'A股', down, '家', today, 'snapshot')
            indicators.append({'indicator': '上涨家数', 'region': 'A股', 'value': up,
                               'unit': '家', 'date': today, 'source': 'snapshot'})
            indicators.append({'indicator': '下跌家数', 'region': 'A股', 'value': down,
                               'unit': '家', 'date': today, 'source': 'snapshot'})
        if turnover:
            factors.append({'name': '沪深两市成交额', 'value': round(turnover / 1e8, 2),
                            'note': '亿元'})
            _save_indicator('两市成交额', 'A股', round(turnover / 1e8, 2), '亿元', today, 'snapshot')
            indicators.append({'indicator': '两市成交额', 'region': 'A股',
                               'value': round(turnover / 1e8, 2), 'unit': '亿元',
                               'date': today, 'source': 'snapshot'})

    # 4) 四色信号
    level, signal_notes = _decide_signal(factor_map)
    factors = signal_notes + [f for f in factors if f['name'] not in
                              {n['name'] for n in signal_notes}]
    signal = SIGNAL_META[level]

    result = {
        'signal': signal,
        'level': level,
        'factors': factors,
        'indicators': indicators,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'collected',
    }
    try:
        set_setting(MACRO_SIGNAL_KEY, {
            'signal': signal, 'level': level,
            'factors': factors, 'updated_at': result['updated_at'],
        })
    except Exception as e:  # noqa: BLE001
        logger.warning('宏观信号保存失败: %s', str(e)[:100])
    logger.info('宏观采集完成: 信号 %s (%s)，因子 %d 项', signal, level, len(factors))
    return result


def get_macro_overview(refresh: bool = False) -> dict:
    """宏观总览：refresh=True 或当日无缓存时重新采集；否则返回缓存信号 + 指标列表"""
    if not refresh:
        stored = get_setting(MACRO_SIGNAL_KEY) or {}
        if stored.get('level') and stored.get('updated_at', '').startswith(
                datetime.now().strftime('%Y-%m-%d')):
            return {
                'signal': stored.get('signal', '🟢'),
                'level': stored.get('level', 'green'),
                'factors': stored.get('factors') or [],
                'indicators': _recent_indicators(),
                'updated_at': stored.get('updated_at'),
                'source': 'stored',
            }
    return collect_macro()


def refresh_macro() -> dict:
    """强制重新采集（幂等：同日同指标覆盖写）"""
    return collect_macro()


def _recent_indicators(limit: int = 30) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT indicator, region, value, unit, date, source FROM macro_indicators '
            'ORDER BY date DESC, id DESC LIMIT ?',
            (min(int(limit), 100),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
