import PagePlaceholder from '../components/PagePlaceholder';

export default function Tracking() {
  return <PagePlaceholder title="追踪管理" description="最多 10 只股票的实时异动监控与分级通知。" features={['价格急涨急跌/放量/大单/技术信号', '紧急/关注/提示三级通知', '同一异动 15 分钟频率控制']} />;
}
