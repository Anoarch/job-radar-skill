---
name: job-radar
description: 根据个人求职画像（专业/城市/学历/经验）自动检索公开招录类（政府/人社局/事业单位/国企/高校/医院/公务员公开发布）招聘公告，经 LLM 匹配打分后生成一份中文岗位日报 HTML。触发词：岗位雷达 / 跑岗位日报 / 每日岗位 / 找工作日报 / 生成我的岗位报告 / 帮我找今天的岗位 / job radar。
---

# 岗位雷达 Job Radar

帮助用户根据自己的求职画像，自动检索**公开招录类**招聘公告并生成结构化中文岗位日报。

## 合规铁律（必须严格遵守）
- 只做「公开招录类」：政府/人社局/事业单位/国企/高校/医院/公务员**公开发布**的招聘公告。
- 商业招聘平台（BOSS直聘/智联/猎聘/51job/前程无忧等）一律不碰——其 ToS 禁止爬取 + 不正当竞争判例 + 甚至有刑案风险（巧达科技爬 2 亿简历被查封）。
- 自动批量爬取商业平台 = ToS 违规 + 不正当竞争。人工单页浏览合法，自动化聚合违规。

## 工作流程
1. 读取 `profile.json`（若不存在，提示用户先复制 `profile.example.json` 并填写自己的画像：专业/城市/学历/状态/经验/邮箱）。
2. 运行检索与渲染（`scripts/run_report.py`，位于本 SKILL.md 同级的 `scripts/` 目录）：
   - 用 profile 文件：
     `python <skill根>/scripts/run_report.py --profile <profile.json 路径> --out report`
   - 用户临时口述画像（如「我是临床医学硕士，想看北京」）：
     `python <skill根>/scripts/run_report.py --major 临床医学 --city 北京 --edu 硕士 --status 应届生 --exp 应届 --out report`
3. 若脚本返回 `ERROR: 未配置 DEEPSEEK_API_KEY`：提示用户在环境变量配置 `DEEPSEEK_API_KEY`（DeepSeek 官网免费申请）。`TAVILY_API_KEY` 可选，不填自动用 keyless 零注册免费模式。
4. 把生成的 `report/index.html` 路径返回给用户，并说明：报告页脚已内置抖音 @手残巧匠 二维码，可扫码关注作者。
5. **邮件发送（可选，默认不发）**：若检测到用户已连接 agent-mail（MCP 工具 `mcp__agent-mail__SendMessage` 可用）或配置了 SMTP，询问用户是否把报告发到自己邮箱；默认只生成本地 HTML，不主动发。

## 配置（环境变量）
| 变量 | 必需 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 是 | DeepSeek 官网申请，用于 LLM 匹配打分 |
| `TAVILY_API_KEY` | 否 | Tavily 搜索 API；不填则自动用 keyless 零注册免费模式（rate-limited，适合轻量/别人零配置试用） |
| `JINA_API_KEY` | 否 | Jina 搜索，仅作 Tavily 不可用时的兜底 |

## 每日自动推送（可选）
用户可在 WorkBuddy 里建一个每日自动化（如每天 9:30），prompt 写「运行岗位雷达 skill，用我的 profile.json 生成今日岗位日报」，即可每天自动收到报告。

## 自定义（改成你自己的情况）

本 skill 的所有文件都是你本地的**明文 Python/HTML**，装到 WorkBuddy 后就在 `~/.workbuddy/skills/job-radar/`（或项目级 `.workbuddy/skills/job-radar/`）。作者完全不介入、也收不到你的任何数据或反馈——你改完重跑即可。

| 想改什么 | 改哪里 | 怎么改 |
|---|---|---|
| 求职画像（必改） | `profile.json` | 复制 `profile.example.json` 改成自己的专业/城市/学历/经验/邮箱 |
| 只收最近 N 天的岗位 | 环境变量 `MAX_AGE_DAYS` | 默认 15；想放宽到 30 天，跑前设 `MAX_AGE_DAYS=30`，如 `MAX_AGE_DAYS=30 python scripts/run_report.py --profile profile.json --out report` |
| 加自己的细分行业词 | `scripts/retriever.py` 的 `_build_queries()` | 在对应学科里加一行检索词，如临床医学想额外搜「规培」「专硕」 |
| 每日预算 / 每邮箱份数 | `scripts/config.py` 的 `BUDGET_CNY_PER_DAY` / `FREE_QUOTA_PER_EMAIL_PER_DAY` | 直接改这两个常量（skill 副本里是硬编码，改文件即可） |
| 报告长什么样 | `assets/交付日报模板.html`（纯静态）+ `scripts/build_delivery.py` 的 `CARD_TPL` | 改 CSS 换皮肤，改 `CARD_TPL` 调每张卡片字段 |

> 改完任何文件，重跑 `run_report.py` 即生效；只有改了本 SKILL.md 的触发词才需重启 WorkBuddy。

## 抖音引流（作者署名，不硬广）
- 生成的 HTML 报告页脚自带「抖音 @手残巧匠」文字 + 二维码（引导用户关注作者）。
- 作者抖音号：**@手残巧匠** —— 一个普通人用 AI 手搓小玩意儿，岗位雷达就是第一个。
