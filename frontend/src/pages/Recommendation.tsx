// S10 推荐中心：生成今日推荐 / 短线·长线卡片 / 约束拦截 / 回测报告 / 历史推荐
// 契约：/api/recommend/{today,run,history,backtest,backtest/evaluate}（后端实测通过版）
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import {
  evaluateRecommendations,
  generateRecommendations,
  getRecommendationsHistory,
  getRecommendationsPerformance,
  getTodayRecommendations,
} from '../services/api';
import type { BacktestRecentItem, HistoryItem, RecommendItem, TodayRecommendations } from '../services/api';

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

const REC_TYPE_LABEL: Record<string, string> = { 短线: '短线', 长线: '长线', short: '短线', long: '长线' };

function isShort(r: RecommendItem): boolean {
  return r.rec_type === '短线' || r.rec_type === 'short';
}

/** 风险等级 → 徽章配色：低=success / 中=info / 高=danger */
function riskVariant(risk: string | null | undefined): 'success' | 'info' | 'danger' | 'default' {
  const r = (risk || '').trim();
  if (r.includes('低') || r === 'low') return 'success';
  if (r.includes('中') || r === 'medium' || r === 'mid') return 'info';
  if (r.includes('高') || r === 'high') return 'danger';
  return 'default';
}

/** 涨跌配色（A 股惯例：红涨绿跌） */
function upDownCls(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return 'text-text';
  return v > 0 ? 'text-danger' : 'text-success';
}

/** 价格显示：A 股 2 位、港股 3 位 */
function fmtPrice(v: number | null | undefined, market?: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toFixed(market === '港股' ? 3 : 2);
}

/** 比率归一化为百分数：0.667 → 66.7；66.7 → 66.7 */
function toPercent(v: number | null | undefined): number | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return Math.abs(v) <= 1 ? v * 100 : v;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  const p = toPercent(v);
  return p === null ? '—' : (p > 0 ? '+' : '') + p.toFixed(digits) + '%';
}

/** 结果状态 → 徽章 */
const OUTCOME_BADGE: Record<string, 'success' | 'danger' | 'warning' | 'default'> = {
  win: 'success',
  loss: 'danger',
  stop: 'warning',
  flat: 'default',
};
const OUTCOME_LABEL: Record<string, string> = { win: '胜', loss: '亏', stop: '止损', flat: '平' };

function outcomeOf(o: string | null | undefined): string {
  if (!o || o === 'null') return '待结算';
  return OUTCOME_LABEL[o] || o;
}

