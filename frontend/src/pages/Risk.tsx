// S14 风险分析与宏观研判
// 契约：GET /api/risk/overview · POST /api/risk/stress-test · GET /api/macro/overview · POST /api/macro/refresh · GET /api/risk/alerts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import {
  getMacroOverview,
  getRiskAlerts,
  getRiskOverview,
  parseApiError,
  refreshMacro,
  runStressTest,
} from '../services/api';
import type {
  MacroFactor,
  MacroIndicator,
  MacroOverview,
  MacroSignalLevel,
  RiskAlert,
  RiskConcentrationItem,
  RiskAlertLog,
  RiskOverview,
  StressScenario,
  StressTestResult,
} from '../services/api';

// ---------------- 格式化工具 ----------------

/** 百分比：兼容小数（0.25）与百分数（25）两种返回 */
function fmtPct(v: number | string | null | undefined, digits = 1): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'string' ? Number(v) : v;
  if (!Number.isFinite(n)) return String(v);
  const abs = Math.abs(n);
  const pct = abs <= 1 ? n * 100 : n;
  return pct.toFixed(digits) + '%';
}

/** 金额：元 → 万/亿 中文缩写 */
function fmtMoney(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'string' ? Number(v) : v;
  if (!Number.isFinite(n)) return String(v);
  const abs = Math.abs(n);
  if (abs >= 1e8) return '¥' + (n / 1e8).toFixed(2) + ' 亿';
  if (abs >= 1e4) return '¥' + (n / 1e4).toFixed(2) + ' 万';
  return '¥' + n.toFixed(2);
}

/** 数值（Beta/夏普等，两位小数） */
function fmtNum(v: number | string | null | undefined, digits = 2): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'string' ? Number(v) : v;
  if (!Number.isFinite(n)) return String(v);
  return n.toFixed(digits);
}

/** 回撤显示值：null/空 → 原样（显示 —），数值取绝对值（兼容小数/百分数） */
function drawdownDisplay(v: number | string | null | undefined): number | string | null | undefined {
  if (v === null || v === undefined || v === '') return v;
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  return Math.abs(n);
}

/** 集中度百分数：兼容小数（0.25）与百分数（25） → 统一为百分数 */
function concPct(v: number | string | null | undefined): number {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n)) return 0;
  return Math.abs(n) <= 1 ? n * 100 : n;
}

/** 时间：created_at "2026-08-31 15:30:05" → "08-31 15:30" */
function fmtTime(s: string | null | undefined): string {
  if (!s) return '';
  const m = /(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})/.exec(s);
  if (m) return m[1].slice(5) + ' ' + m[2];
  return s.slice(0, 16);
}

// ---------------- 宏观信号 ----------------

const SIGNAL_META: Record<MacroSignalLevel, { label: string; emoji: string; desc: string; cls: string }> = {
  green: { label: '环境友好', emoji: '🟢', desc: '宏观环境友好，可正常操作', cls: 'bg-success/10 border-success/60 text-success' },
  yellow: { label: '中性偏谨慎', emoji: '🟡', desc: '宏观环境偏谨慎，控制仓位', cls: 'bg-warning/15 border-warning/70 text-warning' },
  red: { label: '风险偏高', emoji: '🔴', desc: '暂停短线操作，注意风险', cls: 'bg-danger/10 border-danger/70 text-danger' },
  black: { label: '系统性风险', emoji: '⚫', desc: '暂停买入，规避系统性风险', cls: 'bg-neutral-900 border-neutral-900 text-white' },
};

/** 兼容后端 level='green|yellow|red|black' 与 signal='🟢|🟡|🔴|⚫' 两种形态 */
function resolveMacroLevel(m: MacroOverview | null | undefined): MacroSignalLevel {
  const lvl = String(m?.level ?? '').trim().toLowerCase();
  if (lvl === 'green' || lvl === 'yellow' || lvl === 'red' || lvl === 'black') return lvl as MacroSignalLevel;
  const sig = String(m?.signal ?? '');
  if (sig.includes('🟢') || sig.toLowerCase().includes('green')) return 'green';
  if (sig.includes('🟡') || sig.toLowerCase().includes('yellow')) return 'yellow';
  if (sig.includes('🔴') || sig.toLowerCase().includes('red')) return 'red';
  if (sig.includes('⚫') || sig.toLowerCase().includes('black')) return 'black';
  return 'green';
}

