# -*- coding: utf-8 -*-
import os, re
p = os.path.join(os.environ['APPDATA'], 'ai-investment-analyst', 'data', 'logs', 'desktop.log')
raw = open(p, 'rb').read()
try: text = raw.decode('utf-8')
except UnicodeDecodeError: text = raw.decode('gbk', errors='replace')
lines = text.splitlines()
print('总行数', len(lines))
for l in lines[-45:]:
    print(l[:190])
