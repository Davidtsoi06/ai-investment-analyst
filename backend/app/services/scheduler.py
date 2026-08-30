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


def add_cron_job(func, hour: int, minute: int, job_id: str | None = None) -> None:
    scheduler.add_job(func, 'cron', hour=hour, minute=minute, id=job_id, replace_existing=True)
    logger.info('已注册定时任务 %s: %02d:%02d', job_id or func.__name__, hour, minute)
