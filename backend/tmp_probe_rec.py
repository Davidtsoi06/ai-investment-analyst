# -*- coding: utf-8 -*-
"""复现：用户真实 watchlist 候选 + 用户 Key → 走 recommend_agent 真实 AI 调用"""
import os, sys, json, sqlite3, urllib.parse, time
sys.path.insert(0, r'D:/家/home/AI投资分析软件/backend')
from pathlib import Path
import app.config as cfg
cfg.settings.data_dir = Path(os.environ['APPDATA']) / 'ai-investment-analyst' / 'data'
from app.services.crypto_util import decrypt_text
db = cfg.settings.data_dir / 'ai_invest.db'
uri = 'file:' + urllib.parse.quote(str(db).replace(chr(92), '/'), safe='/') + '?mode=ro&immutable=1'
c = sqlite3.connect(uri, uri=True)
c.row_factory = sqlite3.Row
enc = c.execute("SELECT value FROM system_settings WHERE key='ai_key_encrypted'").fetchone()
wl = c.execute("SELECT symbol, name, market FROM watchlist").fetchall()
hd = c.execute("SELECT symbol, name, market FROM holdings WHERE source='portfolio_app' LIMIT 5").fetchall()
c.close()
key = decrypt_text(str(enc[0])) if enc else ''
print('key len', len(key), '| watchlist:', [tuple(w) for w in wl], '| holdings:', [tuple(h) for h in hd])

from app.data_sources.market.data_fusion import data_fusion
from app.services.indicators import indicator_snapshot
from app.utils.prompts.recommend_prompt import build_short_prompt
import requests

cand_list = []
for w in wl[:5]:
    sym, name, mkt = w['symbol'], w['name'], w['market']
    try:
        q = data_fusion.get_quote(sym, mkt)
        bars = data_fusion.get_kline(sym, mkt, 120)
        if q is None or not bars:
            print(sym, '行情失败'); continue
        snap = indicator_snapshot(bars)
        if not snap:
            print(sym, '指标失败'); continue
        cand_list.append({'symbol': sym, 'name': name or q.name, 'market': mkt, 'price': float(q.price),
                          'change_pct': q.change_pct, 'vol_ratio': snap.get('vol_ratio'),
                          'breakout': snap.get('breakout', {}).get('hit'), 'ma_status': snap.get('ma_status'),
                          'dif': snap.get('dif'), 'hist': snap.get('hist'),
                          'macd_golden_cross': snap.get('macd_golden_cross'), 'kdj_golden_cross': snap.get('kdj_golden_cross'),
                          'rsi14': snap.get('rsi14'), 'boll_pos': snap.get('boll_pos'),
                          'chg_5d': snap.get('chg_pct_5d'), 'news': []})
    except Exception as e:
        print(sym, 'ERR', str(e)[:100])
print('候选就绪:', len(cand_list))
if not cand_list:
    raise SystemExit
prompt = build_short_prompt(cand_list)
t0 = time.time()
r = requests.post('https://api.deepseek.com/chat/completions',
                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                  json={'model': 'deepseek-reasoner', 'messages': [{'role': 'user', 'content': prompt}],
                        'temperature': 0.3, 'max_tokens': 3000}, timeout=180)
print('HTTP', r.status_code, '耗时', round(time.time() - t0, 1), 's')
if r.status_code != 200:
    print('body:', r.text[:400])
else:
    msg = r.json().get('choices', [{}])[0].get('message', {})
    text = msg.get('content') or ''
    print('content 长度:', len(text), '| 前120:', text[:120])
    fence = chr(96) * 3
    import re
    t2 = re.sub(r'^\s*' + fence + r'json\s*', '', text.strip())
    t2 = re.sub(r'\s*' + fence + r'\s*$', '', t2).strip()
    if not t2.startswith(('[', '{')):
        idxs = [i for i in (t2.find('['), t2.find('{')) if i >= 0]
        if idxs: t2 = t2[min(idxs):]
    try:
        data = json.loads(t2)
        print('解析 OK 条数:', len(data) if isinstance(data, list) else '非数组', str(data)[:300])
    except Exception as e:
        print('解析失败:', str(e)[:150])
