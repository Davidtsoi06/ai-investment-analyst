// 后端 API 客户端：经 Electron 主进程代理（window.backend），浏览器调试时直连

export interface ApiResult<T = unknown> {
  ok: boolean;
  status?: number;
  error?: string;
  data?: T;
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<ApiResult<T>> {
  if (window.backend) {
    // 主进程：HTTP 错误返回 {ok:false, status, error}；成功返回后端 JSON（可能含业务 ok 字段）
    const raw = (await window.backend.request(method, path, body)) as Record<string, unknown> | null;
    if (raw && raw.ok === false) {
      return raw as unknown as ApiResult<T>; // 错误响应原样返回
    }
    return { ok: true, data: raw as T }; // 成功统一包装（与浏览器分支一致）
  }
  // 浏览器直连（开发调试）：本地后端无令牌模式
  const res = await fetch(`http://127.0.0.1:8756${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) return { ok: false, status: res.status, error: await res.text() };
  return { ok: true, data: (await res.json()) as T };
}

export async function getBackendStatus() {
  if (window.backend) return window.backend.status();
  return { running: false, version: null, url: '', restartCount: 0 };
}

// ---- 画像 ----
export interface Profile {
  risk_tolerance: string;
  invest_amount: string;
  markets: string[];
  holding_period: string;
  experience: string;
  onboarded: number;
}
export const getProfile = () => api<Profile>('GET', '/api/profile');
export const saveProfile = (p: Partial<Profile>) => api<Profile>('PUT', '/api/profile', p);

// ---- 设置 ----
export interface Settings {
  markets: string[];
  notifications: Record<string, boolean>;
  quiet_hours: { enabled: boolean; start: string; end: string; urgent_exempt: boolean };
  ai_configured: boolean;
}
export const getSettings = () => api<Settings>('GET', '/api/settings');
export const saveSettings = (s: Partial<Settings>) => api<Settings>('PUT', '/api/settings', s);
export const saveAiKey = (key: string) => api('POST', '/api/settings/ai-key', { api_key: key });
export const testAiKey = (key?: string) => api<{ ok: boolean; models?: string[]; error?: string }>('POST', '/api/settings/ai-test', key ? { api_key: key } : {});
// ---- 自选股看板（S9） ----
export interface WatchlistItem {
  id: number;
  symbol: string;
  name?: string;
  market?: string;
  group_name?: string;
  sort_order?: number;
  created_at?: string;
  updated_at?: string;
}
export const getWatchlist = () => api<WatchlistItem[]>('GET', '/api/watchlist');
export const addWatchlistItem = (item: { symbol: string; market: string; group_name: string }) =>
  api<WatchlistItem>('POST', '/api/watchlist', item);
export const updateWatchlistGroup = (id: number, group_name: string) =>
  api<WatchlistItem>('PUT', `/api/watchlist/${id}`, { group_name });
export const deleteWatchlistItem = (id: number) => api('DELETE', `/api/watchlist/${id}`);

// ---- 行情与 K 线（S9 复用/扩展） ----
export interface Quote {
  symbol: string;
  name: string;
  market: string;
  price: number;
  change_pct: number;
  change: number;
  open: number;
  high: number;
  low: number;
  prev_close: number;
  volume: number;
  amount: number;
  timestamp: string;
  source: string;
  turnover?: number;
  pe?: number;
  total_market_cap?: number;
  float_market_cap?: number;
}
export const getQuote = (symbol: string, market: string) =>
  api<Quote>('GET', `/api/market/quote?symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}`);

export interface KlineBar {
  date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  amount: number;
}
export interface KlineResult {
  symbol: string;
  market: string;
  bars: KlineBar[];
}
export const getKline = (symbol: string, market: string, days = 120) =>
  api<KlineResult>('GET', `/api/market/kline?symbol=${encodeURIComponent(symbol)}&market=${encodeURIComponent(market)}&days=${days}`);

// ---- 关联资讯（S9） ----
export interface RelatedNewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  market: string;
  summary: string;
  level: string;
  published_at: string;
}
export const getRelatedNews = (keyword: string) =>
  api<RelatedNewsItem[]>('GET', `/api/news/related?keyword=${encodeURIComponent(keyword)}`);

// ---- 推荐中心（S10，契约与后端 /api/recommend/* 对齐） ----
export interface RecommendItem {
  id: number;
  symbol: string;
  name?: string;
  market?: string;
  rec_type: string; // 短线 / 长线
  entry_min?: number | null;
  entry_max?: number | null;
  stop_loss?: number | null;
  target?: number | null;
  valuation_min?: number | null; // 长线估值区间
  valuation_max?: number | null;
  confidence?: number | null; // 0-100
  logic?: string | null;
  risk_level?: string | null; // 低 / 中 / 高
  rec_date?: string;
  rec_price?: number | null;
  status?: string; // open ...
}

export interface BlockedItem {
  symbol: string;
  name?: string;
  rec_type?: string;
  reasons: string[];
}

export interface TodayRecommendations {
  ok?: boolean;
  date?: string;
  cached?: boolean;
  source?: 'ai' | 'rules' | string;
  items: RecommendItem[];
  blocked?: BlockedItem[];
  errors?: string[];
}

export interface HistoryItem extends RecommendItem {
  outcome?: 'win' | 'loss' | 'stop' | 'flat' | 'null' | string | null;
  result_pct?: number | null;
  result_price?: number | null;
  eval_days?: number | null;
}

export interface BacktestGroup {
  count?: number;
  win_rate?: number;
  avg_return?: number;
  total_return?: number;
  wins?: number;
  losses?: number;
  stops?: number;
  flats?: number;
}

export interface BacktestMonth {
  month?: string;
  count?: number;
  win_rate?: number;
  avg_return?: number;
}

export interface BacktestRecentItem {
  id?: number;
  symbol?: string;
  name?: string;
  rec_type?: string;
  rec_date?: string;
  confidence?: number | null;
  outcome?: string | null;
  result_pct?: number | null;
  result_price?: number | null;
  entry_price?: number | null;
  eval_days?: number | null;
}

export interface BacktestResult {
  summary?: BacktestGroup;
  by_type?: Record<string, BacktestGroup>;
  by_month?: BacktestMonth[];
  recent?: BacktestRecentItem[];
}

export interface EvaluateResult {
  evaluated?: number;
  skipped?: { id: number; symbol: string; reason: string }[];
}

export const generateRecommendations = () => api<TodayRecommendations>('POST', '/api/recommend/run');
export const getTodayRecommendations = () => api<TodayRecommendations>('GET', '/api/recommend/today');
export const getRecommendationsHistory = (limit = 50) =>
  api<HistoryItem[]>('GET', `/api/recommend/history?limit=${limit}`);
export const getRecommendationsPerformance = () => api<BacktestResult>('GET', '/api/recommend/backtest');
export const evaluateRecommendations = () => api<EvaluateResult>('POST', '/api/recommend/backtest/evaluate');

// ---- 实时追踪（S11，契约与后端 /api/tracking/* 对齐） ----
export interface TrackingItem {
  id: number;
  symbol: string;
  name?: string;
  market: string;
  /** 价格急涨急跌阈值（%）1~10，默认 3 */
  price_change_pct?: number | null;
  /** 成交量放大倍数 1.5~10，默认 3 */
  volume_ratio?: number | null;
  /** 大单金额阈值（元）50~500 万，默认 100 万 */
  big_order_amount?: number | null;
  /** 技术信号开关：1 开 / 0 关 */
  tech_signals?: number | null;
  /** AI 综合判断开关：1 开 / 0 关 */
  ai_judge?: number | null;
  /** 追踪状态：1 追踪中 / 0 已暂停 */
  active?: number | null;
  /** 今日触发次数 */
  today_triggered?: number | null;
  /** 今日事件数（后端从 tracking_events 统计） */
  today_events?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface TrackingEvent {
  id: number;
  tracking_id?: number;
  symbol: string;
  /** 异动类型：价格急涨/价格急跌/放量/大单/技术信号/突破均线/AI判断 等 */
  event_type: string;
  /** 通知级别：紧急 / 关注 / 提示 */
  level: string;
  price?: number | null;
  change_pct?: number | null;
  detail?: string | null;
  notified?: number;
  created_at?: string;
}

export interface TrackingInput {
  symbol: string;
  name?: string;
  market: string;
  price_change_pct?: number;
  volume_ratio?: number;
  big_order_amount?: number;
  tech_signals?: number;
  ai_judge?: number;
}

export interface TrackingUpdate {
  price_change_pct?: number;
  volume_ratio?: number;
  big_order_amount?: number;
  tech_signals?: number;
  ai_judge?: number;
  active?: number;
}

export interface TrackingCheckResult {
  ok?: boolean;
  /** 本次扫描的追踪数量 */
  checked?: number;
  /** 触发数量（数组时取长度）或事件列表 */
  triggered?: TrackingEvent[] | number;
  events?: TrackingEvent[];
  detail?: string;
  error?: string;
}

export const getTracking = () => api<TrackingItem[]>('GET', '/api/tracking');
export const addTracking = (input: TrackingInput) => api<TrackingItem>('POST', '/api/tracking', input);
export const updateTracking = (id: number, patch: TrackingUpdate) => api<TrackingItem>('PUT', '/api/tracking/' + id, patch);
export const deleteTracking = (id: number) => api('DELETE', '/api/tracking/' + id);
export const getTrackingEvents = (limit = 30) => api<TrackingEvent[]>('GET', '/api/tracking/events?limit=' + limit);
export const runTrackingCheck = () => api<TrackingCheckResult>('POST', '/api/tracking/check');

// ---- 盘后总结（S12，契约与后端 /api/summary/* 对齐） ----
export interface SummaryReport {
  id: number;
  trade_date: string;
  /** A股 / 港股 / 全市场（合并日报） */
  market: string;
  /** 四段式 Markdown 文本：市场全景/持仓追踪回顾/次日预判/操作建议清单 */
  content: string;
  /** 次日预判 JSON（字符串形式，可解析为对象） */
  suggestions?: string | null;
  created_at: string;
}

export interface SummaryGenerateResult {
  ok?: boolean;
  /** true 表示当日该市场已生成，未重复生成 */
  existing?: boolean;
  market?: string;
  report?: SummaryReport;
  error?: string;
}

export interface SummaryDailyResult {
  ok?: boolean;
  existing?: boolean;
  report?: SummaryReport;
  /** 通知推送结果 */
  sent?: boolean;
  reason?: string;
}

export const generateSummary = (market: string) =>
  api<SummaryGenerateResult>('POST', '/api/summary/generate?market=' + encodeURIComponent(market));
export const getTodaySummary = () => api<SummaryReport[]>('GET', '/api/summary/today');
export const getSummaryHistory = (limit = 20) =>
  api<SummaryReport[]>('GET', '/api/summary/history?limit=' + limit);
export const generateDailySummary = () => api<SummaryDailyResult>('POST', '/api/summary/daily');

// ---- 智能问答与研报解读（S13，契约与后端 /api/chat/*、/api/research/* 对齐） ----
export interface ChatUsedData {
  quotes?: unknown[];
  kline_summary?: unknown[];
  holdings?: unknown[];
  news?: unknown[];
}

/** POST /api/chat/ask 返回：{answer, category, used_data, degraded} */
export interface ChatAnswer {
  answer: string;
  category?: string;
  used_data?: ChatUsedData;
  /** true = 无 AI Key 或调用失败，走了规则降级 */
  degraded?: boolean;
  error?: string;
}

/** GET /api/chat/history 条目 */
export interface ChatHistoryItem {
  id: number;
  question: string;
  category?: string | null;
  answer?: string | null;
  degraded?: number | boolean | null;
  used_data_json?: string | null;
  created_at?: string;
}

/** GET /api/research/list 条目：{title, org(机构), rating(评级), rating_change, target_price, date, stock, url, source} */
export interface ResearchItem {
  title: string;
  org?: string | null;
  rating?: string | null;
  /** 评级变化（如：上调/首次/维持） */
  rating_change?: string | null;
  target_price?: string | number | null;
  date?: string | null;
  url?: string | null;
  /** 关联股票信息 */
  stock?: { name?: string; code?: string } | null;
  /** 数据来源：eastmoney 或 news_cache（降级源，逐条标注） */
  source?: string | null;
}

/** POST /api/research/interpret 结果：{ok, research, interpretation, holding_related, holding_match, degraded, source}；兼容整段 Markdown 或结构化字段两种返回 */
export interface ResearchInterpret {
  ok?: boolean;
  /** 被解读的研报条目（原样回传） */
  research?: ResearchItem | string | null;
  /** 整段解读文本（AI 路径为 Markdown 分段；降级为纯文本模板） */
  interpretation?: string;
  summary?: string;
  answer?: string;
  content?: string;
  core_views?: string;
  target_price?: string;
  rating_change?: string;
  key_assumptions?: string;
  risks?: string;
  holdings_relation?: string;
  /** 是否与持仓关联 */
  holding_related?: boolean;
  /** 是否命中具体持仓股票 */
  holding_match?: boolean;
  degraded?: boolean;
  source?: string | null;
}

export const askChat = (question: string) => api<ChatAnswer>('POST', '/api/chat/ask', { question });
export const getChatHistory = (limit = 30) => api<ChatHistoryItem[]>('GET', '/api/chat/history?limit=' + limit);
export const getResearchList = (keyword = '', limit = 10) =>
  api<ResearchItem[]>('GET', `/api/research/list?keyword=${encodeURIComponent(keyword)}&limit=${limit}`);
export const interpretResearch = (keyword: string) => api<ResearchInterpret>('POST', '/api/research/interpret', { keyword });
// ---- 风险分析与宏观研判（S14，契约与后端 /api/risk/*、/api/macro/* 对齐） ----
/** 预警项：{indicator, value, threshold, level}；indicator 可能是英文键或中文名 */
export interface RiskAlert {
  indicator?: string | null;
  value?: number | string | null;
  threshold?: number | string | null;
  /** 预警 / 关注 / 紧急 等 */
  level?: string | null;
  [k: string]: unknown;
}

/** 单只集中度明细项 */
export interface RiskConcentrationItem {
  symbol?: string;
  name?: string;
  market?: string;
  /** 集中度权重（小数或百分数均可） */
  weight_pct?: number | null;
  value?: number | null;
  [k: string]: unknown;
}

export interface RiskIndicators {
  /** 单只最大集中度（%） */
  concentration_max?: number | null;
  concentration_detail?: RiskConcentrationItem[] | null;
  /** 最高市场（A股/港股）占比（%） */
  market_share?: number | null;
  /** 最大回撤（%） */
  max_drawdown?: number | null;
  beta?: number | null;
  sharpe?: number | null;
  /** VaR 95% 日损失金额 */
  var?: number | null;
  [k: string]: unknown;
}

/** GET /api/risk/overview：组合风险指标 + 预警 */
export interface RiskOverview {
  total_value?: number;
  indicators?: RiskIndicators | null;
  alerts?: RiskAlert[] | null;
  updated_at?: string | null;
  error?: string;
  [k: string]: unknown;
}

/** 压力测试场景（契约与后端一致） */
export type StressScenario = 'market_down_10' | 'hk_tech_down_20' | 'cny_depreciate_5';

/** POST /api/risk/stress-test 结果 */
export interface StressTestResult {
  scenario?: string;
  /** 估算损失金额（元） */
  estimated_loss?: number;
  /** 估算损失占比（%） */
  estimated_loss_pct?: number;
  /** 明细：字符串 / 对象 / 数组 / null */
  detail?: string | Record<string, unknown> | unknown[] | null;
  error?: string;
  [k: string]: unknown;
}

/** 宏观信号级别（四色） */
export type MacroSignalLevel = 'green' | 'yellow' | 'red' | 'black';

/** 信号因子：{name, value, note} */
export interface MacroFactor {
  name?: string;
  value?: number | string | null;
  note?: string | null;
  [k: string]: unknown;
}

/** 宏观指标：{indicator|name, region, value, date, source} */
export interface MacroIndicator {
  indicator?: string;
  name?: string;
  region?: string;
  value?: number | string | null;
  date?: string | null;
  source?: string | null;
  [k: string]: unknown;
}

/** GET /api/macro/overview：信号（level 或 signal 字段，兼容 emoji） + 指标列表 */
export interface MacroOverview {
  /** 信号级别：green/yellow/red/black（后端可能放 level，或 signal 为 emoji） */
  level?: string;
  signal?: string;
  factors?: MacroFactor[] | null;
  indicators?: MacroIndicator[] | null;
  updated_at?: string | null;
  error?: string;
  [k: string]: unknown;
}

/** GET /api/risk/alerts：最近风险预警通知（notification_log type='risk'） */
export interface RiskAlertLog {
  id?: number;
  type?: string;
  title?: string;
  content?: string;
  level?: string;
  created_at?: string;
  [k: string]: unknown;
}

export const getRiskOverview = () => api<RiskOverview>('GET', '/api/risk/overview');
export const runStressTest = (scenario: StressScenario) => api<StressTestResult>('POST', '/api/risk/stress-test', { scenario });
export const getMacroOverview = () => api<MacroOverview>('GET', '/api/macro/overview');
export const refreshMacro = () => api<MacroOverview>('POST', '/api/macro/refresh');
export const getRiskAlerts = (limit = 10) => api<RiskAlertLog[]>('GET', '/api/risk/alerts?limit=' + limit);

// ---- 投资复盘（S15，契约与后端 /api/review/* 对齐） ----
export type ReviewPeriod = 'weekly' | 'monthly' | 'quarterly';

export const REVIEW_PERIOD_LABEL: Record<string, string> = {
  weekly: '周度',
  monthly: '月度',
  quarterly: '季度',
};

/** 行为偏差条目（追涨杀跌/过度交易/处置效应/确认偏差/锚定效应）
 * 后端结构：{name, detected, evidence, suggestion}；兼容 level/score/detail 旧写法 */
export interface ReviewBehavior {
  name?: string;
  /** 是否检出该偏差（后端主格式） */
  detected?: boolean;
  /** 检出证据（后端主格式） */
  evidence?: string;
  suggestion?: string;
  /** 兼容写法：明显/一般/轻微/无 */
  level?: string;
  /** 兼容写法：0-1 或 0-100 得分 */
  score?: number | null;
  /** 兼容写法 */
  detail?: string;
  [k: string]: unknown;
}

export interface ReviewReport {
  id: number;
  /** weekly / monthly / quarterly */
  period: string;
  period_start?: string | null;
  period_end?: string | null;
  /** Markdown 文本：操作盈亏/胜率/行为偏差分析等 */
  content: string;
  /** 结构化统计（后端可选返回；默认嵌入 content） */
  stats?: Record<string, unknown> | null;
  behaviors?: unknown[] | null;
  ai_used?: number | null;
  sent?: number | null;
  created_at: string;
}

/** GET /api/review/generate?period= 返回 {ok, existing, period, period_start, period_end, report, error?} */
export interface ReviewGenerateResult {
  ok?: boolean;
  /** true = 当日同周期已生成（幂等） */
  existing?: boolean;
  period?: string;
  period_start?: string | null;
  period_end?: string | null;
  report?: ReviewReport | null;
  error?: string;
}

/** GET /api/review/latest?period= 返回 {exists, report?, reason?}；period 缺省返回最新一份 */
export interface ReviewLatestResult {
  exists: boolean;
  report?: ReviewReport | null;
  reason?: string;
}

export const getReviewHistory = (limit = 20) =>
  api<ReviewReport[]>('GET', '/api/review/history?limit=' + limit);
export const generateReview = (period: ReviewPeriod) =>
  api<ReviewGenerateResult>('GET', '/api/review/generate?period=' + period);
export const getLatestReview = (period?: ReviewPeriod) =>
  api<ReviewLatestResult>('GET', '/api/review/latest' + (period ? '?period=' + period : ''));
/** 别名：getLatestReview */
export const getReviewLatest = getLatestReview;

// ---- 虚拟账本（S15，契约与后端 /api/paper/* 对齐） ----
export interface PaperAccount {
  id?: number;
  /** 当前余额（元） */
  balance?: number | null;
  /** 初始虚拟资金 */
  initial_balance?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  [k: string]: unknown;
}

export interface PaperPosition {
  symbol: string;
  name?: string | null;
  market?: string;
  quantity: number;
  /** 均价成本 */
  avg_cost?: number | null;
  /** 现价（行情失败为 null） */
  price?: number | null;
  market_value?: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
  [k: string]: unknown;
}

/** GET /api/paper/portfolio：余额 + 持仓列表 + 总资产（未开户 ok=false） */
export interface PaperPortfolio {
  ok?: boolean;
  reason?: string;
  balance?: number | null;
  positions?: PaperPosition[];
  total_assets?: number | null;
  [k: string]: unknown;
}

/** POST /api/paper/trade 与 /api/paper/trade-from-recommendation 结果 */
export interface PaperTradeResult {
  ok?: boolean;
  type?: string; // buy / sell
  symbol?: string;
  name?: string | null;
  market?: string;
  quantity?: number;
  price?: number;
  amount?: number;
  balance?: number;
  pnl?: number | null;
  avg_cost?: number | null;
  reason?: string;
  recommendation_id?: number | null;
  [k: string]: unknown;
}

export interface PaperHistoryItem {
  id: number;
  symbol: string;
  name?: string | null;
  market?: string;
  /** buy / sell */
  type: string;
  quantity: number;
  price?: number | null;
  amount?: number | null;
  /** open（持仓中买入）/ closed */
  status?: string;
  pnl?: number | null;
  /** 一键从推荐买入时携带推荐 id，手动交易为 null */
  recommendation_id?: number | null;
  opened_at?: string | null;
  closed_at?: string | null;
  [k: string]: unknown;
}

export const initPaperAccount = (initialCash?: number) =>
  api<{ ok?: boolean; existing?: boolean; account?: PaperAccount }>(
    'POST',
    '/api/paper/account',
    initialCash !== undefined && initialCash > 0 ? { initial_cash: initialCash } : {},
  );
/** 别名：initPaperAccount */
export const openPaperAccount = initPaperAccount;

/** GET /api/paper/account：{opened: bool, account: {...}|null} */
export interface PaperAccountState {
  opened: boolean;
  account?: PaperAccount | null;
  reason?: string;
  [k: string]: unknown;
}
export const getPaperAccount = () => api<PaperAccountState>('GET', '/api/paper/account');
export const getPaperPortfolio = () => api<PaperPortfolio>('GET', '/api/paper/portfolio');
export const paperTrade = (input: { symbol: string; market: string; type: 'buy' | 'sell'; quantity: number }) =>
  api<PaperTradeResult>('POST', '/api/paper/trade', input);
export const tradeFromRecommendation = (recommendation_id: number) =>
  api<PaperTradeResult>('POST', '/api/paper/trade-from-recommendation', { recommendation_id });
/** 别名：tradeFromRecommendation */
export const paperTradeFromRecommendation = tradeFromRecommendation;
export const getPaperHistory = (limit = 50) =>
  api<PaperHistoryItem[]>('GET', '/api/paper/history?limit=' + limit);

// ---- 持仓总览与仪表盘（S16） ----
export interface HoldingItem {
  symbol: string;
  name?: string | null;
  market?: string;
  currency?: string | null;
  quantity?: number;
  cost_price?: number | null;
  current_price?: number | null;
  /** 数据来源：portfolio_app（理财软件同步）/ manual（手动） */
  source?: string;
  sync_at?: string | null;
  [k: string]: unknown;
}

export interface PortfolioAccount {
  name: string;
  broker?: string | null;
  currency?: string | null;
  cash_balance?: number | null;
  [k: string]: unknown;
}

export interface NetWorth {
  date?: string | null;
  total_cash?: number | null;
  total_investments?: number | null;
  net_worth?: number | null;
  [k: string]: unknown;
}

export interface PortfolioSnapshot {
  holdings?: unknown[] | null;
  accounts?: PortfolioAccount[] | null;
  transactions?: unknown[] | null;
  net_worth?: NetWorth | null;
  synced_at?: string | null;
  [k: string]: unknown;
}

export interface PortfolioStatus {
  detected: boolean;
  db_path?: string | null;
  [k: string]: unknown;
}

/** GET /api/portfolio/overview：本地持仓明细 + 理财软件快照（账户/净值）+ 对接状态 */
export interface PortfolioOverview {
  holdings?: HoldingItem[] | null;
  snapshot?: PortfolioSnapshot | null;
  status?: PortfolioStatus | null;
  [k: string]: unknown;
}

/** POST /api/portfolio/sync 结果 */
export interface PortfolioSyncResult {
  ok?: boolean;
  reason?: string;
  holdings?: number;
  accounts?: number;
  transactions?: number;
  net_worth?: NetWorth | null;
  synced_at?: string | null;
  [k: string]: unknown;
}

/** GET /api/notifications：应用内通知 */
export interface NotificationItem {
  id: number;
  type?: string | null;
  level?: string | null;
  title: string;
  content?: string | null;
  sent_at?: string | null;
  [k: string]: unknown;
}

/** 市场快照指数（GET /api/summary/snapshot） */
export interface MarketIndex {
  symbol: string;
  name: string;
  market: string;
  price: number;
  change_pct: number;
  change: number;
  open: number;
  high: number;
  low: number;
  prev_close: number;
  amount?: number;
  volume?: number;
  timestamp?: string;
}

/** GET /api/summary/snapshot?market=A股|港股：指数/情绪/板块快照 */
export interface MarketSnapshot {
  market: string;
  indices?: MarketIndex[] | null;
  breadth?: { up?: number; down?: number; flat?: number; limit_up?: number; limit_down?: number; turnover?: number } | null;
  boards?: unknown;
  turnover?: number | null;
  timestamp?: string;
  [k: string]: unknown;
}

export const getPortfolioOverview = () => api<PortfolioOverview>('GET', '/api/portfolio/overview');
export const getPortfolioStatus = () => api<PortfolioStatus>('GET', '/api/portfolio/status');
export const syncPortfolio = () => api<PortfolioSyncResult>('POST', '/api/portfolio/sync');
export const getNotifications = (limit = 10) => api<NotificationItem[]>('GET', '/api/notifications?limit=' + limit);
export const getMarketSnapshot = (market: string) =>
  api<MarketSnapshot>('GET', '/api/summary/snapshot?market=' + encodeURIComponent(market));

/** 解析后端 400 错误 JSON {detail} → 可读文本 */
export function parseApiError(err: string | undefined, fallback = '后端不可用'): string {
  if (!err) return fallback;
  try {
    const j = JSON.parse(err) as { detail?: string };
    if (typeof j.detail === 'string' && j.detail) return j.detail;
  } catch { /* 非 JSON 直接返回原文 */ }
  return err;
}