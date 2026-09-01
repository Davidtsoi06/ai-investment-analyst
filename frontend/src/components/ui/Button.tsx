import type { ReactNode, ButtonHTMLAttributes } from 'react';

type Variant = 'primary' | 'secondary' | 'danger';

const styles: Record<Variant, string> = {
  primary: 'bg-primary-500 text-white hover:bg-primary-700',
  secondary: 'bg-white text-primary-500 border border-primary-500 hover:bg-primary-50',
  danger: 'bg-danger text-white hover:opacity-80',
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: 'sm' | 'md';
  children: ReactNode;
}

export default function Button({ variant = 'primary', size = 'md', children, className = '', ...rest }: Props) {
  const sizeCls = size === 'sm' ? 'h-8 px-3 text-xs' : 'h-10 px-4 text-sm';
  return (
    <button className={`rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${styles[variant]} ${sizeCls} ${className}`} {...rest}>
      {children}
    </button>
  );
}