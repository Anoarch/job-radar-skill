# 岗位雷达 · 通用 Skill（Job Radar Skill）

一个 **WorkBuddy skill**：填好你的求职画像（专业 / 城市 / 学历），它自动检索**公开发布类**招聘公告（政府 / 事业单位 / 国企 / 高校 / 医院 / 公务员），经 AI 匹配打分后生成一份中文岗位日报 HTML。

**合规底线**：只做公开招录类，商业招聘平台（BOSS / 智联 / 猎聘 / 51job 等）一律不碰。

**作者抖音**：[@手残巧匠](https://www.douyin.com) —— 一个普通人用 AI 手搓小玩意儿。报告页脚已内置二维码，欢迎关注。

---

## 一、安装到 WorkBuddy

1. 克隆本仓库：
   ```bash
   git clone https://github.com/Anoarch/job-radar-skill.git
   ```
2. 把 `job-radar-skill/` 整个文件夹复制到 WorkBuddy 的 skills 目录（二选一）：
   - **用户级（所有项目可用）**：`~/.workbuddy/skills/job-radar/`
   - **项目级（仅当前项目）**：`<你的工作区>/.workbuddy/skills/job-radar/`
3. 重启 WorkBuddy 客户端，skill 即生效。对话里说「跑岗位雷达」即可触发。

---

## 二、配置 API Key（环境变量）

| 变量 | 必需 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | **是** | [DeepSeek 官网](https://platform.deepseek.com) 免费申请，用于 AI 匹配打分 |
| `TAVILY_API_KEY` | 否 | [Tavily](https://app.tavily.com) 注册。**不填也能跑**——自动用 keyless 零注册免费模式（rate-limited，适合轻量/试用） |
| `JINA_API_KEY` | 否 | Jina 搜索，仅作 Tavily 不可用时的兜底 |

WorkBuddy 里配置环境变量：设置 → 环境变量，或在该工作区的 `.env` 文件里填。

---

## 三、填写你的画像

复制 `profile.example.json` 为 `profile.json`，改成你自己的：

```json
{
  "专业": "临床医学",
  "城市": "北京",
  "学历": "硕士",
  "状态": "应届生",
  "经验": "应届",
  "邮箱": "you@example.com",
  "备注": "希望能看到更多三甲医院的临床岗"
}
```

---

## 四、运行

对话里直接说：
> 跑岗位雷达，用我的 profile.json 生成今日岗位日报

或命令行：
```bash
python scripts/run_report.py --profile profile.json --out report
# 生成的报告在 report/index.html
```

---

## 五、每天自动推送（可选）

在 WorkBuddy 建一个每日自动化（如每天 9:30），prompt 写：
> 运行岗位雷达 skill，用我的 profile.json 生成今日岗位日报，若已连接邮箱则发到我邮箱。

即可每天自动收到报告。

---

## 六、文件结构

```
job-radar-skill/
  SKILL.md              # skill 入口（触发词 + 指令）
  README.md             # 本文件
  profile.example.json  # 画像模板
  scripts/
    run_report.py       # CLI 入口（检索 + 渲染）
    retriever.py        # 检索 + 打分核心（Tavily 优先 + jina 兜底，两层解耦）
    config.py           # 合规黑名单/白名单 + 配额
    usage_store.py      # 每日预算熔断
    build_delivery.py   # HTML 渲染（纯静态零 JS）
    sample_jobs.py      # 样例回退（默认不启用）
  assets/
    交付日报模板.html    # 报告模板
    douyin-qr.png       # 抖音二维码（引流）
```

---

## 七、免费额度说明

- **Tavily keyless**（默认，零注册）：适合轻量试用，有速率限制。
- **Tavily 免费 key**：注册后 1000 credits/月，无信用卡。
- **DeepSeek**：约 ¥0.03 / 份报告，极便宜。

单份报告消耗已从 ~150k token 降到 ~13k（仅 DeepSeek 输入），因为 Tavily 返回的摘要已足够 AI 打分，不再拉取整篇公告全文。
