// V1.1.1 M3 个股诊股：搜索 → 聚合分析（行情/K线/技术/位置/资讯/研报）+ AI 综合点评（强免责）
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Loading from '../components/ui/Loading';
import KLineChart from '../components/KLineChart';
import { api, parseApiError } from '../services/api';
import { fmtBig, fmtNum } from '../lib/format';
import type { KlineBar } from '../services/api';

interface Analysis {
  ok?: boolean;
  error?: string;
  symbol?: string;
  name?: string;
  market?: string;
  quote?: Record<string, unknown>;
  kline?: KlineBar[];
  tech?: Record<string, unknown>;
  position?: string;
  news?: { title: string; source?: string; url?: string }[];
  research?: { title: string; org?: string; rating?: string }[];
  disclaimer?: string;
}

function renderMd(text: string, key: string) {
  return text.split('\n').map((line, i) => {
    const t = line.trim();
    if (!t) return <div key={key + i} className="h-1" />;
    const h = /^(#{1,3})\s+(.*)$/.exec(t);
    if (h) return <p key={key + i} className={'mt-1 font-bold text-primary-800 ' + (h[1].length <= 2 ? 'text-sm' : 'text-xs')}>{h[2].replace(/\*\*/g, '')}</p>;
    if (t.startsWith('-') || t.startsWith('*')) {
      return <p key={key + i} className="text-sm leading-6 text-text-secondary flex gap-1.5"><span className="text-primary-500">•</span><span className="whitespace-pre-wrap">{t.slice(1).trim().replace(/\*\*/g, '')}</span></p>;
    }
    return <p key={key + i} className="text-sm leading-6 text-text-secondary whitespace-pre-wrap">{t.replace(/\*\*/g, '')}</p>;
  });
}

export default function StockAnalyze() {
  const [params] = useSearchParams();
  const urlSymbol = params.get('symbol');
  const urlMarket = params.get('market') === '港股' ? '港股' : 'A股';
  const [symbol, setSymbol] = useState(urlSymbol || '');
  const [market, setMarket] = useState(urlMarket);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<Analysis | null>(null);
  const [aiText, setAiText] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState('');

  const analyze = async (sym?: string, mkt?: string) => {
    const s = (sym ?? symbol).trim();
    const mk = mkt ?? market;
    if (!s) return;
    setLoading(true); setError(''); setData(null); setAiText(''); setAiError('');
    const r = await api<Analysis>('GET', '/api/stock/analysis?symbol=' + encodeURIComponent(s) + '&market=' + encodeURIComponent(mk));
    setLoading(false);
    if (r.ok && r.data?.ok) setData(r.data as Analysis);
    else setError('分析失败：' + (((r.data as Analysis)?.error) || parseApiError(r.error)));
  };

  useEffect(() => {
    if (urlSymbol) {
      setSymbol(urlSymbol);
      setMarket(urlMarket);
      void analyze(urlSymbol, urlMarket);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSymbol]);

  const askAi = async () => {
    if (!data) return;
    setAiLoading(true); setAiError('');
    const r = await api<{ ok?: boolean; degraded?: boolean; comment?: string }>('POST', '/api/stock/analysis/ai', data as unknown as Record<string, unknown>);
    setAiLoading(false);
    if (r.ok && r.data?.comment) setAiText(r.data.comment);
    else setAiError('AI 点评失败：' + ((r.data as { error?: string })?.error || parseApiError(r.error)));
  };

  const quote = data?.quote || {};
  const price = quote.price != null ? Number(quote.price) : null;
  const chg = quote.change_pct != null ? Number(quote.change_pct) : null;
  const tech = (data?.tech || {}) as Record<string, unknown>;
  const techRows = useMemo(() => {
    const rows: [string, string][] = [];
    if (tech.ma_status != null) rows.push(['均线状态', String(tech.ma_status)]);
    const macd = tech.macd as Record<string, unknown> | undefined;
    if (macd) rows.push(['MACD', 'DIF ' + fmtNum(Number(macd.dif)) + ' · DEA ' + fmtNum(Number(macd.dea)) + (macd.golden_cross ? '（金叉）' : '')]);
    if (tech.rsi14 != null) rows.push(['RSI(14)', fmtNum(Number(tech.rsi14), 1)]);
    const kdj = tech.kdj as Record<string, unknown> | undefined;
    if (kdj) rows.push(['KDJ', 'K ' + fmtNum(Number(kdj.k), 1) + ' · D ' + fmtNum(Number(kdj.d), 1) + ' · J ' + fmtNum(Number(kdj.j), 1)]);
    if (tech.boll_pos != null) rows.push(['布林位置', String(tech.boll_pos)]);
    if (tech.vol_ratio != null) rows.push(['量比', fmtNum(Number(tech.vol_ratio), 2)]);
    if (tech.weekly_trend != null) rows.push(['周线趋势', String(tech.weekly_trend)]);
    if (tech.monthly_trend != null) rows.push(['月线趋势', String(tech.monthly_trend)]);
    if (tech.chg_5d != null) rows.push(['近5日涨跌', Number(tech.chg_5d) + '%']);
    if (tech.chg_20d != null) rows.push(['近20日涨跌', Number(tech.chg_20d) + '%']);
    return rows;
  }, [tech]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-primary-900">个股诊股</h1>
          <p className="text-xs text-text-muted mt-1">输入股票代码一键获取行情 / 技术 / 位置 / 资讯研报聚合分析，AI 可选点评（A股 6 位、港股 5 位，如 600519 / 00700）</p>
        </div>
      </div>

      <Card>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <div className="text-xs text-text-secondary mb-1">股票代码</div>
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void analyze(); }}
              placeholder="如 600519 / 00700"
              className="rounded border border-border px-3 py-2 text-sm w-44 outline-none focus:border-primary-500" />
          </div>
          <div>
            <div className="text-xs text-text-secondary mb-1">市场</div>
            <select value={market} onChange={(e) => setMarket(e.target.value)}
              className="rounded border border-border px-3 py-2 text-sm bg-white outline-none focus:border-primary-500">
              <option value="A股">A股</option>
              <option value="港股">港股</option>
            </select>
          </div>
          <Button onClick={() => void analyze()} disabled={loading || !symbol.trim()}>
            {loading ? '分析中（拉取行情与 90 日K线）...' : '🔍 开始诊股'}
          </Button>
        </div>
        {error && <p className="text-sm text-danger mt-2">{error}</p>}
      </Card>

      {data && (
        <>
          {/* 概览 */}
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <div>
                <span className="text-lg font-bold text-primary-900">{data.name}</span>
                <span className="text-xs text-text-muted font-number ml-2">{data.symbol} · {data.market}</span>
              </div>
              <span className="text-xl font-bold font-number">{price != null ? fmtNum(price, data.market === '港股' ? 3 : 2) : '—'}</span>
              <Badge variant={chg != null && chg >= 0 ? 'success' : 'danger'}>
                {chg != null ? (chg > 0 ? '+' : '') + chg.toFixed(2) + '%' : '—'}
              </Badge>
              {data.position && (
                <Badge variant={data.position === '高位' ? 'danger' : data.position === '低位' ? 'success' : 'info'}>
                  60日区间：{data.position}
                </Badge>
              )}
              <span className="text-xs text-text-muted ml-auto">
                {quote.pe != null ? 'PE ' + fmtNum(Number(quote.pe), 1) : ''}
                {quote.pb != null ? ' · PB ' + fmtNum(Number(quote.pb), 2) : ''}
                {quote.total_market_cap != null ? ' · 市值 ' + fmtBig(Number(quote.total_market_cap)) : ''}
                {quote.turnover != null ? ' · 换手 ' + fmtNum(Number(quote.turnover), 2) + '%' : ''}
              </span>
            </div>
            {data.disclaimer && <p className="text-xs text-danger/80 mt-2">⚠ {data.disclaimer}</p>}
          </Card>

          {/* K 线 */}
          {Array.isArray(data.kline) && data.kline.length > 0 && (
            <Card>
              <h2 className="font-bold text-sm mb-2">K 线走势（近 90 日 · 日K）</h2>
              <KLineChart bars={data.kline as KlineBar[]} height={300} />
            </Card>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {/* 技术体检 */}
            <Card>
              <h2 className="font-bold text-sm mb-2">技术体检</h2>
              <table className="w-full text-sm">
                <tbody>
                  {techRows.map(([k, v]) => (
                    <tr key={k} className="border-t border-border first:border-t-0">
                      <td className="px-2 py-1.5 text-xs text-text-secondary w-28">{k}</td>
                      <td className="px-2 py-1.5 text-text-secondary font-number">{v}</td>
                    </tr>
                  ))}
                  {techRows.length === 0 && <tr><td className="px-2 py-2 text-xs text-text-muted">暂无技术数据</td></tr>}
                </tbody>
              </table>
            </Card>

            <div className="space-y-4">
              {/* 资讯研报 */}
              <Card>
                <h2 className="font-bold text-sm mb-2">相关资讯与研报</h2>
                {(data.news || []).length === 0 && (data.research || []).length === 0 ? (
                  <p className="text-xs text-text-muted">暂无关联内容（资讯库与研报源未命中）。</p>
                ) : (
                  <div className="space-y-1">
                    {(data.news || []).slice(0, 3).map((it, i) => (
                      <p key={'n' + i} className="text-xs text-text-secondary leading-5">📰 {it.title}</p>
                    ))}
                    {(data.research || []).slice(0, 3).map((it, i) => (
                      <p key={'r' + i} className="text-xs text-text-secondary leading-5">📄 {it.title}{it.org ? '（' + it.org + '）' : ''}{it.rating ? ' · ' + it.rating : ''}</p>
                    ))}
                  </div>
                )}
              </Card>

              {/* AI 点评 */}
              <Card>
                <div className="flex items-center gap-2 mb-2">
                  <h2 className="font-bold text-sm">AI 综合点评</h2>
                  {!aiText && !aiLoading && (
                    <Button size="sm" onClick={() => void askAi()} disabled={aiLoading}>{aiLoading ? '生成中（约 10~30 秒）...' : '生成 AI 点评'}</Button>
                  )}
                </div>
                {aiError && <p className="text-xs text-danger mb-1">{aiError}</p>}
                {aiLoading && !aiText && <Loading className="py-3" />}
                {aiText && (
                  <div className="rounded border-l-2 border-primary-200 pl-3 space-y-0.5">
                    {renderMd(aiText, 'ai')}
                    <p className="text-xs text-danger/80 mt-2">⚠ 本点评由 AI 基于公开行情与资讯自动生成，仅供参考，不构成任何投资建议。</p>
                  </div>
                )}
                {!aiText && !aiLoading && (
                  <p className="text-xs text-text-muted">点击生成：AI 将结合 位置/技术/估值/消息面 给出综合观点与风险提示。</p>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
