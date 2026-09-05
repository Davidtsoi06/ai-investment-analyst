import { useEffect, useState } from 'react';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import {
  api, getSettings, saveSettings, saveAiKey, testAiKey, getBackendStatus, getProfile, saveProfile,
  getAiStatus, parseApiError,
  type AiStatus,
  type Profile as ProfileType,
  type Settings as SettingsType,
} from '../services/api';

const MARKET_OPTIONS = ['A股', '港股', '美股'];
const NOTIFY_ITEMS: [string, string][] = [
  ['premarket', '盘前资讯'],
  ['alert', '异动提醒'],
  ['summary', '收盘报告'],
  ['recommendation', '推荐推送'],
  ['risk', '风险预警'],
  ['review', '复盘报告'],
];

export default function Settings() {
  const [markets, setMarkets] = useState<string[]>(['A股', '港股']);
  const [notifications, setNotifications] = useState<Record<string, boolean>>({});
  const [quietHours, setQuietHours] = useState({ enabled: true, start: '23:00', end: '07:00', urgent_exempt: true });
  const [aiConfigured, setAiConfigured] = useState(false);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [aiMsg, setAiMsg] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [backendStatus, setBackendStatus] = useState<{ running: boolean; version: string | null } | null>(null);
  const [savedMsg, setSavedMsg] = useState('');
  // 版本更新状态（对齐理财软件）
  const [updVersion, setUpdVersion] = useState('');
  const [updPhase, setUpdPhase] = useState<'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'error'>('idle');
  const [updLatest, setUpdLatest] = useState('');
  const [updPercent, setUpdPercent] = useState(0);
  const [updMsg, setUpdMsg] = useState('');
  const [updError, setUpdError] = useState('');
  // 投资风格（画像，PUT /api/profile）
  const [profile, setProfile] = useState<Partial<ProfileType>>({});
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMsg, setProfileMsg] = useState('');
  // 持仓数据来源模式（手动录入 / 快照文件）
  const [pfMode, setPfMode] = useState<string>('snapshot');
  const [pfLoadedMode, setPfLoadedMode] = useState<string | null>(null);
  const [pfStatus, setPfStatus] = useState<{ snapshot_detected?: boolean; snapshot_dir?: string | null; snapshot_modified_at?: string | null } | null>(null);

  useEffect(() => {
    if (!window.updater) return;
    window.updater.getVersion().then((v) => { if (v?.version) setUpdVersion(v.version); }).catch(() => {});
    const off = window.updater.onStatus((data) => {
      switch (data.event) {
        case 'checking-for-update': setUpdPhase('checking'); setUpdError(''); break;
        case 'update-available': setUpdPhase('available'); setUpdLatest(String(data.version || '')); break;
        case 'update-not-available': setUpdPhase('idle'); setUpdMsg('已是最新版本'); break;
        case 'download-progress': setUpdPhase('downloading'); setUpdPercent(Number(data.percent) || 0); break;
        case 'update-downloaded': setUpdPhase('downloaded'); setUpdLatest(String(data.version || updLatest)); break;
        case 'update-error': setUpdPhase('error'); setUpdError(String((data as { message?: string }).message || '更新出错')); break;
      }
    });
    return () => { off(); };
  }, []);

  const checkUpdate = async () => {
    if (!window.updater) return;
    setUpdPhase('checking'); setUpdMsg(''); setUpdError('');
    const r = await window.updater.check();
    if (!r.updateAvailable) { setUpdPhase('idle'); setUpdMsg(r.message || (r.error ? '检查失败：' + r.error : '已是最新版本')); if (r.error) setUpdError(r.error); }
    else { setUpdPhase('available'); setUpdLatest(r.latestVersion || ''); }
  };
  const downloadUpdate = async () => {
    if (!window.updater) return;
    setUpdPhase('downloading'); setUpdError('');
    const r = await window.updater.download();
    if (!r.success) { setUpdPhase('error'); setUpdError(r.error || '下载失败'); }
  };
  const installUpdate = () => { window.updater?.install(); };
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getBackendStatus().then(setBackendStatus).catch(() => null);
    getAiStatus().then((r) => { if (r.ok && r.data) setAiStatus(r.data as AiStatus); }).catch(() => {});
    getProfile().then((r) => { if (r.ok && r.data) setProfile(r.data as ProfileType); }).catch(() => {});
    api<{ portfolio_dir?: string; data_dir?: string }>('GET', '/api/system/info').then((r) => {
      if (r.ok && r.data?.portfolio_dir) {
        const el = document.getElementById('portfolio-dir');
        if (el) el.textContent = r.data.portfolio_dir;
      }
    }).catch(() => {});
    api<{ mode?: string; snapshot_detected?: boolean; snapshot_dir?: string | null; snapshot_modified_at?: string | null }>('GET', '/api/portfolio/status').then((r) => {
      if (r.ok && r.data) {
        if (r.data.mode) { setPfMode(r.data.mode); setPfLoadedMode(r.data.mode); }
        setPfStatus(r.data);
      }
    }).catch(() => {});
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
    setSaving(true);
    const res = await saveSettings({ markets, notifications, quiet_hours: quietHours });
    let ok = res.ok;
    // 持仓数据来源模式变化 → 单独保存
    if (ok && pfLoadedMode !== null && pfMode !== pfLoadedMode) {
      const mr = await api<{ ok?: boolean; reason?: string }>('PUT', '/api/portfolio/mode', { mode: pfMode });
      ok = mr.ok && (mr.data as { ok?: boolean } | undefined)?.ok !== false;
      if (ok) setPfLoadedMode(pfMode);
    }
    setSaving(false);
    setSavedMsg(ok ? '已保存 ✅' : `保存失败：${parseApiError(res.error)}`);
    setTimeout(() => setSavedMsg(''), 3000);
  };

  /** 保存并测试（照搬理财软件交互）：先加密落库 → 立即用真实接口验证 → 显示具体结果/原因 */
  const saveAndTestKey = async () => {
    const key = apiKey.trim();
    if (!key) return setAiMsg('请输入 API Key（以 sk- 开头）');
    setAiBusy(true);
    setAiMsg('正在保存并测试连接...');
    const sv = await saveAiKey(key);
    if (!sv.ok) {
      setAiBusy(false);
      setAiMsg('保存失败：' + parseApiError(sv.error));
      return;
    }
    const r = await testAiKey(); // 后端读取刚保存的 Key（实时解密）测试真实接口
    setAiBusy(false);
    const err = (r.data as { error?: string })?.error || r.error || '未知错误';
    if (r.ok) {
      setAiMsg('已保存并测试通过 ✅（可用模型：' + ((r.data as { models?: string[] }).models?.join(', ') || '—') + '）');
      setApiKey('');
    } else {
      setAiMsg('已保存，但测试未通过 ❌：' + err + '（Key 已加密保存，可重试或更换）');
    }
    const st = await getAiStatus();
    if (st.ok && st.data) setAiStatus(st.data as AiStatus);
  };

  const saveProfileInfo = async () => {
    setProfileSaving(true);
    setProfileMsg('');
    const r = await saveProfile({
      risk_tolerance: String(profile.risk_tolerance ?? '稳健型'),
      invest_amount: String(profile.invest_amount ?? '10-50万'),
      holding_period: String(profile.holding_period ?? '数天~数周'),
      experience: String(profile.experience ?? '有经验'),
    });
    setProfileSaving(false);
    setProfileMsg(r.ok ? '投资风格已保存 ✅' : `保存失败：${parseApiError(r.error)}`);
    setTimeout(() => setProfileMsg(''), 3000);
  };

  /** 打开 DeepSeek Key 申请页（桌面端经主进程 shell.openExternal；浏览器直接新窗口） */
  const openKeyPage = () => {
    const url = 'https://platform.deepseek.com/api_keys';
    if (window.app?.openExternal) {
      void window.app.openExternal(url);
    } else {
      window.open(url, '_blank');
    }
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
            <input type="time" value={quietHours.start} onChange={(e) => setQuietHours({ ...quietHours, start: e.target.value })} className="rounded border border-border px-2 py-1 text-sm outline-none focus:border-primary-500" />
            <span>至</span>
            <input type="time" value={quietHours.end} onChange={(e) => setQuietHours({ ...quietHours, end: e.target.value })} className="rounded border border-border px-2 py-1 text-sm outline-none focus:border-primary-500" />
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
          {aiStatus?.configured ? (
            <Badge variant="success">已配置（sk-****{aiStatus.key_tail || '••••'}）</Badge>
          ) : aiConfigured ? (
            <Badge variant="success">已配置</Badge>
          ) : (
            <Badge variant="warning">未配置</Badge>
          )}
        </div>
        <p className="text-xs text-text-muted mb-3">
          在 <button className="text-primary-600 underline" onClick={openKeyPage}>platform.deepseek.com/api_keys</button> 申请
          API Key；密钥本地加密存储，绝不上传。
        </p>
        {/* 状态异常提示（不再黑盒：解密失败 / 最近调用错误都可见） */}
        {!aiStatus?.configured && aiStatus?.crypto_error && (
          <div className="mb-3 rounded border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger">
            ⚠ {aiStatus.crypto_error} —— 请在下框重新填写 API Key 并「保存并测试」。
          </div>
        )}
        {!aiStatus?.configured && !aiStatus?.crypto_error && aiStatus?.last_error && (
          <div className="mb-3 rounded border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning">
            ⚠ 最近一次 AI 调用失败（{aiStatus.last_error_at || ''}）：{aiStatus.last_error}
          </div>
        )}
        {aiStatus?.configured && aiStatus?.last_error && (
          <div className="mb-3 rounded border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-warning">
            ⚠ 最近一次 AI 调用异常（{aiStatus.last_error_at || ''}）：{aiStatus.last_error}
            <span className="text-text-muted">（若刚保存新 Key 会自动清除；持续出现请重试）</span>
          </div>
        )}
        <div className="flex gap-2">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void saveAndTestKey(); }}
            placeholder={aiStatus?.configured ? '已保存 Key（sk-****' + (aiStatus.key_tail || '') + '），如需更换请输入新 Key' : 'sk-...'}
            className="flex-1 rounded border border-border px-3 py-2 text-sm outline-none focus:border-primary-500"
          />
          <Button size="sm" onClick={saveAndTestKey} disabled={aiBusy || !apiKey.trim()}>
            {aiBusy ? '保存并测试中...' : '保存并测试'}
          </Button>
        </div>
        <p className="text-xs text-text-muted mt-2">保存后立即用真实接口验证；连接失败会显示具体原因（如 401 Key 无效 / 402 余额不足 / 网络错误）。</p>
        {aiMsg && <p className="text-xs text-text-secondary mt-2 whitespace-pre-wrap">{aiMsg}</p>}
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-1">
          <h2 className="font-bold text-sm">投资风格</h2>
          <span className="text-xs text-text-muted">影响推荐范围与风险控制（与引导问卷一致，随时可改）</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4 pt-2">
          <div>
            <div className="text-xs text-text-secondary mb-1.5">风险偏好</div>
            <div className="flex flex-wrap gap-2">
              {['保守型', '稳健型', '激进型'].map((o) => (
                <button key={o} onClick={() => setProfile({ ...profile, risk_tolerance: o })}
                  className={'px-3 py-1.5 rounded-lg border text-sm ' + (profile.risk_tolerance === o ? 'border-primary-500 bg-primary-50 text-primary-700 font-medium' : 'border-border')}>
                  {o}
                </button>
              ))}
            </div>
            <p className="text-xs text-text-muted mt-1.5">
              {profile.risk_tolerance === '保守型' && '优先本金安全：以低波动/高股息标的为主，严格控制仓位。'}
              {profile.risk_tolerance === '稳健型' && '攻守平衡：长短线结合，设置止损纪律，避免单只集中度过高。'}
              {profile.risk_tolerance === '激进型' && '追求高弹性：可承受较大波动，短线机会优先，务必严格执行止损。'}
            </p>
          </div>
          <div className="space-y-3">
            <div>
              <div className="text-xs text-text-secondary mb-1">可投资金额</div>
              <select value={profile.invest_amount || '10-50万'} onChange={(e) => setProfile({ ...profile, invest_amount: e.target.value })}
                className="rounded border border-border px-2 py-1.5 text-sm bg-white focus:border-primary-500 outline-none w-40">
                {['10万以下', '10-50万', '50-100万', '100万以上'].map((o) => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div className="flex flex-wrap gap-x-8 gap-y-3">
              <div>
                <div className="text-xs text-text-secondary mb-1">持仓周期</div>
                <select value={profile.holding_period || '数天~数周'} onChange={(e) => setProfile({ ...profile, holding_period: e.target.value })}
                  className="rounded border border-border px-2 py-1.5 text-sm bg-white focus:border-primary-500 outline-none w-36">
                  {['日内交易', '数天~数周', '数月以上'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div>
                <div className="text-xs text-text-secondary mb-1">投资经验</div>
                <select value={profile.experience || '有经验'} onChange={(e) => setProfile({ ...profile, experience: e.target.value })}
                  className="rounded border border-border px-2 py-1.5 text-sm bg-white focus:border-primary-500 outline-none w-28">
                  {['新手', '有经验', '资深'].map((o) => <option key={o}>{o}</option>)}
                </select>
              </div>
            </div>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button size="sm" onClick={saveProfileInfo} disabled={profileSaving}>
            {profileSaving ? '保存中...' : '保存投资风格'}
          </Button>
          {profileMsg && <span className="text-xs text-success">{profileMsg}</span>}
        </div>
      </Card>

      <Card>
        <div className="flex items-center gap-3 mb-3">
          <h2 className="font-bold text-sm">后端服务</h2>
          {backendStatus ? (backendStatus.running ? <Badge variant="success">运行中 v{backendStatus.version}</Badge> : <Badge variant="danger">未连接</Badge>) : <Badge>检测中...</Badge>}
        </div>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <h2 className="font-bold text-sm">持仓数据来源</h2>
          <span className="text-xs text-text-muted">决定持仓如何进入本软件（推荐 / 风险 / 复盘均按当前来源计算）</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <button
            onClick={() => setPfMode('snapshot')}
            className={'rounded-lg border p-3 text-left text-sm transition ' + (pfMode === 'snapshot' ? 'border-primary-500 bg-primary-50' : 'border-border hover:border-primary-300')}
          >
            <div className={'font-medium ' + (pfMode === 'snapshot' ? 'text-primary-700' : 'text-primary-900')}>
              {pfMode === 'snapshot' ? '☑' : '☐'} 快照文件（推荐）
            </div>
            <p className="text-xs text-text-secondary mt-1 leading-5">
              读取「个人理财投资软件」v1.10.15+ 自动导出的 portfolio_snapshot.json，含持仓/账户/交易/净值，每小时自动同步，无需重复录入。
            </p>
          </button>
          <button
            onClick={() => setPfMode('manual')}
            className={'rounded-lg border p-3 text-left text-sm transition ' + (pfMode === 'manual' ? 'border-primary-500 bg-primary-50' : 'border-border hover:border-primary-300')}
          >
            <div className={'font-medium ' + (pfMode === 'manual' ? 'text-primary-700' : 'text-primary-900')}>
              {pfMode === 'manual' ? '☑' : '☐'} 手动录入
            </div>
            <p className="text-xs text-text-secondary mt-1 leading-5">
              不使用理财软件，在「持仓总览」页直接录入代码/数量/成本价自行管理。
            </p>
          </button>
        </div>
        {pfMode === 'snapshot' ? (
          <div className="mt-3 rounded border border-border bg-bg-secondary/60 px-3 py-2">
            <p className="text-xs text-text-secondary leading-5">
              快照目录：<span className="font-mono" id="portfolio-dir">读取中...</span>
            </p>
            <p className="text-xs text-text-muted mt-1">
              请将「个人理财投资软件」设置 → AI 配置 → 导出文件夹，指向以上目录，并在理财软件中导出一次持仓快照。
              {pfStatus && pfStatus.snapshot_detected
                ? '（已检测到快照文件，更新于 ' + (pfStatus.snapshot_modified_at || '—') + '）'
                : '（当前尚未检测到快照文件）'}
            </p>
          </div>
        ) : (
          <p className="text-xs text-warning mt-2">切换为手动录入后，此前同步的持仓将被清理（可随时切回并重新同步）。</p>
        )}
        <p className="text-xs text-text-muted mt-2">数据库与日志存储于数据目录（%APPDATA%\ai-investment-analyst\data），请勿删除。</p>
      </Card>

      <div className="flex justify-end">
        <Button onClick={save} disabled={saving}>{saving ? '保存中...' : '保存设置'}</Button>
      </div>

      <Card>
        <div className="flex items-center gap-3 mb-3">
          <h2 className="font-bold text-sm">版本更新</h2>
          {updVersion && <Badge variant="info">当前 v{updVersion}</Badge>}
        </div>
        {!window.updater ? (
          <p className="text-xs text-text-muted">更新功能仅在安装版（正式安装包）中可用，开发模式不生效。</p>
        ) : updPhase === 'checking' ? (
          <p className="text-sm text-text-secondary">正在检查更新...</p>
        ) : updPhase === 'available' ? (
          <div className="space-y-2">
            <p className="text-sm">发现新版本 <span className="font-bold text-primary-700">v{updLatest}</span></p>
            <Button size="sm" onClick={downloadUpdate}>下载更新</Button>
            {updError && <p className="text-xs text-danger">{updError}</p>}
          </div>
        ) : updPhase === 'downloading' ? (
          <div>
            <div className="h-2 bg-primary-100 rounded-full overflow-hidden">
              <div className="h-full bg-primary-500 transition-all" style={{ width: updPercent + '%' }} />
            </div>
            <p className="text-xs text-text-secondary mt-1">正在下载更新... {updPercent}%</p>
          </div>
        ) : updPhase === 'downloaded' ? (
          <div className="space-y-2">
            <p className="text-sm text-success">更新已下载完成 ✅</p>
            <Button size="sm" onClick={installUpdate}>重启并安装</Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="secondary" onClick={checkUpdate}>检查更新</Button>
            {updMsg && <span className="text-xs text-text-secondary">{updMsg}</span>}
            {updError && <span className="text-xs text-danger">{updError}</span>}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-bold mb-2 text-sm">关于</h2>
        <p className="text-xs text-text-secondary">AI 投资分析软件 v{updVersion || window.appInfo?.versions?.app || 'dev'} · 本地运行 · 数据安全 · 投资建议仅供参考</p>
      </Card>
    </div>
  );
}