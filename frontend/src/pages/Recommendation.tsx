import PagePlaceholder from '../components/PagePlaceholder';

export default function Recommendation() {
  return <PagePlaceholder title="推荐中心" description="AI 每日生成短线与长线推荐，含约束规则与回测统计。" features={['短线推荐（入场区间/止损/目标价/置信度）', '长线推荐（估值区间/风险等级/逻辑）', '推荐准确率回测报告']} />;
}
