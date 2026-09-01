// S9 自选股看板：分组管理 / 实时行情 / 基本面速览 / ECharts K 线（MA+RSI）/ 关联资讯
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import Stat from '../components/ui/Stat';
import KLineChart from '../components/KLineChart';
import {
  addWatchlistItem,
  deleteWatchlistItem,
  getKline,
  getQuote,
  getRelatedNews,
  getWatchlist,
  parseApiError,
  updateWatchlistGroup,
} from '../services/api';
import type { KlineBar, Quote, RelatedNewsItem, WatchlistItem } from '../services/api';
import { fmtBig, fmtNum, fmtVolume, toList, upDownCls } from '../lib/format';

type Period = 'day' | 'week' | 'month';

const PERIODS: Record<Period, { label: string; days: number }> = {
  day: { label: '日K', days: 120 },
  week: { label: '周K', days: 240 },
  month: { label: '月K', days: 500 },
};

const LEVEL_BADGE: Record<string, 'danger' | 'warning' | 'default'> = {
  '重大': 'danger',
  '中等': 'warning',
  '一般': 'default',
};

/** 日K按周/月聚合（周K：ISO 周；月K：自然月） */
function aggregateBars(bars: KlineBar[], unit: 'week' | 'month'): KlineBar[] {
  const map = new Map<string, KlineBar>();
  for (const b of bars) {
    const d = new Date(b.date + 'T00:00:00');
    if (Number.isNaN(d.getTime())) continue;
    let key: string;
    if (unit === 'month') {
      key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    } else {
      const day = d.getDay() || 7; // 周一=1 ... 周日=7
      const thu = new Date(d);
      thu.setDate(d.getDate() + 4 - day);
      const yearStart = new Date(thu.getFullYear(), 0, 1);
      const week = Math.ceil(((thu.getTime() - yearStart.getTime()) / 86400000 + yearStart.getDay() + 1) / 7);
      key = thu.getFullYear() + '-W' + String(week).padStart(2, '0');
    }
    const prev = map.get(key);
    if (!prev) {
      map.set(key, { ...b, date: key });
    } else {
      prev.close = b.close;
      prev.high = Math.max(prev.high, b.high);
      prev.low = Math.min(prev.low, b.low);
      prev.volume += b.volume;
      prev.amount += b.amount;
    }
  }
  return [...map.values()];
}

