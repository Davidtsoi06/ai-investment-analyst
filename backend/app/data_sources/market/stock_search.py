# -*- coding: utf-8 -*-
"""外部股票搜索：东财 suggest 名称 → 代码（智能问答 #8 增强：非持仓股票也能识别）

仅作名称→代码解析，不爬网页；失败返回空列表（不影响主流程）。
"""

import json
import logging
import re

from .http_client import get

logger = logging.getLogger('stock_search')

SEARCH_URL = 'https://searchapi.eastmoney.com/api/suggest/get'
# 东财前端公开固定 token（仅用于 suggest 名称搜索）
SEARCH_TOKEN = 'D43BF722C8E33BDC906FB84D85E326E8'

# 东财 suggest MktNum：0/1 = 沪深A股，116 = 港股
MKT_A = ('0', '1', 0, 1)
MKT_HK = ('116', 116)

# 港股衍生品/权证特征词（正股名不含）
_DERIVATIVE_HINTS = (
    '购', '沽', '牛证', '熊证', '法兴', '摩利', '摩通', '瑞银', '信证', '高盛', '麦格理',
    '中银', '汇丰', '国君', '华泰', '野村', '大和', '海通', '法巴', '瑞信', '星展', '花旗',
    '东亚', '比迪', '荷合', 'CALL', 'PUT',
)
# A 股代码前缀白名单（排除场内基金 15/16/18 等）
_A_PREFIXES = ('60', '68', '00', '30')
# 港股正股代码多为 00xxx/01xxx（5 位数字 0 开头）
_HK_RE = re.compile(r'^0\d{4}$')
_SUFFIX_RE = re.compile(r'[-_/／]?(?:W|R|WR|S|B|ADR|SW|Ltd|H股)(?![\u4e00-\u9fa5A-Za-z])')


def normalize_name(name: str) -> str:
    # 去交易所/类别后缀：'小米集团-W' → '小米集团'；'腾讯控股-R' → '腾讯控股'
    return _SUFFIX_RE.sub('', name or '').strip()


def search_stocks(keyword: str, limit: int = 5) -> list[dict]:
    """按名称/代码关键词搜索股票 → [{symbol, name, market}]；失败或空返回 []"""
    kw = (keyword or '').strip()
    if not kw or len(kw) > 20:
        return []
    try:
        text = get(SEARCH_URL, params={
            'input': kw,
            'type': '14',  # 沪深 A 股 + 港股（含权证/基金，下方过滤）
            'token': SEARCH_TOKEN,
            'count': str(min(max(limit, 1), 10)),
        }, timeout=6.0)
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        logger.warning('外部搜索失败 %s: %s', kw, str(e)[:100])
        return []
    table = (data.get('QuotationCodeTable') or {})
    rows = table.get('Data') or []
    out: list[dict] = []
    for r in rows:
        code = str(r.get('Code') or '').strip()
        name = str(r.get('Name') or '').strip()
        mkt = r.get('MktNum')
        if not code or not name:
            continue
        market = None
        if mkt in MKT_A and code.isdigit() and len(code) == 6 and code.startswith(_A_PREFIXES):
            market = 'A股'
        elif mkt in MKT_HK and _HK_RE.match(code):
            # 港股正股：代码形如 0xxxx；名称含权证特征词的跳过
            if any(h in name for h in _DERIVATIVE_HINTS):
                continue
            market = '港股'
        if market is None:
            continue
        out.append({'symbol': code, 'name': normalize_name(name), 'market': market})
        if len(out) >= limit:
            break
    return out