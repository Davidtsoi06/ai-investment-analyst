# -*- coding: utf-8 -*-
"""定时任务调度器（APScheduler，北京时间）"""

from apscheduler.schedulers.background import BackgroundScheduler

from .logger import get_app_logger

logger = get_app_logger()

scheduler = BackgroundScheduler(timezone='Asia/Shanghai')


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info('调度器已启动')


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info('调度器已停止')


def add_cron_job(func, hour: int, minute: int, job_id: str | None = None,
                  day: int | None = None, day_of_week: str | None = None) -> None:
    """注册 cron 任务；day=每月几号（1-31），day_of_week=每周几（mon..sun / 0-6）"""
    trigger_args = {'hour': hour, 'minute': minute}
    if day is not None:
        trigger_args['day'] = day
    if day_of_week is not None:
        trigger_args['day_of_week'] = day_of_week
    scheduler.add_job(func, 'cron', id=job_id, replace_existing=True, **trigger_args)

    def _fmt(v) -> str:
        """hour/minute 可能为 int 或 '*' 字符串，统一展示"""
        return f'{v:02d}' if isinstance(v, int) else str(v)

    when = f'{_fmt(hour)}:{_fmt(minute)}'
    if day is not None:
        when += f' 每月{day}日'
    if day_of_week is not None:
        when += f' 星期{day_of_week}'
    logger.info('已注册定时任务 %s: %s', job_id or func.__name__, when)