/** 宏观指标列表：兼容 indicators[] 与 factors[] 两种返回 */
function normalizeMacroIndicators(m: MacroOverview | null | undefined): MacroIndicator[] {
  const list: MacroIndicator[] = [];
  const raw = m?.indicators;
  if (Array.isArray(raw)) {
    for (const it of raw) {
      if (it && typeof it === 'object') list.push({ ...(it as MacroIndicator) });
    }
  }
  const facts = m?.factors;
  if (Array.isArray(facts)) {
    for (const f of facts as MacroFactor[]) {
      list.push({
        indicator: f.name,
        name: f.name,
        region: '信号因子',
        value: f.value,
        date: null,
        source: f.note ?? null,
      });
    }
  }
  return list;
}

/** 信号因子说明（横幅下方 chips） */
function macroFactors(m: MacroOverview | null | undefined): MacroFactor[] {
  return Array.isArray(m?.factors) ? (m.factors as MacroFactor[]) : [];
}

// ---------------- 预警映射 ----------------

/** 把预警 indicator（英文键或中文名）映射到指标卡片 id */
function alertMetricKey(indicator: string | null | undefined): string | null {
  const s = String(indicator ?? '').trim().toLowerCase();
  if (!s) return null;
  if (s.includes('concentration') || s.includes('集中')) return 'concentration';
  if (s.includes('market') || s.includes('占比') || s.includes('行业')) return 'market';
  if (s.includes('drawdown') || s.includes('回撤')) return 'drawdown';
  if (s === 'beta') return 'beta';
  if (s.includes('sharpe') || s.includes('夏普')) return 'sharpe';
  if (s.includes('var') || s.includes('在险')) return 'var';
  return null;
}

function alertBadgeVariant(level: string | null | undefined): 'danger' | 'warning' | 'info' | 'default' {
  const s = String(level ?? '');
  if (s.includes('紧急')) return 'danger';
  if (s.includes('预警') || s.includes('关注') || s.includes('警告')) return 'warning';
  if (s.includes('提示')) return 'info';
  return 'default';
}

// ---------------- 指标卡片 ----------------

interface MetricCardProps {
  label: string;
  value: string;
  hint?: string;
  /** 通俗解读（新手友好，大白话说明指标含义与怎么看） */
  explain?: string;
  /** normal | danger | warning（预警项红色边框） */
  tone?: 'normal' | 'danger' | 'warning';
  /** 警示徽章文字 */
  alertLabel?: string;
}

function MetricCard({ label, value, hint, explain, tone = 'normal', alertLabel }: MetricCardProps) {
  const border =
    tone === 'danger' ? 'border-danger/70' : tone === 'warning' ? 'border-warning/70' : 'border-border';
  const valueCls =
    tone === 'danger' ? 'text-danger' : tone === 'warning' ? 'text-warning' : 'text-primary-900';
  return (
    <div className={'bg-surface rounded-lg border p-3 flex flex-col gap-1 ' + border}>
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-text-secondary">{label}</span>
        {alertLabel && <Badge variant="danger">{alertLabel}</Badge>}
      </div>
      <div className={'text-xl font-bold font-number ' + valueCls}>{value}</div>
      {hint && <div className="text-xs text-text-muted">{hint}</div>}
      {explain && <div className="text-[11px] leading-4 text-text-secondary/80 mt-0.5">{explain}</div>}
    </div>
  );
}

// ---------------- 压力测试明细渲染 ----------------

