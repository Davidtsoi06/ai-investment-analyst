# -*- coding: utf-8 -*-
"""通知中心：记录通知（notification_log）+ 频率控制 + 免打扰判断"""

from datetime import datetime

from ..models.database import get_connection
from .logger import get_notification_logger
from .settings_service import get_setting

notify_log = get_notification_logger()

# 频率控制：{type}: 最短间隔秒数
TYPE_COOLDOWN = {
    'premarket': 3600 * 6,  # 盘前资讯 6 小时不重复
    'alert': 15 * 60,  # 异动 15 分钟
    'risk': 30 * 60,  # 风险预警 30 分钟
}


def _in_quiet_hours(now: datetime | None = None) -> bool:
    """是否处于免打扰时段（紧急通知可豁免）"""
    qh = get_setting('quiet_hours', {})
    if not qh.get('enabled', True):
        return False
    now = now or datetime.now()
    try:
        start = datetime.strptime(qh.get('start', '23:00'), '%H:%M').time()
        end = datetime.strptime(qh.get('end', '07:00'), '%H:%M').time()
    except ValueError:
        return False
    t = now.time()
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def _can_send(notify_type: str) -> bool:
    """频率控制：同一类型在冷却期内不重复发送"""
    cooldown = TYPE_COOLDOWN.get(notify_type, 0)
    if cooldown <= 0:
        return True
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT sent_at FROM notification_log WHERE type = ? ORDER BY sent_at DESC LIMIT 1",
            (notify_type,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return True
    try:
        last = datetime.fromisoformat(row['sent_at'])
    except ValueError:
        return True
    if last.tzinfo is not None:
        last = last.astimezone().replace(tzinfo=None)
    return (datetime.now() - last).total_seconds() >= cooldown


def send_notification(
    notify_type: str,
    title: str,
    content: str,
    level: str = '提示',
    force: bool = False,
) -> dict:
    """发送应用内通知（写入 notification_log）"""
    if not force and not _can_send(notify_type):
        return {'sent': False, 'reason': '频率控制：冷却期内'}
    if not force and level != '紧急' and _in_quiet_hours():
        return {'sent': False, 'reason': '免打扰时段'}
    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            'INSERT INTO notification_log (type, level, title, content, channel, sent_at) VALUES (?, ?, ?, ?, ?, ?)',
            (notify_type, level, title, content, 'in_app', now),
        )
        conn.commit()
    finally:
        conn.close()
    notify_log.info('[%s] %s: %s', level, title, content[:80])
    return {'sent': True, 'at': now}


def list_notifications(limit: int = 30) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            'SELECT id, type, level, title, content, sent_at FROM notification_log ORDER BY sent_at DESC LIMIT ?',
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
