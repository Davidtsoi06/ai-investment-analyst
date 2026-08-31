# -*- coding: utf-8 -*-
"""S13 智能问答 Prompt：系统提示 + 用户上下文（分类 + 上下文 JSON + 问题）"""

import json

SYSTEM_PROMPT = (
    '你是专业的投资分析助手。请严格遵守以下要求：\n'
    '1. 仅基于用户提供的数据回答，严禁编造或猜测数据，数据缺失时明确说明；\n'
    '2. 回答中说明所用数据的截止时间；\n'
    '3. 结论保持谨慎，给出风险提示；\n'
    '4. 结尾必须提醒：本回答仅供参考，不构成投资建议。'
)


def build_chat_messages(question: str, ctx: dict) -> list[dict]:
    """构建 chat 消息：user 内容 = 问题分类 + 上下文 JSON + 问题"""
    context = {
        'category': ctx.get('category'),
        'profile': ctx.get('profile'),
        'holdings': ctx.get('holdings'),
        'news': ctx.get('news'),
        'symbols': ctx.get('symbols'),
    }
    body = (
        f'问题分类：{ctx.get("category")}\n'
        '以下是可用的上下文数据（JSON）：\n'
        f'{json.dumps(context, ensure_ascii=False, default=str)}\n\n'
        f'用户问题：{question}'
    )
    return [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': body}]