/** detail 兼容字符串 / 对象 / 数组 */
function renderDetail(detail: StressTestResult['detail'], keyPrefix: string) {
  if (detail === null || detail === undefined || detail === '') return null;
  if (typeof detail === 'string') {
    return detail.split('\n').map((line, i) => (
      <p key={keyPrefix + '-s' + i} className="text-sm text-text-secondary leading-6 whitespace-pre-wrap">
        {line.replace(/\*\*/g, '')}
      </p>
    ));
  }
  if (Array.isArray(detail)) {
    return (
      <ul className="space-y-1">
        {detail.map((it, i) => {
          const obj = it && typeof it === 'object' ? (it as Record<string, unknown>) : null;
          const pctVal = obj ? obj.loss_pct ?? obj.weight_pct : undefined;
          const name = obj ? String(obj.name ?? obj.symbol ?? JSON.stringify(it)) : String(it);
          const valN = obj && obj.value !== undefined && pctVal === undefined ? Number(obj.value) : NaN;
          return (
            <li key={keyPrefix + '-a' + i} className="text-sm text-text-secondary leading-6">
              {name}
              {pctVal !== undefined ? ' · ' + fmtPct(Number(pctVal)) : ''}
              {Number.isFinite(valN) ? ' · ' + fmtMoney(valN) : ''}
            </li>
          );
        })}
      </ul>
    );
  }
  if (typeof detail === 'object') {
    return (
      <ul className="space-y-1">
        {Object.entries(detail).map(([k, v]) => (
          <li key={keyPrefix + '-o' + k} className="text-sm text-text-secondary leading-6">
            <span className="text-text-muted">{k}：</span>
            {typeof v === 'number' && (k.includes('pct') || k.includes('权重') || k.includes('跌幅')) ? fmtPct(v) : String(v)}
          </li>
        ))}
      </ul>
    );
  }
  return <p className="text-sm text-text-secondary">{String(detail)}</p>;
}

// ---------------- 场景定义 ----------------

const SCENARIOS: { key: StressScenario; label: string; desc: string }[] = [
  { key: 'market_down_10', label: '大盘跌 10%', desc: '组合按 Beta × 10% 估算损失' },
  { key: 'hk_tech_down_20', label: '港股科技跌 20%', desc: '港股持仓按权重 × 20% 估算' },
  { key: 'cny_depreciate_5', label: '人民币贬值 5%', desc: '港股市值按汇率 5% 估算损失' },
];

