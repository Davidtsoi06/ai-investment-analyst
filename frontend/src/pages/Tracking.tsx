// S11 追踪管理：追踪列表（条件摘要/状态/今日触发）/ 添加表单（条件配置）/ 暂停·恢复 / 异动事件记录 / 手动检测
// 契约：/api/tracking{GET,POST}、/api/tracking/{id}{PUT,DELETE}、/api/tracking/events、/api/tracking/check
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import {
  addTracking,
  deleteTracking,
  getTracking,
  getTrackingEvents,
  runTrackingCheck,
  updateTracking,
} from '../services/api';
import type { TrackingEvent, TrackingItem } from '../services/api';

const MAX_TRACKING = 10;

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

/** 通知级别 → 徽章配色：紧急=danger / 关注=warning / 提示=info */
function levelVariant(level: string | null | undefined): 'danger' | 'warning' | 'info' | 'default' {
  const l = (level || '').trim();
  if (l.includes('紧急') || l === 'urgent' || l === 'emergency' || l === 'critical') return 'danger';
  if (l.includes('关注') || l === 'watch' || l === 'attention' || l === 'warning') return 'warning';
  if (l.includes('提示') || l === 'info' || l === 'notice') return 'info';
  return 'default';
}

const EVENT_TYPE_LABEL: Record<string, string> = {
  price_surge: '价格急涨',
  price_drop: '价格急跌',
  price: '价格异动',
  volume: '放量',
  big_order: '大单',
  tech_signal: '技术信号',
  tech: '技术信号',
  breakout_ma: '突破均线',
  breakout: '突破均线',
  ma_breakout: '突破均线',
  ai_judge: 'AI判断',
  ai: 'AI判断',
  '价格急涨': '价格急涨',
  '价格急跌': '价格急跌',
  '放量': '放量',
  '大单': '大单',
  '技术信号': '技术信号',
  '突破均线': '突破均线',
  'AI判断': 'AI判断',
  'AI 判断': 'AI判断',
};

function eventTypeLabel(t: string | null | undefined): string {
  const key = (t || '').trim();
  return EVENT_TYPE_LABEL[key] || key || '异动';
}

/** 大单金额：元 → 万（1000000 → 100 万） */
function fmtWan(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const wan = v / 10000;
  return (Number.isInteger(wan) ? String(wan) : wan.toFixed(1)) + ' 万';
}

/** 价格显示：A 股 2 位、港股 3 位 */
function fmtPrice(v: number | null | undefined, market?: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(market === '港股' ? 3 : 2);
}

/** 涨跌配色（A 股惯例：红涨绿跌） */
function upDownCls(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return 'text-text';
  return v > 0 ? 'text-danger' : 'text-success';
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return (v > 0 ? '+' : '') + v.toFixed(digits) + '%';
}

/** 开关徽章 */
function OnBadge({ on, label }: { on: boolean; label: string }) {
  return on ? <Badge variant="info">{label}</Badge> : <Badge variant="default">{label} 关</Badge>;
}

interface FormState {
  symbol: string;
  market: string;
  priceChangePct: string;
  volumeRatio: string;
  bigOrderWan: string;
  techSignals: boolean;
  aiJudge: boolean;
}

const DEFAULT_FORM: FormState = {
  symbol: '',
  market: 'A股',
  priceChangePct: '3',
  volumeRatio: '3',
  bigOrderWan: '100',
  techSignals: true,
  aiJudge: true,
};

