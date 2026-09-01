// S15 投资复盘：周/月/季度复盘报告（操作盈亏/胜率/行为偏差 AI 分析）+ 复盘推送
// 契约：/api/review/{history,generate,latest}（后端契约见 t1）
import { useCallback, useEffect, useMemo, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import Stat from '../components/ui/Stat';
import { fmtMoney, fmtPct, fmtTime, num, toList, upDownCls } from '../lib/format';
import {
  generateReview,
  getLatestReview,
  getReviewHistory,
  parseApiError,
  REVIEW_PERIOD_LABEL,
} from '../services/api';
import Ledger from './Ledger';
import type { ReviewBehavior, ReviewPeriod, ReviewReport } from '../services/api';

const PERIODS: ReviewPeriod[] = ['weekly', 'monthly', 'quarterly'];

/** 周期 → 徽章配色 */
function periodVariant(p: string): 'default' | 'warning' | 'info' {
  const s = (p || '').toLowerCase();
  if (s.startsWith('week')) return 'default';
  if (s.startsWith('month')) return 'warning';
  if (s.startsWith('quart')) return 'info';
  return 'default';
}

/** 从 stats 对象按候选键取值（兼容中英文键名） */
function pickStat(stats: Record<string, unknown> | null | undefined, keys: string[]): unknown {
  if (!stats) return null;
  for (const k of keys) {
    const v = stats[k];
    if (v !== undefined && v !== null && v !== '') return v;
  }
  return null;
}

/** 复盘报告 Markdown 分行渲染（标题/分隔线/emoji 着色，参考盘后报告页） */
function renderContent(content: string, keyPrefix: string) {
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

/** 行为偏差卡片：后端 {name, detected, evidence, suggestion}；兼容 level/score/detail */
function BehaviorCard({ b }: { b: ReviewBehavior }) {
  const detected = b.detected !== undefined ? !!b.detected : !((b.level || '').includes('无') || b.level === 'none');
  const detail = b.evidence || b.detail;
  return (
    <div className="border border-border rounded-lg p-3 flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <Badge variant={detected ? 'danger' : 'success'}>{detected ? '已检出' : '未检出'}</Badge>
        <span className="text-sm font-medium">{b.name || '行为偏差'}</span>
        {b.score !== undefined && b.score !== null && (
          <span className="text-xs text-text-muted font-number ml-auto">
            {Math.round(Math.abs(num(b.score) ?? 0) <= 1 ? (num(b.score) ?? 0) * 100 : (num(b.score) ?? 0))}%
          </span>
        )}
      </div>
      {detail && <p className="text-xs text-text-secondary leading-relaxed">{detail}</p>}
      {b.suggestion && <p className="text-xs text-primary-700 leading-relaxed">建议：{b.suggestion}</p>}
    </div>
  );
}

/** 行为偏差条目兼容：数组 / {items:[...]} / 字符串 JSON */
function toBehaviors(raw: unknown): ReviewBehavior[] {
  if (Array.isArray(raw)) return raw as ReviewBehavior[];
  if (raw && typeof raw === 'object') {
    const d = raw as Record<string, unknown>;
    if (Array.isArray(d.items)) return d.items as ReviewBehavior[];
    if (typeof d.behaviors === 'string') {
      try {
        const parsed = JSON.parse(d.behaviors);
        if (Array.isArray(parsed)) return parsed as ReviewBehavior[];
      } catch { /* 忽略解析失败 */ }
    }
  }
  return [];
}

type ReviewTab = 'review' | 'ledger';

export default function Review() {
  const [tab, setTab] = useState<ReviewTab>('review');
  const [period, setPeriod] = useState<ReviewPeriod>('weekly');
  const [history, setHistory] = useState<ReviewReport[]>([]);
  const [latest, setLatest] = useState<ReviewReport | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [latestLoading, setLatestLoading] = useState(false);
  const [error, setError] = useState('');
  const [generating, setGenerating] = useState<ReviewPeriod | null>(null);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const flash = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMsg({ type, text });
    window.setTimeout(() => setMsg(null), 6000);
  };

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setError('');
    const r = await getReviewHistory(20);
    setHistoryLoading(false);
    if (r.ok) setHistory(toList<ReviewReport>(r.data));
    else setError('历史复盘获取失败：' + parseApiError(r.error));
  }, []);

  const loadLatest = useCallback(async (p: ReviewPeriod) => {
    setLatestLoading(true);
    const r = await getLatestReview(p);
    setLatestLoading(false);
    if (!r.ok) {
      setLatest(null);
      return;
    }
    const d = r.data as { exists?: boolean; report?: ReviewReport | null } | undefined;
    setLatest(d && d.exists && d.report ? d.report : null);
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    loadLatest(period);
  }, [period, loadLatest]);

  const handleGenerate = async (p: ReviewPeriod) => {
    setGenerating(p);
    setMsg(null);
    const r = await generateReview(p);
    setGenerating(null);
    if (!r.ok) {
      flash('生成失败：' + parseApiError(r.error), 'err');
      return;
    }
    const d = r.data as { existing?: boolean; sent?: boolean; reason?: string } | undefined;
    if (d?.existing) {
      flash(REVIEW_PERIOD_LABEL[p] + '复盘已生成（不重复生成）' + (d.sent ? '，已推送通知' : ''));
    } else {
      flash(REVIEW_PERIOD_LABEL[p] + '复盘生成完成' + (d?.sent ? '，已推送通知' : d?.reason ? '（' + d.reason + '）' : ''));
    }
    await Promise.all([loadHistory(), loadLatest(p)]);
  };

  // 当前周期报告：latest 需匹配所选周期（latest 是全周期最新），否则从历史列表取
  const current = useMemo<ReviewReport | null>(() => {
    const p = period.toLowerCase();
    if (latest && (latest.period || '').toLowerCase().startsWith(p)) return latest;
    return history.find((h) => (h.period || '').toLowerCase().startsWith(p)) ?? null;
  }, [latest, history, period]);

  const stats = current?.stats && typeof current.stats === 'object' ? (current.stats as Record<string, unknown>) : null;
  const pnl = num(pickStat(stats, ['total_pnl', 'total_profit', 'pnl', 'net_pnl', '操作盈亏']));
  const winRate = num(pickStat(stats, ['win_rate', '胜率']));
  const buyCount = num(pickStat(stats, ['buy_count']));
  const sellCount = num(pickStat(stats, ['sell_count']));
  const tradeCountRaw = pickStat(stats, ['trade_count', 'trades', 'count', '操作次数']);
  const tradeCount = tradeCountRaw !== null
    ? tradeCountRaw
    : (buyCount !== null || sellCount !== null ? (buyCount ?? 0) + (sellCount ?? 0) : null);
  const realizedPnl = num(pickStat(stats, ['realized_pnl', '已实现盈亏']));
  const backtestCount = num(pickStat(stats, ['backtest_count']));
  const avgReturn = num(pickStat(stats, ['avg_return']));
  const netWorthChg = num(pickStat(stats, ['net_worth_change_pct', '净值变化']));
  const behaviors = useMemo<ReviewBehavior[]>(() => toBehaviors(current?.behaviors), [current]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">投资复盘</h1>
          <p className="text-xs text-text-muted mt-1">双 tab：复盘报告（周/月/季度 · 操作盈亏/胜率/行为偏差 AI 分析 · 定时生成并推送）+ 虚拟账本（推荐回测统计 + 模拟交易）</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => { loadHistory(); loadLatest(period); }} disabled={historyLoading && latestLoading}>
            刷新
          </Button>
          {PERIODS.map((p) => (
            <Button key={p} size="sm" variant="primary" onClick={() => handleGenerate(p)} disabled={generating !== null}>
              {generating === p ? '生成中...' : '生成' + REVIEW_PERIOD_LABEL[p] + '复盘'}
            </Button>
          ))}
        </div>
      </div>
      {msg && <p className={'text-sm ' + (msg.type === 'ok' ? 'text-success' : 'text-danger')}>{msg.text}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}

      {/* 双 tab：复盘报告 / 虚拟账本 */}
      <div className="flex rounded-lg border border-border overflow-hidden w-fit">
        {(['review', 'ledger'] as ReviewTab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={'px-4 py-1.5 text-sm transition-colors ' + (tab === t ? 'bg-primary-500 text-white font-medium' : 'bg-white text-text-secondary hover:bg-primary-50')}
          >
            {t === 'review' ? '复盘报告' : '虚拟账本'}
          </button>
        ))}
      </div>

      {tab === 'ledger' ? (
        <Ledger />
      ) : (
      <>
      {/* 周期切换 + 当前报告 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <div className="flex rounded-lg border border-border overflow-hidden">
            {PERIODS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={'px-4 py-1.5 text-sm transition-colors ' + (period === p ? 'bg-primary-500 text-white font-medium' : 'bg-white text-text-secondary hover:bg-primary-50')}
              >
                {REVIEW_PERIOD_LABEL[p]}
              </button>
            ))}
          </div>
          {current && (
            <span className="text-xs text-text-muted">
              {(current.period_start || '').slice(0, 10)} ~ {(current.period_end || '').slice(0, 10)} · 生成于 {fmtTime(current.created_at)}
            </span>
          )}
        </div>

        {latestLoading && !current ? (
          <Loading />
        ) : !current ? (
          <EmptyState
            icon="🔄"
            title={'暂无' + REVIEW_PERIOD_LABEL[period] + '复盘报告'}
            description="每周日 10:00 / 每月 1 日 10:00 自动生成（月度含推荐准确率报告），也可点击右上角手动生成。"
          />
        ) : (
          <div className="space-y-4">
            {/* 结构化统计：操作盈亏 / 胜率 / 交易次数 / 最佳最差交易 */}
            {stats && (
              <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
                <Stat label="操作盈亏" value={fmtMoney(pnl)} cls={upDownCls(pnl)} />
                <Stat label="胜率" value={fmtPct(winRate)} cls={upDownCls(winRate)} />
                <Stat label="交易次数" value={tradeCount !== null ? String(tradeCount) : '—'} />
                <Stat label="已实现盈亏" value={fmtMoney(realizedPnl)} cls={upDownCls(realizedPnl)} />
                <Stat label="推荐回测" value={backtestCount !== null ? backtestCount + ' 次 · 均收 ' + fmtPct(avgReturn) : '—'} />
                <Stat label="净值变化" value={fmtPct(netWorthChg)} cls={upDownCls(netWorthChg)} />
              </div>
            )}

            {/* 行为偏差分析 */}
            {behaviors.length > 0 && (
              <div>
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <h3 className="text-sm font-bold">行为偏差 AI 分析</h3>
                  <Badge variant="info">AI</Badge>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {behaviors.map((b, i) => (
                    <BehaviorCard key={b.name || i} b={b} />
                  ))}
                </div>
              </div>
            )}

            {/* 报告正文 */}
            <div className="border-l-2 border-primary-100 pl-3">
              {renderContent(current.content || '', 'cur-' + current.id)}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
              {current.ai_used === 1 && <Badge variant="info">AI 生成</Badge>}
              {current.ai_used === 0 && <Badge variant="default">规则降级</Badge>}
              {current.sent === 1 && <Badge variant="success">已推送</Badge>}
              {current.sent === 0 && <Badge variant="warning">未推送</Badge>}
            </div>
          </div>
        )}
      </Card>

      {/* 历史复盘 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">历史复盘</h2>
          <span className="text-xs text-text-muted">最近 20 份 · 点击展开查看内容</span>
          <div className="ml-auto">
            <Button variant="secondary" size="sm" onClick={loadHistory} disabled={historyLoading}>
              {historyLoading ? '刷新中...' : '刷新'}
            </Button>
          </div>
        </div>
        {historyLoading && history.length === 0 ? (
          <Loading />
        ) : history.length === 0 ? (
          <EmptyState icon="🗂️" title="暂无历史复盘" description="生成的复盘报告会自动存档在这里，点击条目展开查看。" />
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
                    <Badge variant={periodVariant(h.period)}>{REVIEW_PERIOD_LABEL[h.period] || h.period}</Badge>
                    <span className="text-xs text-text-muted font-number">
                      {(h.period_start || '').slice(0, 10)} ~ {(h.period_end || '').slice(0, 10)}
                    </span>
                    <span className="text-xs text-text-muted font-number">{fmtTime(h.created_at)}</span>
                    {h.sent === 1 && <Badge variant="success">已推送</Badge>}
                    <span className="text-xs text-text-secondary ml-auto">{open ? '收起 ▲' : '展开 ▼'}</span>
                  </button>
                  {open && (
                    <div className="px-2 pb-3">
                      <div className="border-l-2 border-primary-100 pl-3">
                        {renderContent(h.content || '', 'his-' + h.id)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
      </>
      )}
    </div>
  );
}