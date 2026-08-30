import PagePlaceholder from '../components/PagePlaceholder';
import Card from '../components/ui/Card';

export default function Settings() {
  const info = window.appInfo?.versions;
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
