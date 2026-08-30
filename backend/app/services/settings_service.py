# -*- coding: utf-8 -*-
"""系统设置服务：system_settings KV 表 + 默认值 + AI Key 加密存储"""

import json

from ..models.database import get_connection, utc_now
from .crypto_util import encrypt_text, decrypt_text
from .logger import get_app_logger

logger = get_app_logger()

AI_KEY_KEY = 'ai_key_encrypted'

DEFAULT_SETTINGS = {
    'markets': ['A股', '港股'],
    'notifications': {
        'premarket': True,
        'alert': True,
        'summary': True,
        'recommendation': True,
        'risk': True,
        'review': True,
    },
    'quiet_hours': {
        'enabled': True,
        'start': '23:00',
        'end': '07:00',
        'urgent_exempt': True,
    },
}


def get_setting(key: str, default=None):
    conn = get_connection()
    try:
        row = conn.execute('SELECT value FROM system_settings WHERE key = ?', (key,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return default
    try:
        return json.loads(row['value'])
    except (ValueError, TypeError):
        return row['value']


def set_setting(key: str, value) -> None:
    conn = get_connection()
    try:
        payload = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        conn.execute(
            'INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)',
            (key, payload, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_settings() -> dict:
    """合并默认值与已存储值"""
    result = json.loads(json.dumps(DEFAULT_SETTINGS))
    for key in DEFAULT_SETTINGS:
        stored = get_setting(key)
        if stored is not None:
            result[key] = stored
    return result


def save_settings(data: dict) -> dict:
    for key in DEFAULT_SETTINGS:
        if key in data:
            set_setting(key, data[key])
    logger.info('系统设置已保存: %s', list(data.keys()))
    return get_all_settings()


def save_ai_key(api_key: str) -> dict:
    """加密存储 API Key，并同步到内存配置"""
    key = api_key.strip()
    if not key:
        return {'ok': False, 'error': 'API Key 不能为空'}
    set_setting(AI_KEY_KEY, encrypt_text(key))
    from ..config import settings
    settings.deepseek_api_key = key
    logger.info('DeepSeek API Key 已加密保存')
    return {'ok': True}


def get_ai_key() -> str:
    from ..config import settings
    if settings.deepseek_api_key:
        return settings.deepseek_api_key
    stored = get_setting(AI_KEY_KEY)
    if stored is None:
        return ''
    key = decrypt_text(str(stored))
    settings.deepseek_api_key = key
    return key


def ai_key_configured() -> bool:
    return bool(get_ai_key())
