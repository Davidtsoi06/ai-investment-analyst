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

const LEVEL_BADGE: Record<string, 'danger' | 'warning' | 'default'> = {
  '重大': 'danger',
  '中等': 'warning',
  '一般': 'default',
};

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
      api<NewsItem[]>('GET', '/api/news/latest?limit=30'),
    ]);
    setLoadingList(false);
    if (p.ok) setPremarket(p.data as Premarket);
    if (l.ok) setItems((l.data as NewsItem[]) || []);
  };

  useEffect(() => { load(); }, []);

  const refresh = async () => {
    setLoading(true);
    setMsg({ type: 'ok', text: '正在抓取多源资讯（约 3~10 秒）...' });
    const r = await api<{ ok: boolean; fetched?: number; saved?: number }>('POST', '/api/news/premarket/run');
    if (r.ok && r.data?.ok) setMsg({ type: 'ok', text: `整合完成：抓取 ${r.data.fetched} 条 / 新增 ${r.data.saved} 条` });
    else setMsg({ type: 'err', text: '抓取失败：' + ((r.data as { reason?: string })?.reason || parseApiError(r.error)) });
    await load();
    setLoading(false);
    setTimeout(() => setMsg(null), 4000);
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
        <Button size="sm" onClick={refresh} disabled={loading}>{loading ? '整合中...' : '抓取最新资讯'}</Button>
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

      <Card>
        <h2 className="font-bold text-sm mb-3">最新资讯（AI 分级）</h2>
        {loadingList ? (
          <Loading />
        ) : items.length === 0 ? (
          <EmptyState icon="🗞️" title="暂无资讯" description="可点击右上角「抓取最新资讯」手动抓取整合。" />
        ) : null}
        <div className="divide-y divide-border">
          {items.map((it) => (
            <div key={it.id} className="py-2.5">
              <div className="flex items-center gap-2">
                <Badge variant={LEVEL_BADGE[it.level] || 'default'}>{it.level}</Badge>
                <span className="text-xs text-text-muted">{it.market}</span>
                {it.holding_related && <Badge variant="info">持仓相关 ★</Badge>}
                <span className="text-xs text-text-muted ml-auto">{it.published_at}</span>
              </div>
              <a href={it.url} target="_blank" rel="noreferrer" className="block text-sm font-medium text-text mt-1 hover:text-primary-700">{it.title}</a>
              <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{it.summary}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}