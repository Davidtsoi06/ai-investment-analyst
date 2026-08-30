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
