import type { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  title: string;
  align?: 'left' | 'right' | 'center';
  render?: (row: T) => ReactNode;
}

export default function Table<T extends { id: string | number }>({ columns, data }: { columns: Column<T>[]; data: T[] }) {
  if (data.length === 0) {
    return <div className="text-center text-text-muted py-8 text-sm">暂无数据</div>;
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="bg-bg-secondary">
          {columns.map((c) => (
            <th key={c.key} className={`px-3 py-2 text-left font-medium text-text-secondary ${c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : ''}`}>
              {c.title}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((row) => (
          <tr key={row.id} className="border-t border-border hover:bg-primary-50">
            {columns.map((c) => (
              <td key={c.key} className={`px-3 py-2 ${c.align === 'right' ? 'text-right font-number' : ''}`}>
                {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? '')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
