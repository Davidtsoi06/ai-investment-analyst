// 指标小卡片：标签 + 数值（数字字体），全页面统一
export default function Stat({ label, value, cls = '' }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-bg-secondary rounded px-3 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className={`mt-0.5 font-number text-sm ${cls}`}>{value}</div>
    </div>
  );
}
