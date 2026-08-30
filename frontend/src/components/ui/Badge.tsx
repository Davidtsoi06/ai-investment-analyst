import type { ReactNode } from 'react';

type Variant = 'success' | 'danger' | 'warning' | 'info' | 'default';

const styles: Record<Variant, string> = {
  success: 'bg-success/10 text-success',
  danger: 'bg-danger/10 text-danger',
  warning: 'bg-warning/15 text-warning',
  info: 'bg-info/10 text-info',
  default: 'bg-primary-50 text-primary-700',
};

export default function Badge({ variant = 'default', children }: { variant?: Variant; children: ReactNode }) {
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${styles[variant]}`}>{children}</span>;
}
