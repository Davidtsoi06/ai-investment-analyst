# 更新日志

本项目的所有重要变更均记录在此文件，格式基于 Keep a Changelog，版本号遵循语义化版本（SemVer）。

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
