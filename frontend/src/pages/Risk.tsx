import PagePlaceholder from '../components/PagePlaceholder';

export default function Risk() {
  return <PagePlaceholder title="风险分析" description="组合风险指标计算与压力测试模拟。" features={['集中度/最大回撤/Beta/夏普/VaR', '大盘跌 10%/板块跌 20% 等压力场景', '超限预警通知']} />;
}
