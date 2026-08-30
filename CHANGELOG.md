# 更新日志

本项目的所有重要变更均记录在此文件，格式基于 Keep a Changelog，版本号遵循语义化版本（SemVer）。

## [0.1.2] - 2026-08-30

### Added

- 前端骨架（S2）：Vite 8 + React 19 + TypeScript + Tailwind 4，淡蓝色系设计 token（与理财软件风格统一）
- 11 个页面占位（仪表盘/资讯/持仓/推荐/追踪/自选股/报告/风险/复盘/问答/设置），220px 侧边导航布局
- 公共 UI 组件：Card / Button / Badge / Table / Amount
- 前端产物接入 Electron（app-renderer 打包机制）
- 后端骨架（S3）：FastAPI + SQLite（14 张核心表 + 迁移表）+ 健康检查 /api/health + 三类日志
- 发布流程新规则：版本推送前必须经用户明确确认（写入版本发布规范）

## [0.1.1] - 2026-08-30

### Added

- Electron 桌面壳最小化（S1）：主进程、预加载、系统托盘（最小化到托盘/退出菜单）、单实例锁、淡蓝主题窗口
- electron-builder NSIS 安装包打包链路打通（首个可安装版本，输出至 desktop/release/）
- 应用图标（淡蓝柱状图风格，PNG/ICO）
- electron-updater 骨架（自动更新基础配置，待后续版本启用）

## [0.1.0] - 2026-08-30

### Added

- 项目初始化：目录骨架（desktop / frontend / backend / data / docs / dev-logs）
- 需求文档 V1.1：14 项需求决策全部确认（GitHub 公开仓库 + MIT、Electron、A股+港股等）
- 标准文档体系：开发执行计划（S0~S16）、技术设计规范、版本发布规范、开发日志规范
- CLAUDE.md AI 工作指引（标准文件索引 + 工作流程 + 硬性规则）
- 开发日志体系上线（dev-logs/，每天自动记录完成事项与待办）
- GitHub Actions CI 骨架
