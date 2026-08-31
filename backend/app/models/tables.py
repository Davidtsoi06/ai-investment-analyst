# -*- coding: utf-8 -*-
"""SQLite 表定义：14 张核心表 + 迁移表（见需求文档 6.2 / 技术设计规范 五）

SCHEMA_VERSION 递增并同步补充 MIGRATIONS：旧库通过 ALTER 增列/建索引平滑升级。
"""

SCHEMA_VERSION = 3

TABLES_DDL = [
    # 1. 用户画像（引导问卷结果，可随时修改）
    """CREATE TABLE IF NOT EXISTS user_profile (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        risk_tolerance TEXT DEFAULT '稳健型',
        invest_amount TEXT DEFAULT '10-50万',
        markets TEXT DEFAULT '["A股","港股"]',
        holding_period TEXT DEFAULT '数天~数周',
        experience TEXT DEFAULT '有经验',
        onboarded INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )"""
    ,
    # 2. 持仓（手动/CSV/理财软件同步）
    """CREATE TABLE IF NOT EXISTS holdings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        name TEXT NOT NULL,
        market TEXT NOT NULL,
        currency TEXT NOT NULL DEFAULT 'CNY',
        quantity REAL NOT NULL DEFAULT 0,
        cost_price REAL NOT NULL DEFAULT 0,
        current_price REAL,
        source TEXT DEFAULT 'manual',
        sync_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )"""
    ,
    # 3. 自选股（支持分组）
    """CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        name TEXT,
        market TEXT,
        group_name TEXT DEFAULT '默认',
        sort_order INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )"""
    ,
    # 4. 追踪股票与异动条件
    """CREATE TABLE IF NOT EXISTS tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        name TEXT,
        market TEXT NOT NULL,
        price_change_pct REAL DEFAULT 3.0,
        volume_ratio REAL DEFAULT 3.0,
        big_order_amount REAL DEFAULT 1000000,
        tech_signals INTEGER DEFAULT 1,
        ai_judge INTEGER DEFAULT 1,
        active INTEGER DEFAULT 1,
        today_triggered INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )"""
    ,
    # 5. 异动事件记录
    """CREATE TABLE IF NOT EXISTS tracking_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        event_type TEXT NOT NULL,
        level TEXT NOT NULL,
        price REAL,
        change_pct REAL,
        detail TEXT,
        notified INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )"""
    ,
    # 6. AI 推荐历史（S10：短线=入场区间/止损/目标价；长线=估值区间）
    """CREATE TABLE IF NOT EXISTS recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        name TEXT,
        market TEXT,
        rec_type TEXT NOT NULL,
        entry_min REAL, entry_max REAL,
        stop_loss REAL, target REAL,
        valuation_min REAL, valuation_max REAL,
        confidence INTEGER,
        logic TEXT,
        risk_level TEXT,
        rec_date TEXT NOT NULL,
        rec_price REAL,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL
    )"""
    ,
    # 7. 推荐回测表现（S10：结算结果，outcome=win/loss/stop/flat）
    """CREATE TABLE IF NOT EXISTS recommendation_performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recommendation_id INTEGER NOT NULL,
        result_price REAL,
        result_pct REAL,
        outcome TEXT,
        entry_price REAL,
        eval_days INTEGER,
        horizon TEXT,
        evaluated_at TEXT
    )"""
    ,
    # 8. 资讯缓存（去重）
    """CREATE TABLE IF NOT EXISTS news_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url TEXT,
        source TEXT,
        market TEXT,
        summary TEXT,
        level TEXT,
        content_hash TEXT UNIQUE,
        published_at TEXT,
        created_at TEXT NOT NULL
    )"""
    ,
    # 9. 盘后总结存档
    """CREATE TABLE IF NOT EXISTS daily_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date TEXT NOT NULL,
        market TEXT NOT NULL,
        content TEXT NOT NULL,
        suggestions TEXT,
        created_at TEXT NOT NULL
    )"""
    ,
    # 10. 复盘报告存档
    """CREATE TABLE IF NOT EXISTS review_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period TEXT NOT NULL,
        period_start TEXT,
        period_end TEXT,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )"""
    ,
    # 11. 通知发送记录（频率控制）
    """CREATE TABLE IF NOT EXISTS notification_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        level TEXT,
        title TEXT,
        content TEXT,
        channel TEXT DEFAULT 'in_app',
        sent_at TEXT NOT NULL
    )"""
    ,
    # 12. 宏观指标历史
    """CREATE TABLE IF NOT EXISTS macro_indicators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator TEXT NOT NULL,
        region TEXT NOT NULL,
        value REAL,
        unit TEXT,
        date TEXT NOT NULL,
        source TEXT,
        created_at TEXT NOT NULL
    )"""
    ,
    # 13. 市场情绪指标历史
    """CREATE TABLE IF NOT EXISTS market_sentiment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market TEXT NOT NULL,
        date TEXT NOT NULL,
        metric TEXT NOT NULL,
        value REAL,
        created_at TEXT NOT NULL
    )"""
    ,
    # 14. 系统设置（KV）
    """CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL
    )"""
    ,
    # 迁移版本记录
    """CREATE TABLE IF NOT EXISTS migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )"""
]

