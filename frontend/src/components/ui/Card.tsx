import type { ReactNode } from 'react';

export default function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`bg-surface rounded-lg shadow-sm p-4 ${className}`}>{children}</div>;
}
