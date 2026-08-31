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
