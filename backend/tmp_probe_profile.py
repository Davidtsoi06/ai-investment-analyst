# -*- coding: utf-8 -*-
import sqlite3, os, urllib.parse
db = os.path.join(os.environ['APPDATA'], 'ai-investment-analyst', 'data', 'ai_invest.db')
uri = 'file:' + urllib.parse.quote(db.replace(chr(92), '/'), safe='/') + '?mode=ro&immutable=1'
c = sqlite3.connect(uri, uri=True)
c.row_factory = sqlite3.Row
rows = c.execute('SELECT id, risk_tolerance, invest_amount, holding_period, experience, onboarded, created_at, updated_at FROM user_profile ORDER BY id').fetchall()
print('总行数:', len(rows))
for r in rows:
    d = dict(r)
    print(' id', d['id'], '| onboarded', d['onboarded'], '| created', d['created_at'], '| updated', d['updated_at'])
c.close()
