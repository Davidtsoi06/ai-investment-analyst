# -*- coding: utf-8 -*-
"""HTTP 封装：统一超时/UA；按数据源指定编码（腾讯/新浪为 GBK）与 Referer；自动重试"""

import time

import requests

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'


def get(
    url: str,
    params: dict | None = None,
    timeout: float = 8.0,
    encoding: str = 'utf-8',
    referer: str | None = None,
    retries: int = 3,
) -> str:
    """GET 请求，失败自动重试（免费接口偶发断连）"""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            headers = {'User-Agent': UA}
            if referer:
                headers['Referer'] = referer
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.encoding = encoding
            resp.raise_for_status()
            return resp.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last  # type: ignore[misc]
