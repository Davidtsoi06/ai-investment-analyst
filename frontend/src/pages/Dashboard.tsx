import PagePlaceholder from '../components/PagePlaceholder';

export default function Dashboard() {
  return <PagePlaceholder title="仪表盘" description="资产总览、今日盈亏、市场概览与待办事项聚合的首页。" features={['总资产/今日盈亏/总收益率卡片', '资产配置饼图与持仓明细', '今日市场速览与通知中心']} />;
}
