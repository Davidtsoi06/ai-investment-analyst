# -*- coding: utf-8 -*-
"""yfinance（港股备用源）"""

from datetime import datetime

from .models import Quote, KLineBar


def hk_quote(symbol: str) -> Quote | None:
    try:
        import yfinance as yf
        t = yf.Ticker(f'{0}.HK'.format(symbol))
        fi = t.fast_info
        price = float(fi.last_price)
        prev_close = float(fi.previous_close) if fi.previous_close else price
        change_pct = (price / prev_close - 1) * 100 if prev_close else 0.0
        return Quote(
            symbol=symbol,
            name=t.info.get('shortName') or symbol,
            market='港股',
            price=price,
            change_pct=round(change_pct, 2),
            change=round(price - prev_close, 2),
            open=price,
            high=price,
            low=price,
            prev_close=prev_close,
            volume=0.0,
            amount=0.0,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            source='yfinance',
        )
    except Exception:
        return None


def hk_kline(symbol: str, days: int = 120) -> list[KLineBar] | None:
    try:
        import yfinance as yf
        t = yf.Ticker(f'{0}.HK'.format(symbol))
        df = t.history(period='1y')
        if df is None or df.empty:
            return None
        bars = []
        for idx, row in df.tail(days).iterrows():
            bars.append(KLineBar(
                date=idx.strftime('%Y-%m-%d'),
                open=float(row['Open']),
                close=float(row['Close']),
                high=float(row['High']),
                low=float(row['Low']),
                volume=float(row['Volume']),
                amount=0.0,
            ))
        return bars or None
    except Exception:
        return None
