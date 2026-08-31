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
