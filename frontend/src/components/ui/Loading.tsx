// 加载态：旋转指示器 + 文案（全页面统一）
export default function Loading({ text = '加载中...', className = '' }: { text?: string; className?: string }) {
  return (
    <div className={`flex items-center justify-center gap-2 py-6 text-sm text-text-muted ${className}`}>
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-primary-100 border-t-primary-500" />
      <span>{text}</span>
    </div>
  );
}
