import { useEffect, useState } from 'react';
import PagePlaceholder from '../components/PagePlaceholder';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import { api, getBackendStatus } from '../services/api';

export default function Settings() {
  const info = window.appInfo?.versions;
  const [backendStatus, setBackendStatus] = useState<{ running: boolean; version: string | null; url: string } | null>(null);
  const [testResult, setTestResult] = useState('');

  useEffect(() => {
    getBackendStatus().then(setBackendStatus).catch(() => setBackendStatus({ running: false, version: null, url: '' }));
  }, []);

  const testConnection = async () => {
    setTestResult('请求中...');
    const res = await api<{ status: string; version: string }>('GET', '/api/health');
    setTestResult(res.ok && res.data ? `连接成功：${res.data.status} v${res.data.version}` : `连接失败：${res.error || res.status}`);
  };

  return (
    <div>
      <PagePlaceholder
        title="系统设置"
        description="市场、通知、数据源与 AI 配置。"
        features={[
          '交易市场勾选（A股/港股/美股）',
          '通知开关与免打扰时段',
          'DeepSeek API Key 引导配置',
        ]}
      />
      <Card className="mt-4">
        <div className="flex items-center gap-3 mb-3">
          <h2 className="font-bold text-sm">后端服务</h2>
          {backendStatus ? (
            backendStatus.running ? (<Badge variant="success">运行中 v{backendStatus.version}</Badge>) : (<Badge variant="danger">未连接</Badge>)
          ) : (<Badge>检测中...</Badge>)}
        </div>
        <div className="flex items-center gap-3">
          <Button size="sm" onClick={testConnection}>测试连接</Button>
          {testResult && <span className="text-xs text-text-secondary">{testResult}</span>}
        </div>
      </Card>
      {info && (
        <Card className="mt-4">
          <h2 className="font-bold mb-2 text-sm">关于</h2>
          <p className="text-xs text-text-secondary">
            AI 投资分析软件 v{info.app} · Electron {info.electron} · Chrome {info.chrome} · Node {info.node}
          </p>
        </Card>
      )}
    </div>
  );
}
