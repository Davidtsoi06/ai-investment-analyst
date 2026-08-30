# CLAUDE.md — AI 开发工作指引

本文件是 AI 投资分析软件项目中对 AI 助手（Claude / DeepSeek 等）的工作指引。任何 AI 在项目中工作前，必须先阅读本文件与下文列出的标准文档。

## 项目简介

AI 投资分析软件：面向个人及家庭的 AI 驱动投资分析工具（A 股 + 港股），集资讯聚合、持仓管理、智能推荐、实时追踪、盘后复盘于一体。技术栈：Electron + React/TS + FastAPI + SQLite + DeepSeek API。GitHub 公开仓库（MIT）：ai-investment-analyst。

## 标准文档体系（开工前必读）

| 文件 | 用途 |
|------|------|
| docs/需求文档V1.md | 需求总纲（V1.1，全部决策已确认） |
| docs/开发执行计划.md | 开发步骤 S0~S16 与执行节奏（每次开工先看，确定当前步骤） |
| docs/技术设计规范.md | 架构、进程模型、数据库、代码与安全规范 |
| docs/版本发布规范.md | 版本号、发布流程、README/CHANGELOG 更新、打包、旧安装包清理 |
| docs/开发日志规范.md | 开发日志格式与维护义务 |
| dev-logs/ | 每日开发日志（每天一个文件） |

## 工作流程

1. **开工**：读取 dev-logs/ 最近日志 → 读取 docs/开发执行计划.md 确定当前步骤 → 只做当前步骤，不越界、不一口气做太多。
2. **收工**：更新当日开发日志（完成事项/待办/决策/问题）→ git 提交（约定式提交）→ 向用户汇报 → 等待确认。
3. **发布版本**：严格按 docs/版本发布规范.md 执行：
   - 更新 README.md 与 CHANGELOG.md
   - 打包新安装包
   - 删除旧的安装包（本地构建目录清空 + GitHub Releases 旧资产删除，防止占用存储空间）
   - 打 tag → push → GitHub Actions 自动发布

## 硬性规则

- .env、API Key、密钥**绝不**提交到仓库（.gitignore 强制）。
- 理财软件数据库（finance.db）**只读**，任何写操作都是违规。
- 数据源为免费接口，实现多源冗余与容错；不直接爬取网页 HTML。
- AI 建议仅供参考，README 与应用内需有免责声明。
- 步骤完成即汇报，不擅自跨步骤推进。

## 关联项目

个人理财投资软件（用户自研 Electron 应用）：源码 D:/家/home/个人理财投资软件；数据 C:/Users/用户/AppData/Roaming/personal-finance/finance.db。本软件只读对接其数据，开发中不得修改该项目的任何文件。