function ConfBar({ value }: { value: number | null | undefined }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const color = v >= 70 ? 'bg-success' : v >= 40 ? 'bg-warning' : 'bg-danger';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-bg-secondary overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${v}%` }} />
      </div>
      <span className="text-xs font-number text-text-secondary w-10 text-right tabular-nums">{v.toFixed(0)}%</span>
    </div>
  );
}

function Stat({ label, value, cls = '' }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-bg-secondary rounded px-3 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className={`text-sm font-number mt-0.5 ${cls}`}>{value}</div>
    </div>
  );
}

/** 推荐卡片：短线展示入场区间/止损/目标，长线展示估值区间 */
function RecCard({ rec }: { rec: RecommendItem }) {
  const short = isShort(rec);
  return (
    <div className="border border-border rounded-lg p-4 flex flex-col gap-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-sm">{rec.name || rec.symbol}</span>
        <span className="text-xs text-text-muted font-number">{rec.symbol}</span>
        <Badge variant={rec.market === '港股' ? 'info' : 'default'}>{rec.market || 'A股'}</Badge>
        <Badge variant={short ? 'warning' : 'default'}>{REC_TYPE_LABEL[rec.rec_type] || rec.rec_type}</Badge>
      </div>
      <ConfBar value={rec.confidence} />
      {short ? (
        <div className="grid grid-cols-2 gap-2">
          <Stat label="入场区间" value={`${fmtPrice(rec.entry_min, rec.market)} ~ ${fmtPrice(rec.entry_max, rec.market)}`} />
          <Stat label="止损" value={fmtPrice(rec.stop_loss, rec.market)} cls="text-danger" />
          <Stat label="目标价" value={fmtPrice(rec.target, rec.market)} cls="text-success" />
          <div className="bg-bg-secondary rounded px-3 py-2">
            <div className="text-xs text-text-secondary">风险等级</div>
            <div className="mt-1">
              <Badge variant={riskVariant(rec.risk_level)}>{rec.risk_level || '—'}</Badge>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <Stat label="估值区间" value={`${fmtPrice(rec.valuation_min, rec.market)} ~ ${fmtPrice(rec.valuation_max, rec.market)}`} />
          <Stat label="当前价" value={fmtPrice(rec.rec_price, rec.market)} />
          <div className="bg-bg-secondary rounded px-3 py-2">
            <div className="text-xs text-text-secondary">风险等级</div>
            <div className="mt-1">
              <Badge variant={riskVariant(rec.risk_level)}>{rec.risk_level || '—'}</Badge>
            </div>
          </div>
          <Stat label="类型" value="长线" />
        </div>
      )}
      {rec.logic && <p className="text-xs text-text-secondary leading-relaxed line-clamp-3">{rec.logic}</p>}
    </div>
  );
}

export default function Recommendation() {
  const [today, setToday] = useState<TodayRecommendations | null>(null);
  const [todayLoading, setTodayLoading] = useState(false);
  const [todayError, setTodayError] = useState('');

  const [backtest, setBacktest] = useState<Record<string, unknown> | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState('');

  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

  const [generating, setGenerating] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const todaySeq = useRef(0);

  const loadToday = useCallback(async () => {
    const seq = ++todaySeq.current;
    setTodayLoading(true);
    setTodayError('');
    const r = await getTodayRecommendations();
    if (seq !== todaySeq.current) return;
    setTodayLoading(false);
    if (r.ok && r.data) {
      const d = r.data as TodayRecommendations;
      setToday(Array.isArray(d.items) ? d : null);
    } else {
      setTodayError('今日推荐获取失败：' + (r.error || '后端不可用'));
    }
  }, []);

  const loadBacktest = useCallback(async () => {
    setBacktestLoading(true);
    setBacktestError('');
    const r = await getRecommendationsPerformance();
    setBacktestLoading(false);
    if (r.ok && r.data) setBacktest(r.data as Record<string, unknown>);
    else setBacktestError('回测统计获取失败：' + (r.error || '后端不可用'));
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError('');
    const r = await getRecommendationsHistory(50);
    setHistoryLoading(false);
    if (r.ok) setHistory(toList<HistoryItem>(r.data));
    else setHistoryError('历史推荐获取失败：' + (r.error || '后端不可用'));
  }, []);

  useEffect(() => {
    loadToday();
    loadBacktest();
    loadHistory();
  }, [loadToday, loadBacktest, loadHistory]);

  const items = useMemo<RecommendItem[]>(() => toList<RecommendItem>(today?.items), [today]);
  const blocked = useMemo(
    () => (Array.isArray(today?.blocked) ? (today.blocked as { symbol: string; name?: string; rec_type?: string; reasons: string[] }[]) : []),
    [today],
  );
  const todayErrors = useMemo(() => (Array.isArray(today?.errors) ? (today.errors as string[]) : []), [today]);

  const shortRecs = useMemo(() => items.filter(isShort), [items]);
  const longRecs = useMemo(() => items.filter((r) => !isShort(r)), [items]);

  const btSummary = useMemo(() => (backtest?.summary ?? {}) as Record<string, unknown>, [backtest]);
  const btByType = useMemo(() => (backtest?.by_type ?? {}) as Record<string, Record<string, unknown>>, [backtest]);
  const btMonths = useMemo(() => toList<Record<string, unknown>>(backtest?.by_month), [backtest]);
  const btRecent = useMemo(() => toList<BacktestRecentItem>(backtest?.recent), [backtest]);

  const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);

  const handleGenerate = async () => {
    setGenerating(true);
    setMsg(null);
    const r = await generateRecommendations();
    setGenerating(false);
    if (!r.ok) {
      setMsg({ type: 'err', text: '生成失败：' + (r.error || '后端不可用') });
      return;
    }
    const d = r.data as TodayRecommendations | undefined;
    if (d && Array.isArray(d.items)) {
      const list = d.items;
      const sc = list.filter(isShort).length;
      const lc = list.length - sc;
      setMsg({
        type: 'ok',
        text: (d.cached ? '已是最新（缓存）' : '已生成') + '：短线 ' + sc + ' 条 · 长线 ' + lc + ' 条'
          + (d.source === 'rules' ? '（规则降级）' : ''),
      });
    } else {
      setMsg({ type: 'ok', text: '生成完成' });
    }
    await Promise.all([loadToday(), loadBacktest(), loadHistory()]);
    window.setTimeout(() => setMsg(null), 5000);
  };

  const handleEvaluate = async () => {
    setEvaluating(true);
    setMsg(null);
    const r = await evaluateRecommendations();
    setEvaluating(false);
    if (!r.ok) {
      setMsg({ type: 'err', text: '结算失败：' + (r.error || '后端不可用') });
      return;
    }
    const d = r.data as { evaluated?: number } | undefined;
    setMsg({ type: 'ok', text: '已结算 ' + (typeof d?.evaluated === 'number' ? d.evaluated : 0) + ' 条推荐' });
    await loadBacktest();
    window.setTimeout(() => setMsg(null), 4000);
  };

  const todayDate = today?.date || (items.length > 0 ? (items[0].rec_date || '').slice(0, 10) : '');

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">推荐中心</h1>
          <p className="text-xs text-text-muted mt-1">AI 每日生成短线与长线推荐 · 约束规则过滤 · 回测统计</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={loadToday} disabled={todayLoading}>
            {todayLoading ? '刷新中...' : '刷新'}
          </Button>
          <Button onClick={handleGenerate} disabled={generating}>
            {generating ? '生成中...' : '生成今日推荐'}
          </Button>
        </div>
      </div>
      {msg && <p className={`text-sm ${msg.type === 'ok' ? 'text-success' : 'text-danger'}`}>{msg.text}</p>}

      {/* 今日推荐 */}
      <Card>
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <h2 className="font-bold text-sm">今日推荐</h2>
          {todayDate && <span className="text-xs text-text-muted">{todayDate}</span>}
          {today?.source && (
            <Badge variant={today.source === 'ai' ? 'info' : 'warning'}>
              {today.source === 'ai' ? 'AI 生成' : '规则降级'}
            </Badge>
          )}
          {today?.cached === true && <span className="text-xs text-text-muted">（缓存）</span>}
          <span className="text-xs text-text-muted">短线 {shortRecs.length} · 长线 {longRecs.length}</span>
        </div>
        {todayError && <p className="text-sm text-danger mb-2">{todayError}</p>}
        {todayErrors.length > 0 && (
          <div className="text-xs text-warning mb-2 space-y-0.5">
            {todayErrors.map((e, i) => <p key={i}>⚠ {e}</p>)}
          </div>
        )}
        {todayLoading && items.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-text-muted">今日暂无推荐，点击右上角「生成今日推荐」开始（每日 09:15 自动生成）。</p>
        ) : (
          <div className="space-y-4">
            {shortRecs.length > 0 && (
              <div>
                <h3 className="text-sm font-bold text-primary-700 mb-2">短线推荐</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {shortRecs.map((rec) => <RecCard key={rec.id} rec={rec} />)}
                </div>
              </div>
            )}
            {longRecs.length > 0 && (
              <div>
                <h3 className="text-sm font-bold text-primary-700 mb-2">长线推荐</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {longRecs.map((rec) => <RecCard key={rec.id} rec={rec} />)}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 约束拦截 */}
        {blocked.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-bold text-text-secondary mb-2">约束拦截（{blocked.length}）</h3>
            <div className="divide-y divide-border rounded border border-border">
              {blocked.map((b, i) => (
                <div key={b.symbol + '-' + (b.rec_type || '') + '-' + i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 bg-bg-secondary/60">
                  <span className="text-sm text-text-muted">{b.name || b.symbol}</span>
                  <span className="text-xs text-text-muted font-number">{b.symbol}</span>
                  {b.rec_type && <Badge variant="default">{REC_TYPE_LABEL[b.rec_type] || b.rec_type}</Badge>}
                  <span className="text-xs text-text-muted ml-auto">
                    {Array.isArray(b.reasons) ? b.reasons.join('；') : '约束不满足'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* 回测报告 */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">
            回测报告
            <span className="text-xs text-text-muted font-normal ml-2">胜率 = 现价优于基准的占比（短线以入场区间中值/长线以估值中值计）</span>
          </h2>
          <div className="ml-auto">
            <Button variant="secondary" size="sm" onClick={handleEvaluate} disabled={evaluating}>
              {evaluating ? '结算中...' : '结算未评估'}
            </Button>
          </div>
        </div>
        {backtestError && <p className="text-sm text-danger mb-2">{backtestError}</p>}
        {backtestLoading && !backtest ? (
          <p className="text-sm text-text-muted">统计中...</p>
        ) : !backtest ? (
          <p className="text-sm text-text-muted">暂无回测数据，生成推荐后自动统计。</p>
        ) : (
          <>
            <div className="grid grid-cols-3 lg:grid-cols-6 gap-2 mb-3">
              <div className="bg-bg-secondary rounded px-3 py-3 text-center">
                <div className="text-xs text-text-secondary">推荐总数</div>
                <div className="text-xl font-number text-primary-900 mt-1">{num(btSummary.count) ?? 0}</div>
              </div>
              <div className="bg-bg-secondary rounded px-3 py-3 text-center">
                <div className="text-xs text-text-secondary">胜率</div>
                <div className={`text-xl font-number mt-1 ${upDownCls(num(btSummary.win_rate))}`}>{fmtPct(num(btSummary.win_rate))}</div>
              </div>
              <div className="bg-bg-secondary rounded px-3 py-3 text-center">
                <div className="text-xs text-text-secondary">平均收益</div>
                <div className={`text-xl font-number mt-1 ${upDownCls(num(btSummary.avg_return))}`}>{fmtPct(num(btSummary.avg_return))}</div>
              </div>
              <div className="bg-bg-secondary rounded px-3 py-3 text-center">
                <div className="text-xs text-text-secondary">累计收益</div>
                <div className={`text-xl font-number mt-1 ${upDownCls(num(btSummary.total_return))}`}>{fmtPct(num(btSummary.total_return))}</div>
              </div>
              <div className="bg-bg-secondary rounded px-3 py-3 text-center">
                <div className="text-xs text-text-secondary">胜 / 亏</div>
                <div className="text-xl font-number mt-1">
                  <span className="text-success">{num(btSummary.wins) ?? 0}</span>
                  <span className="text-text-muted"> / </span>
                  <span className="text-danger">{num(btSummary.losses) ?? 0}</span>
                </div>
              </div>
              <div className="bg-bg-secondary rounded px-3 py-3 text-center">
                <div className="text-xs text-text-secondary">止损 / 平</div>
                <div className="text-xl font-number mt-1 text-text">{num(btSummary.stops) ?? 0} / {num(btSummary.flats) ?? 0}</div>
              </div>
            </div>

            {(btByType['短线'] || btByType['长线']) && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
                {['短线', '长线'].map((t) => {
                  const g = btByType[t];
                  if (!g) return null;
                  return (
                    <div key={t} className="bg-bg-secondary rounded px-3 py-2">
                      <div className="text-xs text-text-secondary mb-1">{t}（{num(g.count) ?? 0} 条）</div>
                      <div className="text-sm font-number">
                        胜率 <span className="text-primary-700">{fmtPct(num(g.win_rate))}</span>
                        <span className="mx-1.5 text-text-muted">/</span>
                        均收 <span className={upDownCls(num(g.avg_return))}>{fmtPct(num(g.avg_return))}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {btMonths.length > 0 && (
              <div className="mb-3">
                <div className="text-xs text-text-secondary mb-1">月度表现（近 6 个月）</div>
                <div className="divide-y divide-border border border-border rounded">
                  {btMonths.map((m, i) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-1.5 text-sm">
                      <span className="font-number text-text-secondary w-14">{String(m.month ?? '').slice(0, 7)}</span>
                      <span className="text-text-muted text-xs">{num(m.count) ?? 0} 条</span>
                      <span className="ml-auto font-number">
                        胜率 <span className="text-primary-700">{fmtPct(num(m.win_rate))}</span>
                        <span className="mx-1.5 text-text-muted">/</span>
                        均收 <span className={upDownCls(num(m.avg_return))}>{fmtPct(num(m.avg_return))}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {btRecent.length > 0 && (
              <div>
                <div className="text-xs text-text-secondary mb-1">最近明细</div>
                <div className="divide-y divide-border border border-border rounded">
                  {btRecent.map((r2, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                      <span className="text-xs text-text-muted font-number">{(r2.rec_date || '').slice(0, 10)}</span>
                      <Badge variant={r2.rec_type === '短线' || r2.rec_type === 'short' ? 'warning' : 'default'}>
                        {REC_TYPE_LABEL[r2.rec_type || ''] || r2.rec_type || '—'}
                      </Badge>
                      <span className="font-medium">{r2.name || r2.symbol}</span>
                      <span className="text-xs text-text-muted font-number">{r2.symbol}</span>
                      <Badge variant={OUTCOME_BADGE[r2.outcome || ''] || 'default'}>{outcomeOf(r2.outcome)}</Badge>
                      <span className="ml-auto font-number">
                        <span className={`${upDownCls(r2.result_pct ?? null)}`}>{fmtPct(r2.result_pct)}</span>
                        {r2.eval_days != null && <span className="text-xs text-text-muted ml-1.5">{r2.eval_days} 日</span>}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </Card>

      {/* 历史推荐 */}
      <Card>
        <h2 className="font-bold text-sm mb-3">
          历史推荐
          <span className="text-xs text-text-muted font-normal ml-2">最近 50 条</span>
        </h2>
        {historyError && <p className="text-sm text-danger mb-2">{historyError}</p>}
        {historyLoading && history.length === 0 ? (
          <p className="text-sm text-text-muted">加载中...</p>
        ) : history.length === 0 ? (
          <p className="text-sm text-text-muted">暂无历史推荐。</p>
        ) : (
          <div className="divide-y divide-border">
            {history.map((h) => (
              <div key={h.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
                <span className="text-xs text-text-muted font-number w-20">{(h.rec_date || '').slice(0, 10)}</span>
                <Badge variant={isShort(h) ? 'warning' : 'default'}>{REC_TYPE_LABEL[h.rec_type] || h.rec_type}</Badge>
                <span className="text-sm font-medium">{h.name || h.symbol}</span>
                <span className="text-xs text-text-muted font-number">{h.symbol}</span>
                <Badge variant={h.market === '港股' ? 'info' : 'default'}>{h.market || 'A股'}</Badge>
                <Badge variant={OUTCOME_BADGE[h.outcome || ''] || 'default'}>{outcomeOf(h.outcome)}</Badge>
                <span className="text-xs text-text-secondary ml-auto">
                  置信度 <span className="font-number">{h.confidence != null ? h.confidence + '%' : '—'}</span>
                  <span className="mx-2 text-text-muted">|</span>
                  结果{' '}
                  <span className={`font-number ${upDownCls(h.result_pct ?? null)}`}>{fmtPct(h.result_pct)}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
