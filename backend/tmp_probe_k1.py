# -*- coding: utf-8 -*-
import os, sqlite3, urllib.parse, json, sys, re
sys.path.insert(0, r'D:/家/home/AI投资分析软件/backend')
from pathlib import Path
import app.config as cfg
cfg.settings.data_dir = Path(os.environ['APPDATA']) / 'ai-investment-analyst' / 'data'
from app.services.crypto_util import decrypt_text, get_last_error
db = cfg.settings.data_dir / 'ai_invest.db'
print('db:', db, 'exists:', db.exists())
print('secret.key:', (cfg.settings.data_dir / 'secret.key').exists())
uri = 'file:' + urllib.parse.quote(str(db).replace(chr(92), '/'), safe='/') + '?mode=ro&immutable=1'
c = sqlite3.connect(uri, uri=True)
c.row_factory = sqlite3.Row
row = c.execute("SELECT key, value, updated_at FROM system_settings WHERE key IN ('ai_key_encrypted','ai_last_error')").fetchall()
for r in row:
    print(' ', r['key'], '| updated:', r['updated_at'], '| value[:40]:', str(r['value'])[:40])
c.close()
# 解密验证
enc = None
c2 = sqlite3.connect(uri, uri=True)
r2 = c2.execute("SELECT value FROM system_settings WHERE key='ai_key_encrypted'").fetchone()
c2.close()
if r2:
    key = decrypt_text(str(r2[0]))
    print('解密结果: 长度', len(key), '| 前缀', (key[:6] + '...' + key[-4:]) if key else '(空!)', '| crypto_error:', get_last_error() or '(无)')
