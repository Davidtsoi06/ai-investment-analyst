# -*- coding: utf-8 -*-
"""日志系统：app / agent / notification 三类日志（data/logs/）"""

import logging
from logging.handlers import RotatingFileHandler

from ..config import settings


def _make_logger(name: str, filename: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        settings.log_dir / filename,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(fh)
    return logger


def get_app_logger() -> logging.Logger:
    return _make_logger("app", "app.log")


def get_agent_logger() -> logging.Logger:
    return _make_logger("agent", "agent.log")


def get_notification_logger() -> logging.Logger:
    return _make_logger("notification", "notification.log")
