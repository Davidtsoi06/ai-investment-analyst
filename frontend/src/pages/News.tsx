import PagePlaceholder from '../components/PagePlaceholder';

export default function News() {
  return <PagePlaceholder title="资讯看板" description="每日盘前资讯聚合推送，AI 分级摘要，持仓关联高亮。" features={['08:00 抓取整合 · 09:00 推送（交易日）', '重大/中等/一般三级分类', '持仓相关资讯置顶 + 跨市场联动标注']} />;
}