export default function Risk() {
  // 组合风险
  const [overview, setOverview] = useState<RiskOverview | null>(null);
  const [ovLoading, setOvLoading] = useState(false);
  const [ovError, setOvError] = useState('');
  const ovSeq = useRef(0);

  // 压力测试
  const [running, setRunning] = useState<StressScenario | null>(null);
  const [stress, setStress] = useState<StressTestResult | null>(null);
  const [stressError, setStressError] = useState('');

  // 宏观研判
  const [macro, setMacro] = useState<MacroOverview | null>(null);
  const [macroLoading, setMacroLoading] = useState(false);
  const [macroError, setMacroError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const macroSeq = useRef(0);

  // 预警通知历史
  const [alertLog, setAlertLog] = useState<RiskAlertLog[]>([]);
  const [alertLogLoading, setAlertLogLoading] = useState(false);

  const loadOverview = useCallback(async () => {
    const seq = ++ovSeq.current;
    setOvLoading(true);
    setOvError('');
    const r = await getRiskOverview();
    if (seq !== ovSeq.current) return;
    setOvLoading(false);
    if (r.ok) setOverview((r.data as RiskOverview) ?? null);
    else setOvError('组合风险获取失败：' + parseApiError(r.error));
  }, []);

  const loadMacro = useCallback(async () => {
    const seq = ++macroSeq.current;
    setMacroLoading(true);
    setMacroError('');
    const r = await getMacroOverview();
    if (seq !== macroSeq.current) return;
    setMacroLoading(false);
    if (r.ok) setMacro((r.data as MacroOverview) ?? null);
    else setMacroError('宏观研判获取失败：' + parseApiError(r.error));
  }, []);

  const loadAlertLog = useCallback(async () => {
    setAlertLogLoading(true);
    const r = await getRiskAlerts(10);
    setAlertLogLoading(false);
    if (r.ok) {
      const d = r.data;
      setAlertLog(Array.isArray(d) ? (d as RiskAlertLog[]) : []);
    }
  }, []);

  useEffect(() => {
    loadOverview();
    loadMacro();
    loadAlertLog();
  }, [loadOverview, loadMacro, loadAlertLog]);

  const handleStress = async (scenario: StressScenario) => {
    setRunning(scenario);
    setStressError('');
    setStress(null);
    const r = await runStressTest(scenario);
    setRunning(null);
    if (!r.ok) {
      setStressError('压力测试失败：' + parseApiError(r.error));
      return;
    }
    const d = r.data as StressTestResult | undefined;
    if (d?.error) {
      setStressError('压力测试失败：' + d.error);
      return;
    }
    setStress(d ?? null);
  };

  const handleMacroRefresh = async () => {
    setRefreshing(true);
    setMacroError('');
    const r = await refreshMacro();
    setRefreshing(false);
    if (!r.ok) {
      setMacroError('宏观数据刷新失败：' + parseApiError(r.error));
      return;
    }
    const d = r.data as MacroOverview | undefined;
    if (d?.error) {
      setMacroError('宏观数据刷新失败：' + d.error);
      return;
    }
    setMacro(d ?? null);
    await loadAlertLog();
  };

  // ---- 组合风险派生数据 ----
  const ind = overview?.indicators;
  const alerts: RiskAlert[] = Array.isArray(overview?.alerts) ? (overview.alerts as RiskAlert[]) : [];
  const alertKeys = useMemo(() => {
    const set = new Set<string>();
    for (const a of alerts) {
      const k = alertMetricKey(a.indicator);
      if (k) set.add(k);
    }
    return set;
  }, [alerts]);

  const concentrationDetail = useMemo(() => {
    const d = ind?.concentration_detail;
    return Array.isArray(d) ? (d as RiskConcentrationItem[]) : [];
  }, [ind]);

  // market_share 为 {A股: 0.4, 港股: 0.6} 对象 → 排序数组（0.6 = 60%）
  const marketShareTop = useMemo(() => {
    const m = ind?.market_share;
    const arr: { market: string; share: number }[] = [];
    if (m && typeof m === 'object') {
      for (const [mk, v] of Object.entries(m as Record<string, unknown>)) {
        const n = Number(v);
        if (Number.isFinite(n)) arr.push({ market: mk, share: n });
      }
    }
    return arr.sort((a, b) => b.share - a.share);
  }, [ind]);

  // ---- 宏观派生数据 ----
  const signal = resolveMacroLevel(macro);
  const signalMeta = SIGNAL_META[signal];
  const macroItems = useMemo(() => normalizeMacroIndicators(macro), [macro]);
  const factors = useMemo(() => macroFactors(macro), [macro]);
  const macroRegion = useMemo(() => {
    const m = new Map<string, MacroIndicator[]>();
    for (const it of macroItems) {
      const region = it.region || '其他';
      if (!m.has(region)) m.set(region, []);
      m.get(region)!.push(it);
    }
    return [...m.entries()];
  }, [macroItems]);

  const loadingAny = ovLoading || macroLoading;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">风险分析</h1>
          <p className="text-xs text-text-muted mt-1">组合风险指标 · 压力测试模拟 · 宏观研判（四色信号）· 超限预警通知</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => { loadOverview(); loadAlertLog(); }} disabled={loadingAny}>
            {loadingAny ? '加载中...' : '刷新风险'}
          </Button>
          <Button size="sm" onClick={handleMacroRefresh} disabled={refreshing || macroLoading}>
            {refreshing ? '采集中...' : '刷新宏观数据'}
          </Button>
        </div>
      </div>

      {/* 1. 组合风险 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">组合风险指标</h2>
          {overview?.updated_at && <span className="text-xs text-text-muted">更新于 {fmtTime(overview.updated_at)}</span>}
          <span className="text-xs text-text-muted ml-auto">阈值：集中度 &gt;20% · 市场占比 &gt;40% · Beta &gt;1.5 · 夏普 &lt;0 · VaR 超可承受</span>
        </div>
        {ovError && <p className="text-sm text-danger mb-2">{ovError}</p>}
        {ovLoading && !overview ? (
          <Loading />
        ) : !overview ? (
          <EmptyState icon="🛡️" title="暂无风险数据" description="请先在「持仓总览」同步持仓，或确认后端已启动。" />
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
              <MetricCard label="组合总市值" value={fmtMoney(overview.total_value)} hint="全部持仓按现价估算"
                explain="你的全部持仓按当前市价合计值多少钱（不含现金）。市值越大，整体涨跌的金额影响也越大。" />
              <MetricCard
                label="单只最大集中度"
                value={fmtPct(ind?.concentration_max)}
                hint={concentrationDetail.length > 0 ? '最大持仓：' + (concentrationDetail[0]?.name || concentrationDetail[0]?.symbol || '—') : '超过 20% 预警'}
                explain="最重仓的一只股票占组合的比例。超过 20% 说明押注这只股票过重——它一旦大跌，会明显拖累整体收益。"
                tone={alertKeys.has('concentration') ? 'danger' : 'normal'}
                alertLabel={alertKeys.has('concentration') ? '预警' : undefined}
              />
              <MetricCard
                label="最高市场占比"
                value={fmtPct(Number(marketShareTop[0]?.share) || 0)}
                hint={marketShareTop.length > 0 ? marketShareTop.map((m) => m.market + ' ' + fmtPct(m.share)).join(' · ') : 'A股/港股 按市值占比'}
                explain="A股或港股的市值占组合的比例。超过 40% 说明你主要押注单一市场，跨市场分散不足。"
                tone={alertKeys.has('market') ? 'danger' : 'normal'}
                alertLabel={alertKeys.has('market') ? '预警' : undefined}
              />
              <MetricCard
                label="最大回撤"
                value={fmtPct(drawdownDisplay(ind?.max_drawdown))}
                hint="按 60 日 K 线组合净值估算"
                explain="最近 60 个交易日里，组合从高点最多回落了多少。数值越大说明波动越剧烈，扛单体验越差。"
                tone={alertKeys.has('drawdown') ? 'warning' : 'normal'}
                alertLabel={alertKeys.has('drawdown') ? '关注' : undefined}
              />
              <MetricCard
                label="Beta"
                value={fmtNum(ind?.beta)}
                hint="对大盘指数 · 大于 1.5 提示"
                explain="组合相对大盘的波动倍数：1 表示与大盘同步；大于 1 涨跌都比大盘更猛；小于 1 更稳。"
                tone={alertKeys.has('beta') ? 'warning' : 'normal'}
                alertLabel={alertKeys.has('beta') ? '关注' : undefined}
              />
              <MetricCard
                label="夏普比率"
                value={fmtNum(ind?.sharpe)}
                hint="年化 · 无风险利率 2% · 小于 0 提示"
                explain="每承受一份波动换来多少超额回报，越高说明「性价比」越好；小于 0 表示收益跑不赢国债。"
                tone={alertKeys.has('sharpe') ? 'danger' : 'normal'}
                alertLabel={alertKeys.has('sharpe') ? '预警' : undefined}
              />
              <MetricCard
                label="VaR（95% 日损失）"
                value={fmtMoney(ind?.var)}
                hint="历史模拟法 · 单日最大可能损失"
                explain="按历史波动估算：95% 的概率单日亏损不超过这个金额（仍有 5% 概率亏更多）。"
                tone={alertKeys.has('var') ? 'danger' : 'normal'}
                alertLabel={alertKeys.has('var') ? '预警' : undefined}
              />
            </div>

            {/* 集中度明细 */}
            {concentrationDetail.length > 0 && (
              <div className="mt-4">
                <div className="text-xs text-text-muted mb-2">单只集中度明细（按市值权重）</div>
                <div className="flex flex-wrap gap-2">
                  {concentrationDetail.map((c, i) => (
                    <span key={c.symbol || c.name || i} className="inline-flex items-center gap-2 text-xs bg-bg-secondary border border-border rounded px-2 py-1">
                      <span className="font-medium">{c.name || c.symbol || '—'}</span>
                      <span className="text-text-muted">{c.market || ''}</span>
                      <span className={'font-number ' + (concPct(c.weight ?? c.weight_pct ?? 0) > 20 ? 'text-danger' : 'text-text-secondary')}>
                        {fmtPct(c.weight ?? c.weight_pct ?? 0)}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 预警列表 */}
            {alerts.length > 0 && (
              <div className="mt-4 border border-danger/40 rounded-lg p-3 bg-danger/5">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm font-bold text-danger">⚠ 风险预警</span>
                  <span className="text-xs text-text-muted">{alerts.length} 项超限</span>
                </div>
                <ul className="space-y-1.5">
                  {alerts.map((a, i) => {
                    // 按指标类型格式化：集中度/占比/回撤=百分数（小数×100），Beta/夏普=数值，VaR=金额
                    const key = alertMetricKey(a.indicator);
                    const fmtCur = (v: unknown) => {
                      if (v === null || v === undefined || v === '') return '—';
                      const n = typeof v === 'number' ? v : Number(v);
                      if (!Number.isFinite(n)) return String(v);
                      if (key === 'beta' || key === 'sharpe') return fmtNum(n);
                      if (key === 'var') return fmtMoney(n);
                      return fmtPct(n);
                    };
                    return (
                      <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                        <Badge variant={alertBadgeVariant(a.level)}>{a.level || '预警'}</Badge>
                        <span className="font-medium">{String(a.indicator ?? '')}</span>
                        <span className="text-text-secondary font-number">当前 {fmtCur(a.value)}</span>
                        <span className="text-text-muted">阈值 {fmtCur(a.threshold)}</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </>
        )}
      </Card>

      {/* 2. 压力测试 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">压力测试</h2>
          <span className="text-xs text-text-muted">基于 Beta 与持仓暴露估算场景损失</span>
        </div>
        <div className="flex flex-wrap gap-2 mb-4">
          {SCENARIOS.map((s) => (
            <Button
              key={s.key}
              variant="secondary"
              size="sm"
              disabled={running !== null}
              onClick={() => handleStress(s.key)}
            >
              {running === s.key ? '测算中...' : s.label}
            </Button>
          ))}
        </div>
        {stressError && <p className="text-sm text-danger mb-2">{stressError}</p>}
        {stress && (
          <div className="border border-border rounded-lg p-4 bg-bg-secondary/60">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 mb-3">
              <div>
                <div className="text-xs text-text-muted mb-1">估算损失</div>
                <div className="text-2xl font-bold font-number text-danger">{fmtMoney(stress.estimated_loss)}</div>
              </div>
              <div>
                <div className="text-xs text-text-muted mb-1">占组合比例</div>
                <div className="text-2xl font-bold font-number text-warning">{fmtPct(stress.estimated_loss_pct)}</div>
              </div>
              {stress.scenario && (
                <div className="ml-auto">
                  <Badge variant="info">{SCENARIOS.find((s) => s.key === stress.scenario)?.label || stress.scenario}</Badge>
                </div>
              )}
            </div>
            {renderDetail(stress.detail, 'stress-' + stress.scenario)}
          </div>
        )}
      </Card>

      {/* 3. 宏观研判 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">宏观研判</h2>
          {macro?.updated_at && <span className="text-xs text-text-muted">更新于 {fmtTime(macro.updated_at)}</span>}
          <span className="text-xs text-text-muted ml-auto">全球（VIX/美元/原油/黄金）· 中国宏观（CPI/PMI）· 市场情绪 · 四色信号约束推荐</span>
        </div>
        {macroError && <p className="text-sm text-danger mb-2">{macroError}</p>}
        {macroLoading && !macro ? (
          <Loading text="加载中（宏观采集约需 10~30 秒）..." />
        ) : !macro ? (
          <EmptyState icon="🌐" title="暂无宏观数据" description="点击右上角「刷新宏观数据」采集全球与中国宏观指标。" />
        ) : (
          <>
            {/* 四色信号横幅 */}
            <div className={'rounded-lg border px-4 py-3 mb-3 ' + signalMeta.cls}>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-2xl">{signalMeta.emoji}</span>
                <div>
                  <div className="font-bold text-base">{signalMeta.label}</div>
                  <div className="text-xs opacity-80">{signalMeta.desc}</div>
                </div>
              </div>
              {factors.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {factors.map((f, i) => (
                    <span key={i} className="text-xs bg-white/30 rounded px-2 py-0.5">
                      {f.name}：{typeof f.value === 'number' ? fmtNum(f.value) : String(f.value ?? '—')}
                      {f.note ? '（' + f.note + '）' : ''}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 指标列表 */}
            {macroItems.length === 0 ? (
              <p className="text-sm text-text-muted">暂无宏观指标数据，可点击「刷新宏观数据」重新采集。</p>
            ) : (
              <div className="space-y-3">
                {macroRegion.map(([region, items]) => (
                  <div key={region}>
                    <div className="text-xs font-medium text-text-secondary mb-1.5">{region}</div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="bg-bg-secondary">
                            <th className="px-3 py-1.5 text-left font-medium text-text-secondary text-xs">指标</th>
                            <th className="px-3 py-1.5 text-right font-medium text-text-secondary text-xs">值</th>
                            <th className="px-3 py-1.5 text-right font-medium text-text-secondary text-xs">日期</th>
                            <th className="px-3 py-1.5 text-left font-medium text-text-secondary text-xs">来源</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.map((it, i) => {
                            const name = it.name || it.indicator || '—';
                            const val = typeof it.value === 'number' ? fmtNum(it.value) : String(it.value ?? '—');
                            return (
                              <tr key={name + i} className="border-t border-border">
                                <td className="px-3 py-1.5">{name}</td>
                                <td className="px-3 py-1.5 text-right font-number">{val}</td>
                                <td className="px-3 py-1.5 text-right text-xs text-text-muted">{fmtTime(it.date) || '—'}</td>
                                <td className="px-3 py-1.5 text-xs text-text-muted">{it.source || '—'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      {/* 4. 预警通知 */}
      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">预警通知</h2>
          <span className="text-xs text-text-muted">最近风险预警（应用内通知）</span>
          <div className="ml-auto">
            <Button variant="secondary" size="sm" onClick={loadAlertLog} disabled={alertLogLoading}>
              {alertLogLoading ? '刷新中...' : '刷新'}
            </Button>
          </div>
        </div>
        {alertLogLoading && alertLog.length === 0 ? (
          <Loading />
        ) : alertLog.length === 0 ? (
          <EmptyState icon="🔕" title="暂无风险预警通知" description="组合指标超限或宏观信号变化时，会在这里生成预警通知。" />
        ) : (
          <div className="divide-y divide-border">
            {alertLog.map((a) => (
              <div key={a.id ?? String(a.created_at)} className="py-2 flex flex-wrap items-start gap-x-3 gap-y-1">
                <span className="text-xs text-text-muted font-number mt-0.5 w-24 shrink-0">{fmtTime(a.created_at)}</span>
                <Badge variant={alertBadgeVariant(a.level || a.type)}>{a.level || a.type || '通知'}</Badge>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{a.title || '风险预警'}</div>
                  {a.content && <div className="text-xs text-text-secondary mt-0.5 whitespace-pre-wrap">{a.content}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
