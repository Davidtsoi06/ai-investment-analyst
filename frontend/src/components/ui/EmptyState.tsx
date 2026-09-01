import type { ReactNode } from 'react';

// 空态：图标 + 标题 + 说明 + 操作引导（所有列表无数据时统一使用）
interface Props {
  icon?: string;
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export default function EmptyState({ icon = '📭', title = '暂无数据', description, action, className = '' }: Props) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-bg-secondary/50 px-4 py-8 text-center ${className}`}>
      <div className="text-2xl leading-none">{icon}</div>
      <div className="text-sm font-medium text-text-secondary">{title}</div>
      {description && <div className="max-w-md text-xs leading-relaxed text-text-muted">{description}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
