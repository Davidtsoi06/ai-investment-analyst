// 后端 API 客户端：经 Electron 主进程代理（window.backend），浏览器调试时直连

export interface ApiResult<T = unknown> {
  ok: boolean;
  status?: number;
  error?: string;
  data?: T;
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<ApiResult<T>> {
  if (window.backend) {
    const res = (await window.backend.request(method, path, body)) as ApiResult<T>;
    return res;
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

