# Python Automation Toolkit

> 个人Python自动化工具集 — 涵盖网页数据抓取、文件批处理、定时任务等实用场景。

## 📦 模块概览

| 模块 | 功能 | 核心技术 |
|:---|:---|:---|
| **pixiv_downloader** | Pixiv图片批量下载、标签翻译、按作者分类整理 | requests, JSON API, 多线程 |
| **pixiv_novel** | Pixiv小说下载、按标签筛选、收藏阈值过滤 | requests, HTML解析 |
| **daily_checkin** | 每日自动签到（多平台聚合API + QQ客户端自动化） | requests, OCR, 鼠标控制 |
| **tag_excel_generator** | 标签分类Excel自动生成（全量/样本） | openpyxl, pandas |
| **novel_tools** | TXT小说按章节分割为独立文件 | 正则, 文件IO |
| **feishu_tools** | 飞书/Lark CLI工具封装 | subprocess, API |
| **daily_summary** | 对话/日志每日摘要生成 | LLM API, 文本处理 |

## 🚀 快速开始

```bash
git clone https://github.com/Hhh12138-Hhh/python-automation-toolkit.git
cd python-automation-toolkit

# 安装依赖（按需）
pip install requests pillow openpyxl pandas

# 运行各模块
cd pixiv_downloader && python Pixiv一键下载.py
cd daily_checkin && python daily_checkin.py
```

## 🛠️ 使用场景

- **Pixiv下载器** — 按作者/标签批量下载画作，自动翻译标签、按作者分类整理文件夹
- **小说筛选下载** — 按标签逐页爬取Pixiv小说，黑名单过滤、收藏阈值筛选
- **每日签到** — 基于OCR视觉定位的多平台自动签到，支持Windows定时任务
- **标签Excel** — 从标签数据库生成全量/样本Excel分类对照表
- **章节分割** — 将长篇TXT按"第XXX章"自动分割为独立文件
- **飞书工具** — Python封装的飞书/Lark命令行工具

## 📝 技术亮点

- **AI Agent辅助开发**：多数工具借助 GenericAgent 框架辅助完成需求分析→编码→调试→文档全流程
- **Prompt工程驱动**：复杂功能（标签翻译）通过结构化Prompt + LLM实现智能处理
- **OCR视觉定位**：签到脚本使用OCR + 鼠标精确点击，不依赖键盘快捷键，适应UI变化
- **模块化设计**：核心引擎与入口分离，支持独立使用和Agent调用两种模式

## ⚠️ 注意事项

- Pixiv相关工具需要有效的Cookie/Session
- 部分脚本包含本地绝对路径，使用前请修改配置
- 签到脚本依赖特定平台的API，可能需要更新

## 📄 License

MIT License. Copyright (c) 2026 Hhh12138-Hhh.

---


