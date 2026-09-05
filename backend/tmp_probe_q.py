# -*- coding: utf-8 -*-
import os, re
base = os.path.join(os.environ['APPDATA'], 'ai-investment-analyst', 'data', 'logs')
for fn in ('app.log', 'agent.log'):
    p = os.path.join(base, fn)
    raw = open(p, 'rb').read()
    try: text = raw.decode('utf-8')
    except UnicodeDecodeError: text = raw.decode('gbk', errors='replace')
    lines = text.splitlines()
    # 最近 15 行中 chat/ask 与 AI 相关
    sel = [l for l in lines[-120:] if re.search(r'chat/ask|chat/history|AI 回答失败|降级|未配置|DeepSeek API Key', l)]
    print('====', fn, '最近相关', len(sel), '条')
    for l in sel[-12:]:
        print(' ', l[:210])
