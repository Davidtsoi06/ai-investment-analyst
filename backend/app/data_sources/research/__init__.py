"""研报数据源（东方财富研报中心 + news_cache 降级）"""
from .eastmoney_research import fetch_research, interpret_research

__all__ = ['fetch_research', 'interpret_research']
