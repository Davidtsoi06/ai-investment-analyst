# -*- coding: utf-8 -*-
"""资讯去重：标题相似度 > 85% 视为同源（difflib）"""

import difflib

SIMILARITY_THRESHOLD = 0.85


def normalize(title: str) -> str:
    """标题归一化：去【】与空白"""
    return title.replace('【', '').replace('】', '').replace(' ', '').strip()


def is_duplicate(new_title: str, existing_titles: list[str]) -> bool:
    """与已有标题比较，相似度超过阈值视为重复"""
    n = normalize(new_title)
    if not n:
        return True
    for t in existing_titles[:50]:
        m = normalize(t)
        if not m:
            continue
        if m == n:
            return True
        ratio = difflib.SequenceMatcher(None, n, m).ratio()
        if ratio > SIMILARITY_THRESHOLD and len(n) > 10:
            return True
    return False


def dedup_in_batch(items: list) -> list:
    """批量内两两去重（保持顺序）"""
    result: list = []
    seen: list[str] = []
    for item in items:
        if not is_duplicate(item.title, seen):
            result.append(item)
            seen.append(item.title)
    return result
