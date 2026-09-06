import { useEffect, useState } from 'react';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Loading from '../components/ui/Loading';
import EmptyState from '../components/ui/EmptyState';
import { api, parseApiError } from '../services/api';

interface NewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  market: string;
  summary: string;
  level: string;
  published_at: string;
  region?: string | null;
  related?: string[];
  holding_related?: boolean;
}

interface Premarket {
  date?: string;
  content?: string;
  fetched?: number;
  saved?: number;
  pushed?: boolean;
  created_at?: string;
}

const LEVEL_BADGE: Record<string, 'danger' | 'warning' | 'default'> = { '重大': 'danger', '中等': 'warning', '一般': 'default' };
const REGION_MARK: Record<string, string> = { '美国': '🇺🇸', '英国': '🇬🇧', '日本': '🇯🇵', '韩国': '🇰🇷' };

/** 打开原文（桌面经系统浏览器；网页新窗口） */
function openUrl(url: string) {
  if (window.app?.openExternal) void window.app.openExternal(url);
  else window.open(url, '_blank', 'noopener');
}

function NewsRow({ it }: { it: NewsItem }) {
  const isOverseas = it.region && it.region !== 'cn';
  const title = it.title || '';
  return (
    <div className="py-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant={LEVEL_BADGE[it.level] || 'default'}>{it.level}</Badge>
        {isOverseas && <span title={'海外源 · ' + it.region}>{REGION_MARK[it.region || ''] || '🌍'} {it.region}</span>}
        <span className="text-xs text-text-muted">{it.source || it.market}</span>
        {Array.isArray(it.related) && it.related.length > 0 && (
          <Badge variant="info">📌 {it.related.slice(0, 3).join('、')}</Badge>
        )}
        {!isOverseas && it.holding_related && <Badge variant="info">持仓相关 ★</Badge>}
        {isOverseas && <span className="text-xs text-text-muted">英文原文 · 标题已译</span>}
        <span className="text-xs text-text-muted ml-auto">{(it.published_at || '').slice(5, 16)}</span>
      </div>
      <div className="text-sm font-medium text-text mt-1">{title}</div>
      {it.summary && <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{it.summary}</p>}
      <button onClick={() => openUrl(it.url)} className="text-xs text-primary-600 hover:text-primary-700 mt-1">
        {isOverseas ? '查看原文（原网站）↗' : '查看原文 ↗'}
      </button>
    </div>
  );
}

function NewsSection({ title, items, icon, emptyText }: { title: string; items: NewsItem[]; icon: string; emptyText: string }) {
  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <h2 className="font-bold text-sm">{icon} {title}</h2>
        {items.length > 0 && <span className="text-xs text-text-muted">{items.length} 条</span>}
      </div>
      {items.length === 0 ? (
        <EmptyState icon={icon} title="暂无内容" description={emptyText} className="py-6" />
      ) : (
        <div className="divide-y divide-border">
          {items.slice(0, 20).map((it) => <NewsRow key={it.id} it={it} />)}
        </div>
      )}
    </Card>
  );
}

export default function News() {
  const [premarket, setPremarket] = useState<Premarket | null>(null);
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const load = async () => {
    setLoadingList(true);
    const [p, l] = await Promise.all([
      api<Premarket>('GET', '/api/news/premarket/today'),
      api<NewsItem[]>('GET', '/api/news/latest?limit=60'),
    ]);
    setLoadingList(false);
    if (p.ok) setPremarket(p.data as Premarket);
    if (l.ok) setItems((l.data as NewsItem[]) || []);
  };

  useEffect(() => { load(); }, []);

  // 分区：池相关（related/持仓）> 海外 > 全市场中文
  const poolItems = items.filter((it) => (Array.isArray(it.related) && it.related.length > 0) || it.holding_related);
  const overseas = items.filter((it) => it.region && it.region !== 'cn' && !poolItems.includes(it));
  const market = items.filter((it) => (!it.region || it.region === 'cn') && !poolItems.includes(it));

  const refresh = async () => {
    setLoading(true);
    setMsg({ type: 'ok', text: '正在抓取中文源（约 3~10 秒），随后抓取海外源（美/英/日/韩）...' });
    const r = await api<{ ok: boolean; fetched?: number; saved?: number; reason?: string }>('POST', '/api/news/premarket/run');
    const cnMsg = r.ok && r.data?.ok ? `中文源整合完成：抓取 ${r.data.fetched} 条 / 新增 ${r.data.saved} 条` : ('中文源失败：' + (r.data?.reason || parseApiError(r.error)));
    setMsg({ type: 'ok', text: cnMsg + '；海外源抓取中...' });
    const o = await api<{ fetched?: number; saved?: number; failed_sources?: string[] }>('POST', '/api/news/fetch-overseas');
    const fail = (o.data?.failed_sources || []).length ? '（不可达：' + (o.data?.failed_sources || []).join('、') + '）' : '';
    setMsg({
      type: (r.ok && r.data?.ok) || o.ok ? 'ok' : 'err',
      text: cnMsg + (o.ok ? `；海外源新增 ${o.data?.saved ?? 0} 条${fail}` : '；海外源抓取失败'),
    });
    await load();
    setLoading(false);
    setTimeout(() => setMsg(null), 6000);
  };

  const renderPremarket = (content: string) =>
    content.split('\n').map((line, i) => {
      let cls = 'text-text-secondary';
      if (line.startsWith('📰') || line.includes('━━')) cls = 'font-bold text-primary-900';
      else if (line.startsWith('🔴')) cls = 'text-danger';
      else if (line.startsWith('🟡')) cls = 'text-warning';
      else if (line.startsWith('🟢')) cls = 'text-success';
      return <p key={i} className={`text-sm leading-6 ${cls}`}>{line}</p>;
    });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-primary-900">资讯看板</h1>
          {premarket?.pushed && <Badge variant="success">已推送</Badge>}
        </div>
        <Button size="sm" onClick={refresh} disabled={loading}>
          {loading ? '抓取整合中（约 10~30 秒）...' : '抓取最新资讯'}
        </Button>
      </div>
      {msg && <p className={`text-sm ${msg.type === 'ok' ? 'text-success' : 'text-danger'}`}>{msg.text}</p>}

      <Card>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="font-bold text-sm">今日盘前资讯</h2>
          {premarket?.date && <span className="text-xs text-text-muted">{premarket.date}{premarket.fetched ? ` · 抓取 ${premarket.fetched} 条` : ''}</span>}
        </div>
        {premarket?.content ? renderPremarket(premarket.content) : (
          <EmptyState icon="📰" title="今日尚无盘前资讯" description="点击右上角「抓取最新资讯」获取今日盘前整合内容。" className="py-6" />
        )}
      </Card>

      {loadingList && items.length === 0 ? (
        <Loading />
      ) : (
        <>
          <NewsSection icon="📌" title="我的股票池相关" items={poolItems}
            emptyText="暂无与您持仓/股票池相关的资讯——在「我的股票池」添加观察股后，相关新闻会优先展示在这里。" />
          <NewsSection icon="🌍" title="海外市场（自动翻译为中文标题，点击查看原网站）" items={overseas}
            emptyText="海外源暂未抓到内容（可点右上角「抓取最新资讯」；英国/日本源视网络可达性而定）。" />
          <NewsSection icon="🗞️" title="全市场要闻（AI 分级）" items={market} emptyText="可点击右上角「抓取最新资讯」手动抓取整合。" />
        </>
      )}
    </div>
  );
}
