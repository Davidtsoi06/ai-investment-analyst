import { useEffect, useState } from 'react';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import {
  getSettings, saveSettings, saveAiKey, testAiKey, getBackendStatus,
  type Settings as SettingsType,
} from '../services/api';

const MARKET_OPTIONS = ['A股', '港股', '美股'];
const NOTIFY_ITEMS: [string, string][] = [
  ['premarket', '盘前资讯'],
  ['alert', '异动提醒'],
  ['summary', '盘后总结'],
  ['recommendation', '推荐推送'],
  ['risk', '风险预警'],
  ['review', '复盘报告'],
];

export default function Settings() {
  const [markets, setMarkets] = useState<string[]>(['A股', '港股']);
  const [notifications, setNotifications] = useState<Record<string, boolean>>({});
  const [quietHours, setQuietHours] = useState({ enabled: true, start: '23:00', end: '07:00', urgent_exempt: true });
  const [aiConfigured, setAiConfigured] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [aiMsg, setAiMsg] = useState('');
  const [backendStatus, setBackendStatus] = useState<{ running: boolean; version: string | null } | null>(null);
  const [savedMsg, setSavedMsg] = useState('');

  useEffect(() => {
    getBackendStatus().then(setBackendStatus).catch(() => null);
    getSettings().then((res) => {
      if (res.ok && res.data) {
        const s = res.data as SettingsType;
        setMarkets(s.markets || ['A股', '港股']);
        setNotifications(s.notifications || {});
        setQuietHours(s.quiet_hours || quietHours);
        setAiConfigured(s.ai_configured);
      }
    });
  }, []);

  const toggleMarket = (m: string) =>
    setMarkets((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]));

  const save = async () => {
    const res = await saveSettings({ markets, notifications, quiet_hours: quietHours });
    setSavedMsg(res.ok ? '已保存 ✅' : `保存失败：${res.error}`);
    setTimeout(() => setSavedMsg(''), 3000);
  };

  const saveKey = async () => {
    if (!apiKey.trim()) return setAiMsg('请输入 API Key');
    const r = await saveAiKey(apiKey.trim());
    if (r.ok) { setAiConfigured(true); setAiMsg('已保存（加密存储）'); setApiKey(''); }
    else setAiMsg(`保存失败：${r.error}`);
  };

  const testKey = async () => {
    setAiMsg('测试中...');
    const r = await testAiKey(apiKey.trim() || undefined);
    setAiMsg(r.ok ? `连接成功 ✅（可用模型：${(r.data as { models?: string[] }).models?.join(', ')}）` : `连接失败：${(r.data as { error?: string }).error}`);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold text-primary-900">系统设置</h1>
        {savedMsg && <span className="text-sm text-success">{savedMsg}</span>}
      </div>

      <Card>
        <div className="flex items-center gap-3 mb-3">
          <h2 className="font-bold text-sm">交易市场</h2>
          <span className="text-xs text-text-muted">决定推荐范围与轮询开关</span>
        </div>
        <div className="flex gap-3">
          {MARKET_OPTIONS.map((m) => (
            <button key={m} onClick={() => toggleMarket(m)}
              className={`px-4 py-2 rounded-lg border text-sm ${markets.includes(m) ? 'border-primary-500 bg-primary-50 text-primary-700 font-medium' : 'border-border'}`}>
              {markets.includes(m) ? '☑' : '☐'} {m}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="font-bold text-sm mb-3">通知设置</h2>
        <div className="grid grid-cols-2 gap-2">
          {NOTIFY_ITEMS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={!!notifications[k]} onChange={() => setNotifications({ ...notifications, [k]: !notifications[k] })} className="accent-primary-500" />
              {label}
            </label>
          ))}
        </div>
        <div className="mt-4 pt-3 border-t border-border space-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={quietHours.enabled} onChange={() => setQuietHours({ ...quietHours, enabled: !quietHours.enabled })} className="accent-primary-500" />
            免打扰时段
          </label>
          <div className="flex items-center gap-2 ml-6">
            <input type="time" value={quietHours.start} onChange={(e) => setQuietHours({ ...quietHours, start: e.target.value })} className="border border-border rounded px-2 py-1 text-sm" />
            <span>至</span>
            <input type="time" value={quietHours.end} onChange={(e) => setQuietHours({ ...quietHours, end: e.target.value })} className="border border-border rounded px-2 py-1 text-sm" />
          </div>
          <label className="flex items-center gap-2 ml-6">
            <input type="checkbox" checked={quietHours.urgent_exempt} onChange={() => setQuietHours({ ...quietHours, urgent_exempt: !quietHours.urgent_exempt })} className="accent-primary-500" />
            紧急异动不受免打扰限制
          </label>
        </div>
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-3">
          <h2 className="font-bold text-sm">DeepSeek AI 配置</h2>
          {aiConfigured ? <Badge variant="success">已配置</Badge> : <Badge variant="warning">未配置</Badge>}
        </div>
        <p className="text-xs text-text-muted mb-3">在 platform.deepseek.com 申请 API Key；密钥本地加密存储，绝不上传。</p>
        <div className="flex gap-2">
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." className="flex-1 border border-border rounded px-3 py-2 text-sm" />
          <Button size="sm" onClick={saveKey}>保存</Button>
          <Button size="sm" variant="secondary" onClick={testKey}>测试连接</Button>
        </div>
        {aiMsg && <p className="text-xs text-text-secondary mt-2">{aiMsg}</p>}
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-3">
          <h2 className="font-bold text-sm">后端服务</h2>
          {backendStatus ? (backendStatus.running ? <Badge variant="success">运行中 v{backendStatus.version}</Badge> : <Badge variant="danger">未连接</Badge>) : <Badge>检测中...</Badge>}
        </div>
      </Card>

      <div className="flex justify-end">
        <Button onClick={save}>保存设置</Button>
      </div>

      <Card>
        <h2 className="font-bold mb-2 text-sm">关于</h2>
        <p className="text-xs text-text-secondary">AI 投资分析软件 v0.4.0 · 本地运行 · 数据安全 · 投资建议仅供参考</p>
      </Card>
    </div>
  );
}
