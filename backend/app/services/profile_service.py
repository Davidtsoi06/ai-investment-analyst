# -*- coding: utf-8 -*-
"""用户画像服务：user_profile 表（首次引导问卷）"""

import json

from ..models.database import get_connection, utc_now

DEFAULT_PROFILE = {
    'risk_tolerance': '稳健型',
    'invest_amount': '10-50万',
    'markets': ['A股', '港股'],
    'holding_period': '数天~数周',
    'experience': '有经验',
    'onboarded': 0,
}


def get_profile() -> dict:
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM user_profile ORDER BY id DESC LIMIT 1').fetchone()
    finally:
        conn.close()
    if row is None:
        return dict(DEFAULT_PROFILE)
    profile = dict(row)
    try:
        profile['markets'] = json.loads(profile.get('markets') or '[]')
    except (ValueError, TypeError):
        profile['markets'] = DEFAULT_PROFILE['markets']
    return profile


# 投资金额档位 -> 中值（元）：10万以下→5万、10-50万→30万、50-100万→75万、100万以上→150万
INVEST_AMOUNT_MID = {
    '10万以下': 50000,
    '10-50万': 300000,
    '50-100万': 750000,
    '100万以上': 1500000,
}


def invest_amount_mid() -> float:
    """画像投资金额档位对应的中值金额（元）；未识别档位默认 30 万"""
    profile = get_profile()
    return INVEST_AMOUNT_MID.get((profile.get('invest_amount') or '').strip(), 300000)


def save_profile(data: dict) -> dict:
    """保存画像并标记引导完成"""
    now = utc_now()
    fields = ('risk_tolerance', 'invest_amount', 'markets', 'holding_period', 'experience')
    values = {k: data.get(k, DEFAULT_PROFILE.get(k)) for k in fields}
    markets_json = json.dumps(values.get('markets') or ['A股', '港股'], ensure_ascii=False)
    conn = get_connection()
    try:
        conn.execute(
            '''INSERT INTO user_profile
            (risk_tolerance, invest_amount, markets, holding_period, experience, onboarded, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)'''
            , (
            values['risk_tolerance'],
            values['invest_amount'],
            markets_json,
            values['holding_period'],
            values['experience'],
            now,
            now,
        ))
        conn.commit()
    finally:
        conn.close()
    result = get_profile()
    result['onboarded'] = 1
    return result
