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
    """加密存储 API Key（明文不入库；每次读取时实时解密，与理财软件一致）"""
    key = api_key.strip()
    if not key:
        return {'ok': False, 'error': 'API Key 不能为空'}
    set_setting(AI_KEY_KEY, encrypt_text(key))
    logger.info('DeepSeek API Key 已加密保存')
    return {'ok': True}


def get_ai_key() -> str:
    """读取 API Key：每次实时解密数据库密文（无内存缓存，避免进程重启/缓存不一致导致"有 Key 却读不到"）"""
    stored = get_setting(AI_KEY_KEY)
    if stored is None:
        return ''
    return decrypt_text(str(stored))


def ai_key_configured() -> bool:
    return bool(get_ai_key())


def ai_key_tail() -> str:
    """Key 尾号（用于界面展示，如 sk-****abcd；未配置返回空）"""
    key = get_ai_key()
    return key[-4:] if key else ''
