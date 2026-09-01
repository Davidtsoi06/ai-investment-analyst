// 前端共享格式化/兼容工具：统一各页面的数值显示与涨跌配色（需求文档十一章 UI 规范）
// 涨跌配色规范：涨绿 #52C41A / 跌红 #FF4D4F（成功=涨=绿，与 Amount 组件一致）

/** 兼容后端返回数组或 {items:[...]}/{list:[...]}/{reports:[...]}/{positions:[...]} 等包装 */
export function toList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>;
    if (Array.isArray(d.items)) return d.items as T[];
    if (Array.isArray(d.list)) return d.list as T[];
    if (Array.isArray(d.reports)) return d.reports as T[];
    if (Array.isArray(d.positions)) return d.positions as T[];
  }
  return [];
}

/** 数字安全取值：null/undefined/NaN/空串 → null；数字或数字字符串 → number */
export function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** 比率归一化为百分数：0.667 → 66.7；66.7 → 66.7 */
export function toPercent(v: number | string | null | undefined): number | null {
  const n = num(v);
  if (n === null) return null;
  return Math.abs(n) <= 1 ? n * 100 : n;
}

/** 涨跌/盈亏配色（统一规范：涨绿跌红，0/空为中性灰） */
export function upDownCls(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return 'text-text';
  return v > 0 ? 'text-success' : 'text-danger';
}

/** 百分数显示：0.667 → +66.7%；66.7 → +66.7%；空 → — */
export function fmtPct(v: number | string | null | undefined, digits = 1): string {
  const p = toPercent(v);
  return p === null ? '—' : (p > 0 ? '+' : '') + p.toFixed(digits) + '%';
}

/** 金额显示（元 → 万/亿 中文缩写，¥ 前缀） */
export function fmtMoney(v: number | string | null | undefined): string {
  const n = num(v);
  if (n === null) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e8) return '¥' + (n / 1e8).toFixed(2) + ' 亿';
  if (abs >= 1e4) return '¥' + (n / 1e4).toFixed(2) + ' 万';
  return '¥' + n.toFixed(2);
}

/** 大数值（市值等）：万亿/亿/万，无币种前缀 */
export function fmtBig(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return (v / 1e12).toFixed(2) + ' 万亿';
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + ' 亿';
  if (abs >= 1e4) return (v / 1e4).toFixed(2) + ' 万';
  return String(Math.round(v));
}

/** 成交量：亿股/万股/股 */
export function fmtVolume(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + ' 亿股';
  if (abs >= 1e4) return (v / 1e4).toFixed(2) + ' 万股';
  return Math.round(v) + ' 股';
}

/** 大单金额（元 → 万）：1000000 → 100 万 */
export function fmtWan(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const wan = v / 10000;
  return (Number.isInteger(wan) ? String(wan) : wan.toFixed(1)) + ' 万';
}

/** 价格显示：A 股 2 位小数、港股 3 位小数 */
export function fmtPrice(v: number | null | undefined, market?: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(market === '港股' ? 3 : 2);
}

/** 数值显示（默认两位小数） */
export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(digits);
}

/** 时间显示：ISO(UTC) → 北京时间；本地 "YYYY-MM-DD HH:MM:SS" → "MM-DD HH:MM" */
export function fmtTime(s: string | null | undefined): string {
  if (!s) return '';
  if (s.includes('T')) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      const bj = new Date(d.getTime() + 8 * 3600 * 1000);
      const p = (n: number) => String(n).padStart(2, '0');
      return p(bj.getMonth() + 1) + '-' + p(bj.getDate()) + ' ' + p(bj.getHours()) + ':' + p(bj.getMinutes());
    }
  }
  const m = /(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})/.exec(s);
  if (m) return m[1].slice(5) + ' ' + m[2];
  return s.slice(0, 16);
}
