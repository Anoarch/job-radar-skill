# 岗位雷达 · 通用 Skill（Job Radar Skill）

一个 **WorkBuddy skill**：填好你的求职画像（专业 / 城市 / 学历），它自动检索**公开发布类**招聘公告（政府 / 事业单位 / 国企 / 高校 / 医院 / 公务员），经 AI 匹配打分后生成一份中文岗位日报 HTML。

**🎯 零 API key（默认）**：直接用 WorkBuddy 自带的联网搜索（WebSearch）+ 宿主模型打分，装完即用地，**不用申请任何第三方 key、不产生任何费用**。

**合规底线**：只做公开招录类，商业招聘平台（BOSS / 智联 / 猎聘 / 51job 等）一律不碰。

**作者抖音**：[@手残巧匠](https://www.douyin.com) —— 一个普通人用 AI 手搓小玩意儿。报告页脚已内置二维码，欢迎关注。

---

## 一、安装到 WorkBuddy

1. 下载本仓库（GitHub 页面绿色 **Code → Download ZIP**，或用 git）：
   ```bash
   git clone https://github.com/Anoarch/job-radar-skill.git
   ```
2. 把文件夹**重命名为 `job-radar`**，复制到 WorkBuddy 的 skills 目录（二选一）：
   - **用户级（所有项目可用）**：`C:\Users\你的用户名\.workbuddy\skills\job-radar\`（Windows）或 `~/.workbuddy/skills/job-radar/`（macOS / Linux）
   - **项目级（仅当前项目）**：`<你的工作区>/.workbuddy/skills/job-radar/`
3. 重启 WorkBuddy 客户端，skill 即生效。

---

## 二、配置（零 key，默认不用配）

**默认路径（推荐，零 key）**：什么都不用配。装完重启后，对话里说「跑岗位雷达」即可——skill 会用 WorkBuddy 自带的 WebSearch 联网搜岗、用宿主模型打分，不产生任何第三方费用。

**可选高级模式（自接 key，命令行批量跑）**：若你想脱离对话、纯命令行跑，或用自己的 key 控制成本，才需要配置：

| 变量 | 必需 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 仅高级模式需 | [DeepSeek 官网](https://platform.deepseek.com) 免费申请，用于脚本模式打分 |
| `TAVILY_API_KEY` | 否 | [Tavily](https://app.tavily.com) 注册，脚本模式搜岗；不填自动 keyless 免费 |
| `JINA_API_KEY` | 否 | 仅 Tavily 兜底 |

> 普通用户走默认零 key 路径，**这一节可以直接跳过**。

---

## 三、填写你的画像

复制 `profile.example.json` 为 `profile.json`，改成你自己的（专业 / 城市 / 学历 / 状态 / 经验 / 邮箱）。也可以不填，直接在对话里口述画像。

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

**对话触发（默认，零 key）**：
> 跑岗位雷达，用我的 profile.json 生成今日岗位日报

**命令行（可选高级模式，需自接 key）**：
```bash
python scripts/run_report.py --profile profile.json --out report
# 生成的报告在 report/index.html
```

---

## 五、每天自动推送（可选）

在 WorkBuddy 建一个每日自动化（如每天 9:30），prompt 写：
> 运行岗位雷达 skill，用我的 profile.json 生成今日岗位日报

即可每天自动收到报告（同样零 key）。

---

## 六、文件结构

```
job-radar-skill/
  SKILL.md              # skill 入口（触发词 + 零 key 对话工作流指令）
  README.md             # 本文件
  profile.example.json  # 画像模板
  scripts/              # 可选高级模式：自接 key 的命令行批量生成
    run_report.py       # CLI 入口
    retriever.py        # 检索 + 打分核心（与对话路径规则完全一致）
    config.py / usage_store.py / build_delivery.py / sample_jobs.py
  assets/
    交付日报模板.html    # 报告模板（对话模式也复用它）
    douyin-qr.png       # 抖音二维码（引流）
```

---

## 七、自定义（改成你自己的情况）

所有文件都在你本地 WorkBuddy 的 skills 目录里，是**明文 Python/HTML**，随便改。作者不介入、也收不到你的数据或反馈——改完重跑就生效。

| 想改什么 | 改哪里 |
|---|---|
| 求职画像（必改） | `profile.json`（复制 `profile.example.json`） |
| 只收最近 N 天 | 对话里说「放宽到 30 天」；或脚本模式设 `MAX_AGE_DAYS=30` |
| 加细分行业词 | 对话里补充，或脚本模式改 `scripts/retriever.py` 的 `_build_queries()` |
| 报告样式 | `assets/交付日报模板.html` + 对话要求调整 |

---

## 八、合规与原理

- **只检索公开招录**（政府 / 事业单位 / 国企 / 高校 / 医院 / 公务员公开发布），商业平台一律不碰。
- **默认零 key**：搜岗用 WorkBuddy WebSearch，打分用宿主模型推理，无任何第三方费用。
- **15 天新鲜度硬闸 + 商业平台黑名单**，从源头避免"旧岗混入"和合规风险。
- 想脱离对话批量跑？`scripts/` 里保留了与你本地对话**完全一致规则**的命令行版本，自接 key 即可用。
