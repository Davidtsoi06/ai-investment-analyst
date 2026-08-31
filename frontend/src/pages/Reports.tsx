// S12 盘后报告：今日报告（A股/港股 四段式）/ 合并日报 / 历史报告
// 契约：/api/summary/{today,generate,daily,history}（后端契约见 t1）
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import {
  generateDailySummary,
  generateSummary,
  getSummaryHistory,
  getTodaySummary,
} from '../services/api';
import type { SummaryReport } from '../services/api';

/** 兼容后端返回数组或 {items:[...]}/{list:[...]} 两种包装 */
function toList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>;
    if (Array.isArray(d.items)) return d.items as T[];
    if (Array.isArray(d.list)) return d.list as T[];
  }
  return [];
}

/** 合并日报市场标识（后端用「全市场」，兼容 合并/日报/汇总 等写法） */
const DAILY_MARKETS = ['全市场', '合并', '合并日报', '日报', '汇总', 'daily', 'all'];

function isDaily(r: SummaryReport): boolean {
  const m = (r.market || '').trim();
  return DAILY_MARKETS.some((k) => m.includes(k) || m.toLowerCase() === k);
}

function marketVariant(m: string | undefined | null): 'success' | 'danger' | 'warning' | 'info' | 'default' {
  const s = (m || '').trim();
  if (s.includes('港股')) return 'info';
  if (s.includes('全市场') || s.includes('合并') || s.includes('日报')) return 'warning';
  return 'default';
}