export default function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [activeGroup, setActiveGroup] = useState('全部');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState({ symbol: '', market: 'A股', group: '默认' });
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState('');
  const [klineBars, setKlineBars] = useState<KlineBar[]>([]);
  const [klineLoading, setKlineLoading] = useState(false);
  const [klineError, setKlineError] = useState('');
  const [period, setPeriod] = useState<Period>('day');
  const [news, setNews] = useState<RelatedNewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError] = useState('');

  const quoteSeq = useRef(0);
  const klineSeq = useRef(0);
  const newsSeq = useRef(0);

  const groupNames = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) set.add(it.group_name || '默认');
    const arr = [...set];
    const idx = arr.indexOf('默认');
    if (idx > 0) {
      arr.splice(idx, 1);
      arr.unshift('默认');
    }
    return arr;
  }, [items]);

  const tabs = useMemo(() => {
    const all = { name: '全部', count: items.length };
    const rest = groupNames.map((g) => ({ name: g, count: items.filter((i) => (i.group_name || '默认') === g).length }));
    return [all, ...rest];
  }, [items, groupNames]);

  const groupItems = useMemo(() => {
    if (activeGroup === '全部') return items;
    return items.filter((i) => (i.group_name || '默认') === activeGroup);
  }, [items, activeGroup]);

  const selected = useMemo(() => items.find((i) => i.id === selectedId) ?? null, [items, selectedId]);

  const loadWatchlist = useCallback(async () => {
    setLoadingList(true);
    const r = await getWatchlist();
    setLoadingList(false);
    if (!r.ok) {
      setMsg({ type: 'err', text: '自选股列表获取失败：' + parseApiError(r.error) });
      return;
    }
    const list = toList<WatchlistItem>(r.data);
    setItems(list);
    setSelectedId((prev) => {
      if (prev !== null && list.some((i) => i.id === prev)) return prev;
      return list.length > 0 ? list[0].id : null;
    });
  }, []);

  useEffect(() => {
    loadWatchlist();
  }, [loadWatchlist]);

  const loadQuote = useCallback(async (item: WatchlistItem) => {
    const seq = ++quoteSeq.current;
    setQuoteLoading(true);
    setQuoteError('');
    const r = await getQuote(item.symbol, item.market || 'A股');
    if (seq !== quoteSeq.current) return;
    setQuoteLoading(false);
    if (r.ok && r.data) setQuote(r.data);
    else setQuoteError('行情获取失败：' + parseApiError(r.error, '后端或数据源不可用'));
  }, []);

  const loadKline = useCallback(async (item: WatchlistItem, p: Period) => {
    const seq = ++klineSeq.current;
    setKlineLoading(true);
    setKlineError('');
    const r = await getKline(item.symbol, item.market || 'A股', PERIODS[p].days);
    if (seq !== klineSeq.current) return;
    setKlineLoading(false);
    if (r.ok && r.data && Array.isArray(r.data.bars)) setKlineBars(r.data.bars);
    else setKlineError('K线获取失败：' + parseApiError(r.error, '后端或数据源不可用'));
  }, []);

  const loadNews = useCallback(async (item: WatchlistItem) => {
    const seq = ++newsSeq.current;
    setNewsLoading(true);
    setNewsError('');
    const r = await getRelatedNews(item.name || item.symbol);
    if (seq !== newsSeq.current) return;
    setNewsLoading(false);
    if (r.ok) setNews(toList<RelatedNewsItem>(r.data));
    else setNewsError('关联资讯获取失败：' + parseApiError(r.error, '后端或数据源不可用'));
  }, []);

  // 选中变化：清空并加载行情 / 资讯；K 线由下方 [selected, period] 效应负责
  useEffect(() => {
    if (!selected) {
      setQuote(null);
      setQuoteError('');
      setKlineBars([]);
      setKlineError('');
      setNews([]);
      setNewsError('');
      return;
    }
    setQuote(null);
    setQuoteError('');
    setKlineBars([]);
    setKlineError('');
    setNews([]);
    setNewsError('');
    loadQuote(selected);
    loadNews(selected);
  }, [selected, loadQuote, loadNews]);

  useEffect(() => {
    if (selected) loadKline(selected, period);
  }, [selected, period, loadKline]);

  // 行情轻量轮询（30 秒；后台标签页暂停）
  useEffect(() => {
    if (!selected) return;
    const t = window.setInterval(() => {
      if (!document.hidden) loadQuote(selected);
    }, 30000);
    return () => window.clearInterval(t);
  }, [selected, loadQuote]);

  const displayBars = useMemo(() => {
    if (period === 'day') return klineBars;
    return aggregateBars(klineBars, period === 'week' ? 'week' : 'month');
  }, [klineBars, period]);

  const handleAdd = async () => {
    const symbol = form.symbol.trim();
    if (!symbol) return;
    setSubmitting(true);
    setMsg(null);
    const r = await addWatchlistItem({ symbol, market: form.market, group_name: form.group.trim() || '默认' });
    setSubmitting(false);
    if (!r.ok) {
      setMsg({ type: 'err', text: '添加失败：' + parseApiError(r.error) });
      return;
    }
    setForm((f) => ({ ...f, symbol: '' }));
    setMsg({ type: 'ok', text: '已添加 ' + symbol });
    await loadWatchlist();
    const created = r.data as WatchlistItem | undefined;
    if (created && typeof created.id === 'number') setSelectedId(created.id);
    window.setTimeout(() => setMsg(null), 3000);
  };

  const handleDelete = async (item: WatchlistItem) => {
    if (!window.confirm('确定从自选股中删除 ' + (item.name || item.symbol) + ' ？')) return;
    const r = await deleteWatchlistItem(item.id);
    if (r.ok) {
      await loadWatchlist();
      setMsg({ type: 'ok', text: '已删除 ' + (item.name || item.symbol) });
    } else {
      setMsg({ type: 'err', text: '删除失败：' + parseApiError(r.error) });
    }
    window.setTimeout(() => setMsg(null), 2500);
  };

  const handleMoveGroup = async (item: WatchlistItem, group: string) => {
    const r = await updateWatchlistGroup(item.id, group);
    if (r.ok) {
      await loadWatchlist();
      setMsg({ type: 'ok', text: '已移至「' + group + '」' });
    } else {
      setMsg({ type: 'err', text: '改分组失败：' + parseApiError(r.error) });
    }
    window.setTimeout(() => setMsg(null), 2500);
  };

  const inputCls = 'h-10 rounded border border-border px-3 text-sm bg-white focus:outline-none focus:border-primary-500';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-primary-900">自选股看板</h1>
          <p className="text-xs text-text-muted mt-1">自定义分组 · 实时行情 · K线技术指标 · 基本面速览 · 关联资讯</p>
        </div>
      </div>

      {/* 添加自选股 */}
      <Card>
        <h2 className="font-bold text-sm mb-3">添加自选股</h2>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={form.symbol}
            onChange={(e) => setForm((f) => ({ ...f, symbol: e.target.value }))}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
            placeholder="股票代码，如 600519 / 00700"
            className={inputCls + ' w-44'}
          />
          <select
            value={form.market}
            onChange={(e) => setForm((f) => ({ ...f, market: e.target.value }))}
            className={inputCls}
          >
            <option value="A股">A股</option>
            <option value="港股">港股</option>
          </select>
          <input
            value={form.group}
            onChange={(e) => setForm((f) => ({ ...f, group: e.target.value }))}
            placeholder="分组名（默认）"
            list="wl-groups"
            className={inputCls + ' w-36'}
          />
          <datalist id="wl-groups">
            {groupNames.map((g) => <option key={g} value={g} />)}
          </datalist>
          <Button onClick={handleAdd} disabled={submitting || !form.symbol.trim()}>
            {submitting ? '添加中...' : '添加'}
          </Button>
        </div>
        {msg && (
          <p className={`text-sm mt-2 ${msg.type === 'ok' ? 'text-success' : 'text-danger'}`}>{msg.text}</p>
        )}
      </Card>

      {/* 分组 + 列表 */}
      <Card>
        <div className="flex flex-wrap items-center gap-1.5 mb-3">
          <h2 className="font-bold text-sm mr-1">我的自选</h2>
          {tabs.map((t) => (
            <button
              key={t.name}
              onClick={() => setActiveGroup(t.name)}
              className={`h-8 px-3 rounded text-xs font-medium transition-colors ${
                activeGroup === t.name ? 'bg-primary-500 text-white' : 'bg-primary-50 text-primary-700 hover:bg-primary-100'
              }`}
            >
              {t.name}<span className={`ml-1 ${activeGroup === t.name ? 'opacity-80' : 'text-text-muted'}`}>{t.count}</span>
            </button>
          ))}
        </div>
        {loadingList ? (
          <Loading />
        ) : groupItems.length === 0 ? (
          <EmptyState icon="⭐" title="暂无自选股" description="先在上方添加一只（如 600519 贵州茅台），即可查看实时行情、K 线与关联资讯。" />
        ) : (
          <div className="divide-y divide-border">
            {groupItems.map((item) => (
              <div
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                className={`flex items-center gap-3 py-2 px-2 -mx-2 rounded cursor-pointer transition-colors ${
                  selectedId === item.id ? 'bg-primary-50' : 'hover:bg-primary-50/50'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{item.name || item.symbol}</span>
                    <span className="text-xs text-text-muted font-number">{item.symbol}</span>
                    <Badge variant={item.market === '港股' ? 'info' : 'default'}>{item.market || 'A股'}</Badge>
                  </div>
                </div>
                <select
                  value={item.group_name || '默认'}
                  onChange={(e) => handleMoveGroup(item, e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  className="h-8 rounded border border-border text-xs bg-white px-1 focus:outline-none focus:border-primary-500"
                  title="改分组"
                >
                  {groupNames.map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
                <Button variant="danger" size="sm" onClick={(e) => { e.stopPropagation(); handleDelete(item); }}>
                  删除
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* 选中股票详情 */}
      {selected && (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-3 mb-3">
              <h2 className="font-bold text-sm">{selected.name || selected.symbol}</h2>
              <span className="text-xs text-text-muted font-number">{selected.symbol}</span>
              <Badge variant={selected.market === '港股' ? 'info' : 'default'}>{selected.market || 'A股'}</Badge>
              {quote && (
                <span className="text-xs text-text-muted">
                  更新于 {quote.timestamp}{quote.source ? ' · ' + quote.source : ''}
                </span>
              )}
              <div className="ml-auto flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => loadQuote(selected)} disabled={quoteLoading}>
                  {quoteLoading ? '刷新中...' : '刷新行情'}
                </Button>
                <Button size="sm" disabled title="S11 模块实现，敬请期待">一键加入追踪</Button>
              </div>
            </div>
            {quoteError && <p className="text-sm text-danger mb-2">{quoteError}</p>}
            {quote ? (
              <>
                <div className="flex items-end gap-3 mb-3">
                  <span className="text-3xl font-number leading-none">{fmtNum(quote.price)}</span>
                  <span className={`text-sm font-number mb-0.5 ${upDownCls(quote.change_pct)}`}>
                    {quote.change != null && quote.change !== 0 ? (quote.change > 0 ? '+' : '') + quote.change.toFixed(2) : ''}
                    {quote.change_pct != null && quote.change_pct !== 0 ? ' ' + (quote.change_pct > 0 ? '+' : '') + quote.change_pct.toFixed(2) + '%' : ''}
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
                  <Stat label="今开" value={fmtNum(quote.open)} />
                  <Stat label="最高" value={fmtNum(quote.high)} cls={upDownCls(quote.high != null && quote.prev_close != null ? quote.high - quote.prev_close : null)} />
                  <Stat label="最低" value={fmtNum(quote.low)} cls={upDownCls(quote.low != null && quote.prev_close != null ? quote.low - quote.prev_close : null)} />
                  <Stat label="昨收" value={fmtNum(quote.prev_close)} />
                  <Stat label="成交量" value={fmtVolume(quote.volume)} />
                  <Stat label="成交额" value={fmtBig(quote.amount)} />
                  <Stat label="换手率" value={quote.turnover != null ? fmtNum(quote.turnover) + '%' : '—'} />
                  <Stat label="PE(TTM)" value={quote.pe != null ? fmtNum(quote.pe) : '—'} />
                  <Stat label="总市值" value={fmtBig(quote.total_market_cap)} />
                  <Stat label="流通市值" value={fmtBig(quote.float_market_cap)} />
                </div>
              </>
            ) : quoteLoading ? (
              <Loading className="py-4" text="行情加载中..." />
            ) : null}
          </Card>

          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <h2 className="font-bold text-sm">
                K 线走势
                <span className="text-xs text-text-muted font-normal ml-2">
                  {period === 'day' ? '日K · 120 根' : period === 'week' ? '日K按周聚合' : '日K按月聚合'}
                </span>
              </h2>
              <div className="flex gap-1">
                {(Object.keys(PERIODS) as Period[]).map((p) => (
                  <button
                    key={p}
                    onClick={() => setPeriod(p)}
                    className={`h-7 px-3 rounded text-xs font-medium transition-colors ${
                      period === p ? 'bg-primary-500 text-white' : 'bg-primary-50 text-primary-700 hover:bg-primary-100'
                    }`}
                  >
                    {PERIODS[p].label}
                  </button>
                ))}
              </div>
            </div>
            {klineError && <p className="text-sm text-danger mb-2">{klineError}</p>}
            {displayBars.length > 0 ? (
              <KLineChart bars={displayBars} height={430} />
            ) : klineLoading ? (
              <Loading className="py-4" text="K线加载中..." />
            ) : (
              <EmptyState icon="📉" title="暂无K线数据" description="后端或数据源暂未返回 K 线，可稍后刷新重试。" className="py-6" />
            )}
          </Card>

          <Card>
            <div className="flex items-center gap-2 mb-3">
              <h2 className="font-bold text-sm">关联资讯</h2>
              <span className="text-xs text-text-muted">关键词：{selected.name || selected.symbol}</span>
            </div>
            {newsError && <p className="text-sm text-danger mb-2">{newsError}</p>}
            {news.length > 0 ? (
              <div className="divide-y divide-border">
                {news.map((n) => (
                  <div key={n.id} className="py-2.5">
                    <div className="flex items-center gap-2">
                      <Badge variant={LEVEL_BADGE[n.level] || 'default'}>{n.level || '一般'}</Badge>
                      <span className="text-xs text-text-muted">{n.source || n.market || ''}</span>
                      <span className="text-xs text-text-muted ml-auto">{n.published_at || ''}</span>
                    </div>
                    {n.url ? (
                      <a href={n.url} target="_blank" rel="noreferrer" className="block text-sm font-medium text-text mt-1 hover:text-primary-700">
                        {n.title}
                      </a>
                    ) : (
                      <p className="text-sm font-medium text-text mt-1">{n.title}</p>
                    )}
                    {n.summary && <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{n.summary}</p>}
                  </div>
                ))}
              </div>
            ) : newsLoading ? (
              <Loading className="py-4" text="资讯加载中..." />
            ) : (
              <EmptyState
                icon="📰"
                title="暂无关联资讯"
                description={'暂未找到与「' + (selected.name || selected.symbol) + '」相关的资讯。'}
                className="py-6"
              />
            )}
          </Card>
        </>
      )}
    </div>
  );
}