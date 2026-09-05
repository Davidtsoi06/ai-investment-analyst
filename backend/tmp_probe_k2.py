# -*- coding: utf-8 -*-
import os, re
base = os.path.join(os.environ['APPDATA'], 'ai-investment-analyst', 'data', 'logs')
for fn in ('app.log', 'agent.log'):
    p = os.path.join(base, fn)
    if not os.path.exists(p):
        continue
    raw = open(p, 'rb').read()
    try: text = raw.decode('utf-8')
    except UnicodeDecodeError: text = raw.decode('gbk', errors='replace')
    lines = text.splitlines()
    sel = [l for l in lines if re.search(r'2026-09-05|09-05', l) and re.search(r'AI|推荐|降级|chat|Key|key|错误|失败|reasoner|chat/ask|recommend/run|401|402|429|DeepSeek', l)]
    print('====', fn, '| 9/5 相关', len(sel), '条（总', len(lines), '）')
    for l in sel[-60:]:
        print(' ', l[:230])