/** 四段式 Markdown 分行渲染：标题/分隔线/emoji 行着色，参考 News 页 renderPremarket */
function renderSummary(content: string, keyPrefix: string) {
  return content.split('\n').map((line, i) => {
    const t = line.trim();
    if (!t) return <div key={keyPrefix + '-e' + i} className="h-1.5" />;
    let cls = 'text-text-secondary';
    if (t.startsWith('📋') || t.includes('━━') || /^#{1,4}\s/.test(t)) cls = 'font-bold text-primary-900';
    else if (t.startsWith('🔴') || t.startsWith('⚠')) cls = 'text-danger';
    else if (t.startsWith('🟡')) cls = 'text-warning';
    else if (t.startsWith('🟢')) cls = 'text-success';
    else if (t.startsWith('【')) cls = 'font-bold text-primary-700';
    else if (t.startsWith('　')) cls = 'text-text-secondary';
    return (
      <p key={keyPrefix + '-' + i} className={'text-sm leading-6 whitespace-pre-wrap ' + cls}>
        {line.replace(/\*\*/g, '')}
      </p>
    );
  });
}

/** 时间显示：created_at "2026-08-31 15:30:05" → "15:30" */
function fmtTime(s: string | undefined | null): string {
  if (!s) return '';
  const m = /(\d{2}):(\d{2})/.exec(s);
  return m ? m[1] + ':' + m[2] : s.slice(0, 5);
}

export default function Reports() {
  const [today, setToday] = useState<SummaryReport[]>([]);
  const [todayLoading, setTodayLoading] = useState(false);
  const [todayError, setTodayError] = useState('');

  const [history, setHistory] = useState<SummaryReport[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const [generating, setGenerating] = useState<string | null>(null); // A股 / 港股 / daily
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const todaySeq = useRef(0);

  const loadToday = useCallback(async () => {
    const seq = ++todaySeq.current;
    setTodayLoading(true);
    setTodayError('');
    const r = await getTodaySummary();
    if (seq !== todaySeq.current) return;
    setTodayLoading(false);
    if (r.ok) setToday(toList<SummaryReport>(r.data));
    else setTodayError('今日报告获取失败：' + (r.error || '后端不可用'));
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError('');
    const r = await getSummaryHistory(20);
    setHistoryLoading(false);
    if (r.ok) setHistory(toList<SummaryReport>(r.data));
    else setHistoryError('历史报告获取失败：' + (r.error || '后端不可用'));
  }, []);

  useEffect(() => {
    loadToday();
    loadHistory();
  }, [loadToday, loadHistory]);

  // 30 秒轻量轮询（收盘后自动生成时页面自动更新；后台标签页暂停）
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.hidden) return;
      loadToday();
    }, 30000);
    return () => window.clearInterval(t);
  }, [loadToday]);

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMsg({ type, text });
    window.setTimeout(() => setMsg(null), 6000);
  };

  const handleGenerate = async (market: string) => {
    setGenerating(market);
    setMsg(null);
    const r = await generateSummary(market);
    setGenerating(null);
    if (!r.ok) {
      flash('生成失败：' + (r.error || '后端不可用'), 'err');
      return;
    }
    const d = r.data as { existing?: boolean; report?: SummaryReport } | undefined;
    if (d?.existing) {
      flash(market + ' 今日报告已生成（不重复生成），已刷新列表');
    } else {
      flash(market + ' 总结生成完成');
    }
    await Promise.all([loadToday(), loadHistory()]);
  };

  const handleDaily = async () => {
    setGenerating('daily');
    setMsg(null);
    const r = await generateDailySummary();
    setGenerating(null);
    if (!r.ok) {
      flash('合并日报生成失败：' + (r.error || '后端不可用'), 'err');
      return;
    }
    const d = r.data as { existing?: boolean; sent?: boolean; reason?: string } | undefined;
    if (d?.existing) {
      flash('今日合并日报已生成（不重复生成）' + (d.sent ? '，已推送通知' : ''));
    } else {
      flash('合并日报生成完成' + (d?.sent ? '，已推送通知' : d?.reason ? '（' + d.reason + '）' : ''));
    }
    await Promise.all([loadToday(), loadHistory()]);
  };

  const todayDaily = useMemo(() => today.filter(isDaily), [today]);
  const todayMarkets = useMemo(() => today.filter((r) => !isDaily(r)), [today]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">盘后报告</h1>
          <p className="text-xs text-text-muted mt-1">收盘后自动生成 · 15:30 A股 / 16:30 港股总结 · 17:30 合并日报 · 四段式：市场全景 / 持仓追踪回顾 / 次日预判 / 操作建议</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => { loadToday(); loadHistory(); }} disabled={todayLoading && historyLoading}>
            刷新
          </Button>
          <Button variant="secondary" size="sm" onClick={() => handleGenerate('A股')} disabled={generating !== null}>
            {generating === 'A股' ? '生成中...' : '生成 A股 总结'}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => handleGenerate('港股')} disabled={generating !== null}>
            {generating === '港股' ? '生成中...' : '生成港股总结'}
          </Button>
          <Button size="sm" onClick={handleDaily} disabled={generating !== null}>
            {generating === 'daily' ? '合并中...' : '合并日报'}
          </Button>
        </div>
      </div>
      {msg && <p className={'text-sm ' + (msg.type === 'ok' ? 'text-success' : 'text-danger')}>{msg.text}</p>}

      {/* 今日报告：合并日报 + 各市场分区 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">今日报告</h2>
          {today.length > 0 && <span className="text-xs text-text-muted">{today[0].trade_date}</span>}
          <span className="text-xs text-text-muted ml-auto">30 秒自动刷新 · 生成会拉取实时行情，约 10~30 秒</span>
        </div>
        {todayError && <p className="text-sm text-danger mb-2">{todayError}</p>}
        {todayLoading && today.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : today.length === 0 ? (
          <p className="text-sm text-text-muted">
            今日暂无报告。收盘后自动生成（A股 15:30 / 港股 16:30 / 合并日报 17:30），也可点击右上角「生成 A股 总结」「生成港股总结」手动生成。
          </p>
        ) : (
          <div className="space-y-4">
            {todayDaily.map((r) => (
              <div key={r.id} className="border border-warning/40 rounded-lg p-3 bg-warning/5">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <Badge variant="warning">合并日报</Badge>
                  <span className="text-sm font-medium">{r.trade_date}</span>
                  <span className="text-xs text-text-muted">生成于 {fmtTime(r.created_at)}</span>
                </div>
                {renderSummary(r.content, 'daily-' + r.id)}
              </div>
            ))}
            {todayMarkets.map((r) => (
              <div key={r.id} className="border border-border rounded-lg p-3">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <Badge variant={marketVariant(r.market)}>{r.market || '—'}</Badge>
                  <span className="text-sm font-medium">{r.trade_date}</span>
                  <span className="text-xs text-text-muted">生成于 {fmtTime(r.created_at)}</span>
                </div>
                {renderSummary(r.content, 'mkt-' + r.id)}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* 历史报告 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">历史报告</h2>
          <span className="text-xs text-text-muted">最近 20 份 · 点击展开查看内容</span>
          <div className="ml-auto">
            <Button variant="secondary" size="sm" onClick={loadHistory} disabled={historyLoading}>
              {historyLoading ? '刷新中...' : '刷新'}
            </Button>
          </div>
        </div>
        {historyError && <p className="text-sm text-danger mb-2">{historyError}</p>}
        {historyLoading && history.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : history.length === 0 ? (
          <p className="text-sm text-text-muted">暂无历史报告，生成后自动存档。</p>
        ) : (
          <div className="divide-y divide-border">
            {history.map((h) => {
              const open = expandedId === h.id;
              return (
                <div key={h.id}>
                  <button
                    type="button"
                    onClick={() => setExpandedId(open ? null : h.id)}
                    className="w-full flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-left hover:bg-primary-50/60 rounded px-2"
                  >
                    <span className="text-xs text-text-muted font-number w-24">{h.trade_date}</span>
                    <Badge variant={marketVariant(h.market)}>{isDaily(h) ? '合并日报' : h.market || '—'}</Badge>
                    <span className="text-xs text-text-muted font-number">{fmtTime(h.created_at)}</span>
                    <span className="text-xs text-text-secondary ml-auto">{open ? '收起 ▲' : '展开 ▼'}</span>
                  </button>
                  {open && (
                    <div className="px-2 pb-3">
                      <div className="border-l-2 border-primary-100 pl-3">
                        {renderSummary(h.content, 'his-' + h.id)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
