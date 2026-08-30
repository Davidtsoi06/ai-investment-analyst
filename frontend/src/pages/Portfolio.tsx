import PagePlaceholder from '../components/PagePlaceholder';

export default function Portfolio() {
  return <PagePlaceholder title="持仓总览" description="与个人理财软件 finance.db 只读对接的持仓与资产总览。" features={['持仓明细（数量/成本/现价/盈亏）', '资产配置与净值走势', '每小时自动同步 + 手动刷新']} />;
}
