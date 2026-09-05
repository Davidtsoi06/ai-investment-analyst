// S10 推荐中心：生成今日推荐 / 短线·长线卡片 / 约束拦截 / 回测报告 / 历史推荐
// 契约：/api/recommend/{today,run,history,backtest,backtest/evaluate}（后端实测通过版）
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import Stat from '../components/ui/Stat';
import { fmtPct, fmtPrice, num, toList, upDownCls } from '../lib/format';
import {
  evaluateRecommendations,
  generateRecommendations,
  getAiStatus,
  getRecommendationsHistory,
  getRecommendationsPerformance,
  getTodayRecommendations,
  parseApiError,
} from '../services/api';
import { Link } from 'react-router-dom';
import type { BacktestRecentItem, HistoryItem, RecommendItem, TodayRecommendations } from '../services/api';

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

  // V1.0.9：按意愿生成（弹出意图输入框）
  const [intentOpen, setIntentOpen] = useState(false);
  const [intentText, setIntentText] = useState('');

  // AI 最近错误（V1.0.7：规则降级原因可见化，不再"莫名降级"）
  const [aiErr, setAiErr] = useState<{ last_error?: string; last_error_at?: string; configured?: boolean } | null>(null);

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
      setTodayError('今日推荐获取失败：' + parseApiError(r.error));
    }
  }, []);

  const loadBacktest = useCallback(async () => {
    setBacktestLoading(true);
    setBacktestError('');
    const r = await getRecommendationsPerformance();
    setBacktestLoading(false);
    if (r.ok && r.data) setBacktest(r.data as Record<string, unknown>);
    else setBacktestError('回测统计获取失败：' + parseApiError(r.error));
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError('');
    const r = await getRecommendationsHistory(50);
    setHistoryLoading(false);
    if (r.ok) setHistory(toList<HistoryItem>(r.data));
    else setHistoryError('历史推荐获取失败：' + parseApiError(r.error));
  }, []);

  useEffect(() => {
    loadToday();
    loadBacktest();
    loadHistory();
    getAiStatus().then((r) => {
      if (r.ok && r.data) setAiErr(r.data as { last_error?: string; last_error_at?: string; configured?: boolean });
    }).catch(() => {});
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

  const openIntent = () => {
    setIntentText('');
    setIntentOpen(true);
  };

  const closeIntent = () => setIntentOpen(false);

  const handleGenerate = async (intent = '') => {
    setIntentOpen(false);
    setGenerating(true);
    setMsg(null);
    const r = await generateRecommendations(intent);
    setGenerating(false);
    if (!r.ok) {
      setMsg({ type: 'err', text: '生成失败：' + parseApiError(r.error) });
      return;
    }
    const d = r.data as TodayRecommendations | undefined;
    if (d && Array.isArray(d.items)) {
      const list = d.items;
      const sc = list.filter(isShort).length;
      const lc = list.length - sc;
      const scope = intent.trim() ? '（范围：' + intent.trim() + '）' : '';
      setMsg({
        type: 'ok',
        text: (d.cached ? '已是最新（缓存）' : '已生成') + scope + '：短线 ' + sc + ' 条 · 长线 ' + lc + ' 条'
          + (d.source === 'rules' ? '（规则引擎）' : d.source === 'ai_empty' ? '（AI 暂无合适标的）' : ''),
      });
    } else {
      setMsg({ type: 'ok', text: '生成完成' });
    }
    await Promise.all([loadToday(), loadBacktest(), loadHistory()]);
    window.setTimeout(() => setMsg(null), 6000);
  };

  const handleEvaluate = async () => {
    setEvaluating(true);
    setMsg(null);
    const r = await evaluateRecommendations();
    setEvaluating(false);
    if (!r.ok) {
      setMsg({ type: 'err', text: '结算失败：' + parseApiError(r.error) });
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
          <Button onClick={openIntent} disabled={generating}>
            {generating
              ? '正在分析候选股票（约 10~30 秒）...'
              : today?.cached === true
                ? '重新生成（可按意愿）'
                : '生成今日推荐'}
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
            <span title={
              today.source === 'ai' ? '由 DeepSeek 大模型综合研判生成'
                : today.source === 'ai_empty' ? 'AI 已正常分析，但当前这些候选均未达到推荐标准'
                  : '未配置 AI Key 或 AI 调用失败时，由内置规则引擎按技术形态与估值评分生成'
            }>
              <Badge variant={today.source === 'ai' ? 'info' : today.source === 'ai_empty' ? 'default' : 'warning'}>
                {today.source === 'ai' ? 'AI 生成'
                  : today.source === 'ai_empty' ? 'AI 已分析（暂无合适标的）'
                    : '规则引擎'}
              </Badge>
            </span>
          )}
          {today?.intent && (
            <span className="text-xs text-primary-700 bg-primary-50 border border-primary-100 rounded-full px-2 py-0.5" title="本次推荐的分析范围">
              📌 范围：{today.intent}
            </span>
          )}
          {today?.cached === true && (
            <span className="text-xs text-text-muted" title="今日推荐已生成并存入本地，展示的是缓存结果；如需强制重新分析请点右上角「重新生成」">（缓存）</span>
          )}
          <span className="text-xs text-text-muted">短线 {shortRecs.length} · 长线 {longRecs.length}</span>
        </div>
        {today?.source === 'rules' && aiErr && (aiErr.last_error || aiErr.configured === false) && (
          <div className="mb-2 rounded border border-warning/40 bg-warning/5 px-3 py-2">
            <p className="text-xs text-warning">
              ⚠ {aiErr.last_error
                ? 'AI 调用失败（' + (aiErr.last_error_at || '') + '）：' + aiErr.last_error
                : '未检测到已配置的 AI Key'}
            </p>
            <p className="text-xs text-text-muted mt-0.5">
              当前以「规则引擎」模式生成。请到 <Link to="/settings" className="text-primary-600 underline">系统设置 → DeepSeek AI 配置</Link> 检查 Key 并点「保存并测试」。
            </p>
          </div>
        )}
        {todayError && <p className="text-sm text-danger mb-2">{todayError}</p>}
        {todayErrors.length > 0 && (
          <div className="text-xs text-warning mb-2 space-y-0.5">
            {todayErrors.map((e, i) => <p key={i}>⚠ {e}</p>)}
          </div>
        )}
        {todayLoading && items.length === 0 ? (
          <Loading />
        ) : items.length === 0 ? (
          today ? (
            <div className="rounded-lg border border-border bg-bg-secondary/40 px-4 py-4">
              <div className="flex flex-wrap items-center gap-2 mb-1.5">
                <span className="text-sm font-bold text-primary-900">今日暂无推荐</span>
                {today.cached === true && <Badge variant="info">已生成（缓存）</Badge>}
                {typeof today.pool_size === 'number' && today.pool_size > 0 && (
                  <span className="text-xs text-text-muted">候选池 {today.pool_size} 只</span>
                )}
              </div>
              <p className="text-xs text-text-secondary leading-5">
                {today.empty_reason
                  ? today.empty_reason
                  : today.cached === true
                    ? '今日推荐已生成过（缓存结果为空），如行情变化可点「重新生成」强制重算。'
                    : '候选股票均已分析，但当前没有满足条件的推荐。'}
              </p>
              {typeof today.candidate_count === 'number' && today.candidate_count > 0 && (
                <p className="text-xs text-text-muted mt-1">本次实际分析 {today.candidate_count} 只候选股票。</p>
              )}
              {today.source === 'rules' && (
                <p className="text-xs text-text-muted mt-1">
                  当前由内置「规则引擎」筛选（AI 不可用降级）。可点下方按钮按意愿重新生成，或到设置检查 AI 配置。
                </p>
              )}
              <div className="mt-3 flex items-center gap-2">
                <Button size="sm" onClick={openIntent} disabled={generating}>
                  {generating ? '正在分析...' : today.cached === true ? '重新生成' : '生成今日推荐'}
                </Button>
                {today.source === 'ai_empty' && (
                  <span className="text-xs text-text-muted">换个行业/范围再试，可能找到合适标的</span>
                )}
              </div>
            </div>
          ) : (
            <EmptyState icon="🎯" title="今日暂无推荐" description="点击右上角「生成今日推荐」开始（每个交易日 09:15 自动生成）。" />
          )
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
          <Loading text="统计中..." />
        ) : !backtest ? (
          <EmptyState icon="📊" title="暂无回测数据" description="生成推荐并经历评估周期后自动统计胜率与收益。" />
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
          <Loading />
        ) : history.length === 0 ? (
          <EmptyState icon="🗂️" title="暂无历史推荐" description="生成的推荐记录会保存在这里。" />
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

      {/* 按意愿生成 Modal（V1.0.9） */}
      {intentOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={closeIntent}>
          <div
            className="bg-surface rounded-xl shadow-xl w-full max-w-md p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-base font-bold text-primary-900">想要哪方面的推荐？</h3>
              <button onClick={closeIntent} className="text-text-muted hover:text-text px-2 text-lg leading-none">×</button>
            </div>
            <p className="text-xs text-text-muted mb-3">
              输入您想看的行业/类型，AI 会解析并按此范围分析候选股。不输入则全面分析。
            </p>
            <textarea
              value={intentText}
              onChange={(e) => setIntentText(e.target.value)}
              rows={2}
              autoFocus
              placeholder="例如：酒类的股票以及科技股"
              className="w-full rounded border border-border px-3 py-2 text-sm outline-none focus:border-primary-500 resize-none"
            />
            <div className="flex flex-wrap gap-1.5 mt-2">
              {['白酒', '科技/半导体', '新能源车', '银行高股息', '医药', 'AI/算力', '军工', '港股互联网'].map((c) => (
                <button
                  key={c}
                  onClick={() => setIntentText(c)}
                  className={'text-xs rounded-full px-2.5 py-1 border transition-colors ' + (intentText === c ? 'border-primary-500 bg-primary-50 text-primary-700' : 'border-border text-text-secondary hover:border-primary-300')}
                >
                  {c}
                </button>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => handleGenerate('')} disabled={generating}>
                不指定（全面分析）
              </Button>
              <Button size="sm" onClick={() => handleGenerate(intentText.trim())} disabled={generating || !intentText.trim()}>
                {generating ? '分析中（约 10~30 秒）...' : '按此范围分析'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}