export default function Tracking() {
  const [items, setItems] = useState<TrackingItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState('');

  const [events, setEvents] = useState<TrackingEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState('');

  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const listSeq = useRef(0);
  const eventsSeq = useRef(0);

  const loadTracking = useCallback(async () => {
    const seq = ++listSeq.current;
    setListLoading(true);
    setListError('');
    const r = await getTracking();
    if (seq !== listSeq.current) return;
    setListLoading(false);
    if (!r.ok) {
      setListError('追踪列表获取失败：' + (r.error || '后端不可用'));
      return;
    }
    setItems(toList<TrackingItem>(r.data));
  }, []);

  const loadEvents = useCallback(async () => {
    const seq = ++eventsSeq.current;
    setEventsLoading(true);
    setEventsError('');
    const r = await getTrackingEvents(30);
    if (seq !== eventsSeq.current) return;
    setEventsLoading(false);
    if (!r.ok) {
      setEventsError('事件记录获取失败：' + (r.error || '后端不可用'));
      return;
    }
    setEvents(toList<TrackingEvent>(r.data));
  }, []);

  useEffect(() => {
    loadTracking();
    loadEvents();
  }, [loadTracking, loadEvents]);

  // 轻量轮询（30 秒刷新列表与事件；后台标签页暂停）
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.hidden) return;
      loadTracking();
      loadEvents();
    }, 30000);
    return () => window.clearInterval(t);
  }, [loadTracking, loadEvents]);

  const full = items.length >= MAX_TRACKING;
  const activeCount = useMemo(() => items.filter((i) => i.active !== 0).length, [items]);
  const todayTotal = useMemo(() => items.reduce((s, i) => s + (typeof i.today_triggered === 'number' ? i.today_triggered : 0), 0), [items]);

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMsg({ type, text });
    window.setTimeout(() => setMsg(null), 4000);
  };

  const validateForm = (): string => {
    const symbol = form.symbol.trim();
    if (!symbol) return '请输入股票代码';
    const pct = Number(form.priceChangePct);
    if (!Number.isFinite(pct) || pct < 1 || pct > 10) return '价格阈值需在 1%~10% 之间';
    const ratio = Number(form.volumeRatio);
    if (!Number.isFinite(ratio) || ratio < 1.5 || ratio > 10) return '放量倍数需在 1.5~10 倍之间';
    const wan = Number(form.bigOrderWan);
    if (!Number.isFinite(wan) || wan < 50 || wan > 500) return '大单金额需在 50~500 万之间';
    return '';
  };

  const handleAdd = async () => {
    if (full) {
      flash('追踪数量已达 ' + MAX_TRACKING + ' 只上限，请先删除或暂停部分追踪', 'err');
      return;
    }
    const err = validateForm();
    if (err) {
      flash(err, 'err');
      return;
    }
    setSubmitting(true);
    setMsg(null);
    const r = await addTracking({
      symbol: form.symbol.trim(),
      market: form.market,
      price_change_pct: Number(form.priceChangePct),
      volume_ratio: Number(form.volumeRatio),
      big_order_amount: Math.round(Number(form.bigOrderWan) * 10000),
      tech_signals: form.techSignals ? 1 : 0,
      ai_judge: form.aiJudge ? 1 : 0,
    });
    setSubmitting(false);
    if (!r.ok) {
      flash('添加失败：' + (r.error || '后端不可用'), 'err');
      return;
    }
    const created = r.data as TrackingItem | undefined;
    flash('已添加 ' + (created?.name || created?.symbol || form.symbol.trim()) + ' 到追踪列表');
    setForm((f) => ({ ...f, symbol: '' }));
    await loadTracking();
  };

  const handleToggle = async (item: TrackingItem) => {
    const next = item.active === 0 ? 1 : 0;
    const r = await updateTracking(item.id, { active: next });
    if (r.ok) {
      flash(next === 1 ? '已恢复追踪 ' + (item.name || item.symbol) : '已暂停追踪 ' + (item.name || item.symbol));
      await loadTracking();
    } else {
      flash('操作失败：' + (r.error || '后端不可用'), 'err');
    }
  };

  const handleDelete = async (item: TrackingItem) => {
    if (!window.confirm('确定删除追踪 ' + (item.name || item.symbol) + ' ？其异动事件记录将一并删除。')) return;
    const r = await deleteTracking(item.id);
    if (r.ok) {
      flash('已删除 ' + (item.name || item.symbol));
      await Promise.all([loadTracking(), loadEvents()]);
    } else {
      flash('删除失败：' + (r.error || '后端不可用'), 'err');
    }
  };

  const handleCheck = async () => {
    setChecking(true);
    setMsg(null);
    const r = await runTrackingCheck();
    setChecking(false);
    if (!r.ok) {
      flash('手动检测失败：' + (r.error || '后端不可用'), 'err');
      return;
    }
    const d = r.data as Record<string, unknown> | undefined;
    const triggeredRaw = d?.triggered;
    const triggeredCount = Array.isArray(triggeredRaw) ? triggeredRaw.length : typeof triggeredRaw === 'number' ? triggeredRaw : (Array.isArray(d?.events) ? (d.events as unknown[]).length : 0);
    const checked = typeof d?.checked === 'number' ? d.checked : items.length;
    flash('检测完成：扫描 ' + checked + ' 只' + (triggeredCount ? '，触发 ' + triggeredCount + ' 次异动' : '，无异动触发'));
    await Promise.all([loadTracking(), loadEvents()]);
  };

  const inputCls = 'h-10 rounded border border-border px-3 text-sm bg-white focus:outline-none focus:border-primary-500';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">追踪管理</h1>
          <p className="text-xs text-text-muted mt-1">最多 10 只 · 价格急涨急跌 / 放量 / 大单 / 技术信号 / AI 综合判断 · 分级通知</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => { loadTracking(); loadEvents(); }} disabled={listLoading && eventsLoading}>
            刷新
          </Button>
          <Button onClick={handleCheck} disabled={checking}>
            {checking ? '检测中...' : '手动检测'}
          </Button>
        </div>
      </div>
      {msg && <p className={'text-sm ' + (msg.type === 'ok' ? 'text-success' : 'text-danger')}>{msg.text}</p>}

      {/* 添加追踪：代码 + 市场 + 异动条件配置 */}
      <Card>
        <h2 className="font-bold text-sm mb-3">添加追踪</h2>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={form.symbol}
            onChange={(e) => setForm((f) => ({ ...f, symbol: e.target.value }))}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
            placeholder="股票代码，如 600519 / 00700"
            className={inputCls + ' w-44'}
          />
          <select value={form.market} onChange={(e) => setForm((f) => ({ ...f, market: e.target.value }))} className={inputCls}>
            <option value="A股">A股</option>
            <option value="港股">港股</option>
          </select>
          <div className={'flex items-center gap-1 ' + inputCls + ' w-40'}>
            <span className="text-xs text-text-secondary whitespace-nowrap">价格</span>
            <input
              type="number"
              min={1}
              max={10}
              step={0.5}
              value={form.priceChangePct}
              onChange={(e) => setForm((f) => ({ ...f, priceChangePct: e.target.value }))}
              className="w-12 bg-transparent text-sm focus:outline-none font-number"
            />
            <span className="text-xs text-text-secondary">%</span>
          </div>
          <div className={'flex items-center gap-1 ' + inputCls + ' w-40'}>
            <span className="text-xs text-text-secondary whitespace-nowrap">放量</span>
            <input
              type="number"
              min={1.5}
              max={10}
              step={0.5}
              value={form.volumeRatio}
              onChange={(e) => setForm((f) => ({ ...f, volumeRatio: e.target.value }))}
              className="w-12 bg-transparent text-sm focus:outline-none font-number"
            />
            <span className="text-xs text-text-secondary">倍</span>
          </div>
          <div className={'flex items-center gap-1 ' + inputCls + ' w-44'}>
            <span className="text-xs text-text-secondary whitespace-nowrap">大单</span>
            <input
              type="number"
              min={50}
              max={500}
              step={10}
              value={form.bigOrderWan}
              onChange={(e) => setForm((f) => ({ ...f, bigOrderWan: e.target.value }))}
              className="w-16 bg-transparent text-sm focus:outline-none font-number"
            />
            <span className="text-xs text-text-secondary">万</span>
          </div>
          <label className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
            <input type="checkbox" checked={form.techSignals} onChange={(e) => setForm((f) => ({ ...f, techSignals: e.target.checked }))} className="accent-primary-500" />
            <span>技术信号</span>
          </label>
          <label className="flex items-center gap-1.5 text-sm cursor-pointer select-none">
            <input type="checkbox" checked={form.aiJudge} onChange={(e) => setForm((f) => ({ ...f, aiJudge: e.target.checked }))} className="accent-primary-500" />
            <span>AI 判断</span>
          </label>
          <Button onClick={handleAdd} disabled={submitting || full || !form.symbol.trim()}>
            {submitting ? '添加中...' : full ? '已达上限' : '添加追踪'}
          </Button>
        </div>
        <p className="text-xs text-text-muted mt-2">
          已追踪 {items.length} / {MAX_TRACKING} 只{full ? '（已达上限，请先删除或暂停）' : '（异动同股同类 15 分钟不重复通知；突破均线随技术信号检测）'}
        </p>
      </Card>

      {/* 追踪列表 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">追踪列表</h2>
          <span className="text-xs text-text-muted">追踪中 {activeCount} · 今日触发 {todayTotal} 次</span>
        </div>
        {listError && <p className="text-sm text-danger mb-2">{listError}</p>}
        {listLoading && items.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-text-muted">暂无追踪，先在上方添加一只（如 600519 贵州茅台）。</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {items.map((item) => {
              const active = item.active !== 0;
              return (
                <div key={item.id} className={'border rounded-lg p-3 flex flex-col gap-2 ' + (active ? 'border-border' : 'border-dashed border-border opacity-80')}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm">{item.name || item.symbol}</span>
                    <span className="text-xs text-text-muted font-number">{item.symbol}</span>
                    <Badge variant={item.market === '港股' ? 'info' : 'default'}>{item.market || 'A股'}</Badge>
                    <Badge variant={active ? 'success' : 'default'}>{active ? '追踪中' : '已暂停'}</Badge>
                    <span className="ml-auto text-xs text-text-secondary">
                      今日 <span className="font-number text-primary-700">{item.today_triggered ?? 0}</span> 次
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="warning">价格 ±{item.price_change_pct ?? 3}%</Badge>
                    <Badge variant="warning">放量 {item.volume_ratio ?? 3} 倍</Badge>
                    <Badge variant="warning">大单 {fmtWan(item.big_order_amount ?? 1000000)}</Badge>
                    <OnBadge on={(item.tech_signals ?? 1) === 1} label="技术信号" />
                    <OnBadge on={(item.ai_judge ?? 1) === 1} label="AI 判断" />
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <Button size="sm" variant="secondary" onClick={() => handleToggle(item)}>
                      {active ? '暂停' : '恢复'}
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => handleDelete(item)}>删除</Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* 异动事件记录 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">异动事件</h2>
          <span className="text-xs text-text-muted">最近 30 条 · 手动检测与轮询检测都会记录</span>
          <div className="ml-auto">
            <Button variant="secondary" size="sm" onClick={loadEvents} disabled={eventsLoading}>
              {eventsLoading ? '刷新中...' : '刷新事件'}
            </Button>
          </div>
        </div>
        {eventsError && <p className="text-sm text-danger mb-2">{eventsError}</p>}
        {eventsLoading && events.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-text-muted">暂无异动事件。行情波动达到配置条件时自动触发，也可点击右上角「手动检测」。</p>
        ) : (
          <div className="divide-y divide-border">
            {events.map((ev) => (
              <div key={ev.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                <span className="text-xs text-text-muted font-number w-36">{ev.created_at || ''}</span>
                <Badge variant={levelVariant(ev.level)}>{ev.level || '提示'}</Badge>
                <Badge variant="default">{eventTypeLabel(ev.event_type)}</Badge>
                <span className="text-sm font-medium">{ev.symbol}</span>
                {(ev.price != null || ev.change_pct != null) && (
                  <span className={'text-xs font-number ' + (ev.change_pct ? upDownCls(ev.change_pct) : 'text-text-secondary')}>
                    {ev.price != null ? fmtPrice(ev.price) : ''}
                    {ev.change_pct != null && ev.change_pct !== 0 ? ' ' + fmtPct(ev.change_pct) : ''}
                  </span>
                )}
                {ev.detail && <span className="text-xs text-text-secondary w-full sm:w-auto sm:flex-1 sm:min-w-40 line-clamp-2">{ev.detail}</span>}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
