// 金额显示：正值绿色（+）、负值红色（-）、币种符号在前，数字字体
export default function Amount({ value, currency = '¥' }: { value: number; currency?: string }) {
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  const cls = value > 0 ? 'text-success' : value < 0 ? 'text-danger' : 'text-text';
  return (
    <span className={`font-number ${cls}`}>
      {sign}{currency}{Math.abs(value).toFixed(2)}
    </span>
  );
}
