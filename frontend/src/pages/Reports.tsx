// 收盘报告（V1.0.6 重塑）：交易日 12:15 午间收盘报告 / 16:15 全天收盘报告（A股+港股一次合并）
// + 盘中临时总结（随时手动生成，独立类型显示，不与收盘报告混淆）
// 契约：/api/summary/{today,history,lunch,daily,intraday}
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import {
  generateCloseReport,
  generateIntradayReport,
  generateLunchReport,
  getSummaryHistory,
  getTodaySummary,
  parseApiError,
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

/** 报告类型元信息（V1.0.6 kind；旧记录归一为 daily） */
function kindMeta(kind: string | null | undefined): { label: string; variant: 'info' | 'success' | 'warning' | 'default' } {
  const k = (kind || '').toLowerCase();
  if (k === 'lunch') return { label: '午间收盘', variant: 'info' };
  if (k === 'intraday') return { label: '盘中临时总结', variant: 'warning' };
  return { label: '全天收盘', variant: 'success' };
}

/** UTC ISO → 北京时间 "MM-DD HH:mm"（旧格式无时区则原样截取） */
function fmtBjt(s: string | null | undefined): string {
  if (!s) return '';
  const d = new Date(s);
  if (!Number.isNaN(d.getTime())) {
    const bj = new Date(d.getTime() + 8 * 3600 * 1000);
    const p = (n: number) => String(n).padStart(2, '0');
    return (
      p(bj.getUTCMonth() + 1) + '-' + p(bj.getUTCDate()) + ' ' + p(bj.getUTCHours()) + ':' + p(bj.getUTCMinutes())
    );
  }
  return s.slice(0, 16);
}

/** 四段式 Markdown 分行渲染：标题/分隔线/emoji 行着色 */
function renderSummary(content: string, keyPrefix: string) {
  return (content || '').split('\n').map((line, i) => {
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

/** 单份报告内容卡（标题行：类型徽章 + 市场 + 日期 + 北京时间生成时刻 + AI/规则来源） */
function ReportCard({ r, tone }: { r: SummaryReport; tone?: 'border' | 'highlight' }) {
  const meta = kindMeta(r.kind);
  const marketTag = r.market === '合并' ? 'A股+港股' : r.market;
  const isSingleMarket = r.market !== '合并';
  return (
    <div className={'rounded-lg p-3 ' + (tone === 'highlight' ? 'border border-warning/40 bg-warning/5' : 'border border-border')}>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <Badge variant={meta.variant}>{meta.label}</Badge>
        {marketTag && marketTag !== '—' && (
          <Badge variant={isSingleMarket ? 'default' : 'info'}>{marketTag}</Badge>
        )}
        <span className="text-sm font-medium">{r.trade_date}</span>
        <span className="text-xs text-text-muted">
          生成于 {fmtBjt(r.created_at)}
          {r.ai_used === false && ' · 规则引擎'}
        </span>
      </div>
      {r.title && <div className="text-xs font-medium text-primary-800 mb-1">{r.title.replace(/^📊\s*/g, '')}</div>}
      {renderSummary(r.content, 'rep-' + r.id)}
    </div>
  );
}

export default function Reports() {
  const [today, setToday] = useState<SummaryReport[]>([]);
  const [todayLoading, setTodayLoading] = useState(false);
  const [todayError, setTodayError] = useState('');

  const [history, setHistory] = useState<SummaryReport[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const [generating, setGenerating] = useState<string | null>(null); // lunch / daily / intraday
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
    else setTodayError('报告获取失败：' + parseApiError(r.error));
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError('');
    const r = await getSummaryHistory(30);
    setHistoryLoading(false);
    if (r.ok) setHistory(toList<SummaryReport>(r.data));
    else setHistoryError('历史报告获取失败：' + parseApiError(r.error));
  }, []);

  useEffect(() => {
    loadToday();
    loadHistory();
  }, [loadToday, loadHistory]);

  // 30 秒轻量轮询（定时报告生成后页面自动更新；后台标签页暂停）
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

  const handleGen = async (kind: 'lunch' | 'daily' | 'intraday') => {
    setGenerating(kind);
    setMsg(null);
    const fn = kind === 'lunch' ? generateLunchReport : kind === 'daily' ? generateCloseReport : generateIntradayReport;
    const r = await fn();
    setGenerating(null);
    if (!r.ok) {
      flash('生成失败：' + parseApiError(r.error), 'err');
      return;
    }
    const d = r.data as { cached?: boolean; ok?: boolean; reason?: string } | undefined;
    if (d?.cached) {
      flash('今日该报告已生成（不重复生成），已刷新列表');
    } else if (d?.ok === false) {
      flash('生成失败：' + (d.reason || '未知原因'), 'err');
    } else {
      flash('已生成，稍候自动刷新');
    }
    await Promise.all([loadToday(), loadHistory()]);
  };

  // 今日分组：合并两市（lunch/daily/intraday）+ 旧版单市场记录
  const byKind = useMemo(() => {
    const merged = today.filter((r) => r.market === '合并');
    const legacy = today.filter((r) => r.market !== '合并');
    const lunch = merged.find((r) => (r.kind || 'daily').toLowerCase() === 'lunch') || null;
    const daily = merged.find((r) => (r.kind || 'daily').toLowerCase() === 'daily') || null;
    const intraday = merged.filter((r) => (r.kind || '').toLowerCase() === 'intraday');
    return { lunch, daily, intraday, legacy };
  }, [today]);

  const todayNonEmpty = byKind.lunch || byKind.daily || byKind.intraday.length > 0 || byKind.legacy.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">收盘报告</h1>
          <p className="text-xs text-text-muted mt-1">
            交易日 12:15 自动生成午间收盘报告 · 16:15 自动生成全天收盘报告（每次均含 A股+港股）· 盘中可随时生成「盘中临时总结」，两者分开显示
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => { loadToday(); loadHistory(); }} disabled={todayLoading && historyLoading}>
            刷新
          </Button>
          <Button size="sm" onClick={() => handleGen('intraday')} disabled={generating !== null}>
            {generating === 'intraday' ? '生成中（约 10~30 秒）...' : '📝 生成盘中总结'}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => handleGen('lunch')} disabled={generating !== null}>
            {generating === 'lunch' ? '生成中...' : '生成午间报告'}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => handleGen('daily')} disabled={generating !== null}>
            {generating === 'daily' ? '生成中...' : '生成全天报告'}
          </Button>
        </div>
      </div>
      {msg && <p className={'text-sm ' + (msg.type === 'ok' ? 'text-success' : 'text-danger')}>{msg.text}</p>}

      {/* 今日报告：午间收盘 / 全天收盘 / 盘中临时总结 分区显示 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">今日报告</h2>
          {today[0]?.trade_date && <span className="text-xs text-text-muted">{today[0].trade_date}</span>}
          <span className="text-xs text-text-muted ml-auto">30 秒自动刷新 · 生成需拉取两市实时行情，约 10~30 秒</span>
        </div>
        {todayError && <p className="text-sm text-danger mb-2">{todayError}</p>}
        {todayLoading && !todayNonEmpty ? (
          <Loading />
        ) : !todayNonEmpty ? (
          <EmptyState
            icon="📋"
            title="今日暂无报告"
            description="交易日 12:15 将自动生成「午间收盘报告」、16:15 自动生成「全天收盘报告」；现在也可点击右上角「生成盘中总结」获取一份截至目前的行情总结。"
          />
        ) : (
          <div className="space-y-3">
            {byKind.lunch && (
              <div>
                <div className="text-xs font-bold text-primary-700 mb-1.5">🌤 午间收盘报告（12:15）</div>
                <ReportCard r={byKind.lunch} />
              </div>
            )}
            {byKind.daily && (
              <div>
                <div className="text-xs font-bold text-primary-700 mb-1.5">🌆 全天收盘报告（16:15）</div>
                <ReportCard r={byKind.daily} tone="highlight" />
              </div>
            )}
            {byKind.intraday.length > 0 && (
              <div>
                <div className="text-xs font-bold text-warning mb-1.5">⏱ 盘中临时总结（随时生成 · 独立于收盘报告）</div>
                {byKind.intraday.map((r) => (
                  <div key={r.id} className="mb-2 last:mb-0">
                    <ReportCard r={r} />
                  </div>
                ))}
              </div>
            )}
            {byKind.legacy.length > 0 && (
              <div>
                <div className="text-xs font-bold text-text-secondary mb-1.5">旧版单市场报告（兼容显示）</div>
                {byKind.legacy.map((r) => (
                  <div key={r.id} className="mb-2 last:mb-0">
                    <ReportCard r={r} />
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 历史报告：按类型分徽章展示 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">历史报告</h2>
          <span className="text-xs text-text-muted">最近 30 份 · 点击展开查看内容</span>
          <div className="ml-auto">
            <Button variant="secondary" size="sm" onClick={loadHistory} disabled={historyLoading}>
              {historyLoading ? '刷新中...' : '刷新'}
            </Button>
          </div>
        </div>
        {historyError && <p className="text-sm text-danger mb-2">{historyError}</p>}
        {historyLoading && history.length === 0 ? (
          <Loading />
        ) : history.length === 0 ? (
          <EmptyState icon="🗂️" title="暂无历史报告" description="收盘报告与盘中总结都会自动存档在这里（类型徽章区分），点击条目展开查看。" />
        ) : (
          <div className="divide-y divide-border">
            {history.map((h) => {
              const open = expandedId === h.id;
              const meta = kindMeta(h.kind);
              return (
                <div key={h.id}>
                  <button
                    type="button"
                    onClick={() => setExpandedId(open ? null : h.id)}
                    className="w-full flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-left hover:bg-primary-50/60 rounded px-2"
                  >
                    <span className="text-xs text-text-muted font-number w-24">{h.trade_date}</span>
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                    {h.market && h.market !== '合并' && <Badge variant="default">{h.market}</Badge>}
                    <span className="text-xs text-text-muted font-number">{fmtBjt(h.created_at)}</span>
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