# 版本化迁移：{版本: 步骤列表}。步骤必须幂等（增列前先查列存在性，建索引用 IF NOT EXISTS）。
MIGRATIONS: dict[int, list[dict]] = {
    3: [
        # S11 tracking：今日触发计数归属日（跨日轮询重置 today_triggered）+ 事件查询索引
        {'kind': 'add_column', 'table': 'tracking', 'column': 'today_date', 'ddl': "ALTER TABLE tracking ADD COLUMN today_date TEXT"},
        {'kind': 'sql', 'ddl': "CREATE INDEX IF NOT EXISTS idx_tracking_events_tid ON tracking_events(tracking_id)"},
        {'kind': 'sql', 'ddl': "CREATE INDEX IF NOT EXISTS idx_tracking_events_created ON tracking_events(created_at)"},
    ],
    2: [
        # recommendations 增加长线估值区间与生命周期状态
        {'kind': 'add_column', 'table': 'recommendations', 'column': 'valuation_min', 'ddl': "ALTER TABLE recommendations ADD COLUMN valuation_min REAL"},
        {'kind': 'add_column', 'table': 'recommendations', 'column': 'valuation_max', 'ddl': "ALTER TABLE recommendations ADD COLUMN valuation_max REAL"},
        {'kind': 'add_column', 'table': 'recommendations', 'column': 'status', 'ddl': "ALTER TABLE recommendations ADD COLUMN status TEXT NOT NULL DEFAULT 'open'"},
        # recommendation_performance 增加结算字段
        {'kind': 'add_column', 'table': 'recommendation_performance', 'column': 'entry_price', 'ddl': "ALTER TABLE recommendation_performance ADD COLUMN entry_price REAL"},
        {'kind': 'add_column', 'table': 'recommendation_performance', 'column': 'eval_days', 'ddl': "ALTER TABLE recommendation_performance ADD COLUMN eval_days INTEGER"},
        {'kind': 'add_column', 'table': 'recommendation_performance', 'column': 'horizon', 'ddl': "ALTER TABLE recommendation_performance ADD COLUMN horizon TEXT"},
        # 索引
        {'kind': 'sql', 'ddl': "CREATE INDEX IF NOT EXISTS idx_recommendations_rec_date ON recommendations(rec_date)"},
        {'kind': 'sql', 'ddl': "CREATE INDEX IF NOT EXISTS idx_recommendations_status ON recommendations(status)"},
        {'kind': 'sql', 'ddl': "CREATE INDEX IF NOT EXISTS idx_rec_perf_rec_id ON recommendation_performance(recommendation_id)"},
    ],
}
