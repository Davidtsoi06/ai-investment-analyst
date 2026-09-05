# -*- coding: utf-8 -*-
"""DeepSeek API 客户端：测试连接 + 聊天 + AI 错误记录（V1.0.7 错误可见化）"""

import json
import time

import requests

from ..config import settings
from ..models.database import get_connection, utc_now
from .logger import get_app_logger
from .settings_service import get_ai_key

logger = get_app_logger()

AI_LAST_ERROR_KEY = 'ai_last_error'


def _record_ai_error(message: str) -> None:
    """记录最近一次 AI 调用错误（供界面展示真实原因，避免"莫名降级"黑盒）"""
    try:
        payload = json.dumps({'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'error': str(message)[:500]},
                             ensure_ascii=False)
        conn = get_connection()
        try:
            conn.execute(
                'INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)',
                (AI_LAST_ERROR_KEY, payload, utc_now()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass  # 错误记录本身失败不阻塞业务


def clear_ai_error() -> None:
    """公开：清除最近 AI 错误记录（保存新 Key / 测试成功后调用）"""
    _clear_ai_error()


def _clear_ai_error() -> None:
    """AI 调用恢复正常时清除错误记录"""
    try:
        conn = get_connection()
        try:
            conn.execute('DELETE FROM system_settings WHERE key = ?', (AI_LAST_ERROR_KEY,))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        pass


def get_ai_last_error() -> dict:
    """最近一次 AI 错误（{at, error}；无错误返回空 dict）"""
    conn = get_connection()
    try:
        row = conn.execute(
            'SELECT value FROM system_settings WHERE key = ?', (AI_LAST_ERROR_KEY,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    try:
        d = json.loads(row['value'])
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def ai_status() -> dict:
    """AI 连接状态（供设置页与推荐中心展示；绝不返回 Key 明文）：
    {configured, key_tail, crypto_error, last_error, last_error_at}"""
    from .crypto_util import get_last_error
    key = get_ai_key()
    last = get_ai_last_error()
    return {
        'configured': bool(key),
        'key_tail': (key[-4:] if key else ''),
        'crypto_error': get_last_error(),
        'last_error': last.get('error') or '',
        'last_error_at': last.get('at') or '',
    }


def _http_error_message(status: int, body: str) -> str:
    """把 DeepSeek HTTP 错误转可读中文提示（含服务端原文）"""
    hints = {
        401: 'API Key 无效（401 Invalid API key）——请检查是否复制完整（以 sk- 开头）',
        402: 'API 余额不足或额度用尽（402）——请到 platform.deepseek.com 充值',
        403: '无权限访问（403）',
        404: '接口或模型不存在（404）',
        429: '请求过于频繁或限流（429）——请稍后重试',
        500: 'DeepSeek 服务端错误（500）',
    }
    hint = hints.get(status, f'HTTP {status}')
    return f'DeepSeek {hint}：{body[:200]}'


def test_connection(api_key: str | None = None) -> dict:
    """测试 API Key 有效性（调 /models 接口）；结果同步到最近错误记录"""
    key = (api_key or get_ai_key()).strip()
    if not key:
        _record_ai_error('未配置 DeepSeek API Key')
        return {'ok': False, 'error': '未配置 API Key'}
    try:
        r = requests.get(
            settings.deepseek_base_url.rstrip('/') + '/models',
            headers={'Authorization': f'Bearer {key}'},
            timeout=10,
        )
        if r.status_code == 200:
            models = [m.get('id') for m in r.json().get('data', [])]
            _clear_ai_error()
            return {'ok': True, 'models': models[:5]}
        msg = _http_error_message(r.status_code, r.text[:200])
        _record_ai_error(msg)
        return {'ok': False, 'error': msg}
    except Exception as e:  # noqa: BLE001
        msg = f'网络请求失败：{str(e)[:150]}'
        _record_ai_error(msg)
        return {'ok': False, 'error': msg}


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.7, max_tokens: int = 2048) -> str:
    """基础聊天调用（资讯/推荐/总结/问答等 Agent 使用）。失败抛带原因异常并记录最近错误"""
    key = get_ai_key()
    if not key:
        _record_ai_error('未配置 DeepSeek API Key（或密钥解密失败），请到 设置 → DeepSeek AI 配置 检查')
        raise RuntimeError('未配置 DeepSeek API Key')
    payload = {
        'model': model or settings.model_chat,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    try:
        r = requests.post(
            settings.deepseek_base_url.rstrip('/') + '/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=60,
        )
    except Exception as e:  # noqa: BLE001
        msg = f'网络请求失败：{str(e)[:150]}'
        _record_ai_error(msg)
        raise RuntimeError(msg) from e
    if r.status_code != 200:
        msg = _http_error_message(r.status_code, r.text[:200])
        _record_ai_error(msg)
        raise RuntimeError(msg)
    _clear_ai_error()  # 调用成功：清除历史错误
    try:
        content = r.json()['choices'][0]['message']['content']
    except Exception as e:  # noqa: BLE001
        msg = f'DeepSeek 返回解析失败：{str(e)[:150]}（原始内容: {r.text[:150]}）'
        _record_ai_error(msg)
        raise RuntimeError(msg) from e
    return content
