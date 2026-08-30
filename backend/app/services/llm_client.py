# -*- coding: utf-8 -*-
"""DeepSeek API 客户端：测试连接 + 聊天（后续 Agent 使用）"""

import requests

from ..config import settings
from .logger import get_app_logger
from .settings_service import get_ai_key

logger = get_app_logger()


def test_connection(api_key: str | None = None) -> dict:
    """测试 API Key 有效性（调 /models 接口）"""
    key = (api_key or get_ai_key()).strip()
    if not key:
        return {'ok': False, 'error': '未配置 API Key'}
    try:
        r = requests.get(
            settings.deepseek_base_url.rstrip('/') + '/models',
            headers={'Authorization': f'Bearer {key}'},
            timeout=10,
        )
        if r.status_code == 200:
            models = [m.get('id') for m in r.json().get('data', [])]
            return {'ok': True, 'models': models[:5]}
        return {'ok': False, 'error': f'HTTP {r.status_code}: {r.text[:150]}'}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': str(e)[:150]}


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.7, max_tokens: int = 2048) -> str:
    """基础聊天调用（后续资讯/推荐/总结 Agent 使用）"""
    key = get_ai_key()
    if not key:
        raise RuntimeError('未配置 DeepSeek API Key')
    payload = {
        'model': model or settings.model_chat,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }
    r = requests.post(
        settings.deepseek_base_url.rstrip('/') + '/chat/completions',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content']
