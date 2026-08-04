#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
对外交付日报生成器 —— 给「岗位雷达」申请者跑专属日报的唯一入口。

与 build_report.py 的区别（别搞混）:
    build_report.py    自用日报。带标注/已投递/不想投/保存回写等交互, 写进 job-hunt/日报/。
    build_delivery.py  对外交付。纯静态零 JS, 无本地文件回写, 无 file:// 死链, 独立输出目录。

为什么要单独一套:
    1. 自用版会写 <root>/日报/YYYY-MM-DD.html, 直接覆盖用户当天自己的日报;
    2. 自用版卡片带「写自荐信」按钮, 指向 ../推荐信/自荐信生成器.html —— 对外部署后是死链;
    3. 自用版的标注按钮会把陌生人引向「保存标注到文件」这种本地能力, 对外无意义。
    所以对外交付不复用自用模板, 但同样禁止手工拼 HTML —— 只能走本脚本。

用法:
    python build_delivery.py <数据JSON路径> <输出目录>

数据 JSON 结构:
{
  "日期": "2026-08-02",
  "标题": "管理学 · 广东+厦门 专属岗位日报",
  "画像": ["管理学", "本科", "2 年经验", "广东 + 厦门", "期望 1w"],
  "小结": "这次一共扫到 N 个……(支持 <b> 标签)",
  "分区": [
    {"名": "高匹配", "说明": "专业经验城市都对得上", "岗位": [ {...}, ... ]},
    ...
  ]
}
岗位字段:
  岗位名 / 单位 / 城市 / 薪资 / 学历要求 / 经验要求 / 链接 / 分数 / 匹配理由
  可选: 标签[{"文":"国企","型":"ok|warn|"}] / 提醒 / 投递方式

铁律（沿用自用版的教训）:
  1. 模板只做 str.replace('{{X}}', v), 严禁对整页用 .format()/f-string —— CSS 的 { } 会被吃掉。
  2. 一切用户数据都过 html.escape, 匹配理由/小结允许保留 <b>。
  3. 不在本脚本里内联任何交互 JS。交付页就该是纯静态的。
"""
import sys
import re
import json
import shutil
import html as html_mod
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SCRIPTS_DIR.parent / "assets"
TEMPLATE = ASSETS_DIR / "交付日报模板.html"

CARD_TPL = """<div class="card{{DIM}}">
  <div class="r1">
    <div class="role"><a href="{{LINK}}" target="_blank" rel="noopener">{{ROLE}}</a></div>
    <div class="score {{SCORE_CLS}}">{{SCORE}} 分</div>
  </div>
  <div class="meta"><b>{{UNIT}}</b> ｜ {{CITY}} ｜ {{SALARY}} ｜ {{EDU}} ｜ {{EXP}}</div>
  {{DEADLINE}}
  {{TAGS}}
  <div class="why">{{REASON}}</div>
  {{NOTE}}
  <div class="apply">
    <a href="{{LINK}}" target="_blank" rel="noopener">查看原文并投递 →</a>
    {{WAY}}
  </div>
</div>"""


def esc(v):
    return html_mod.escape(str(v if v is not None else "")).strip()


def rich(v):
    """允许 <b> 的富文本字段。"""
    return esc(v).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def build_card(job):
    score = int(job.get("分数", 0))
    tags = job.get("标签") or []
    tags_html = ""
    if tags:
        items = "".join(
            '<span class="tag {}">{}</span>'.format(esc(t.get("型", "")), esc(t.get("文", "")))
            for t in tags
        )
        tags_html = '<div class="tags">{}</div>'.format(items)

    note = job.get("提醒")
    note_html = '<div class="note">⚠️ {}</div>'.format(rich(note)) if note else ""

    way = job.get("投递方式")
    way_html = '<span class="way">{}</span>'.format(rich(way)) if way else ""

    # 截止日期：未注明 → 红色提醒；其余正常显示
    dl = job.get("截止日期") or "未注明"
    if dl == "未注明" or not dl.strip():
        dl_html = ('<div class="dl" style="margin:4px 0;font-size:13px;'
                   'color:#d4380d;font-weight:600;">截止：未注明 · 请向单位核实</div>')
    else:
        dl_html = ('<div class="dl" style="margin:4px 0;font-size:13px;'
                   'color:#555;">截止：{}</div>').format(esc(dl))

    html = CARD_TPL
    repl = {
        "{{DIM}}": " dim" if score < 40 else "",
        "{{LINK}}": esc(job.get("链接")),
        "{{ROLE}}": esc(job.get("岗位名")),
        "{{SCORE}}": str(score),
        "{{SCORE_CLS}}": "hi" if score >= 70 else "",
        "{{UNIT}}": esc(job.get("单位")),
        "{{CITY}}": esc(job.get("城市")),
        "{{SALARY}}": esc(job.get("薪资")),
        "{{EDU}}": esc(job.get("学历要求")),
        "{{EXP}}": esc(job.get("经验要求")),
        "{{DEADLINE}}": dl_html,
        "{{TAGS}}": tags_html,
        "{{REASON}}": rich(job.get("匹配理由")),
        "{{NOTE}}": note_html,
        "{{WAY}}": way_html,
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


def main():
    if len(sys.argv) < 3:
        print("用法: python build_delivery.py <数据JSON> <输出目录>")
        return 1

    data_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    data = json.loads(data_path.read_text(encoding="utf-8"))

    chips = "".join(
        '<span class="chip{}">{}</span>'.format(" hl" if i == 0 else "", esc(c))
        for i, c in enumerate(data.get("画像", []))
    )

    sections = []
    total = 0
    for sec in data.get("分区", []):
        jobs = sec.get("岗位", [])
        if not jobs:
            continue
        total += len(jobs)
        cards = "\n".join(build_card(j) for j in jobs)
        sections.append(
            '<h2>{} <span class="n">{} 个</span></h2>\n{}'.format(
                esc(sec.get("名")), len(jobs), cards
            )
        )

    tpl = TEMPLATE.read_text(encoding="utf-8")
    out = tpl
    for k, v in {
        "{{TITLE}}": esc(data.get("标题", "岗位雷达 · 专属日报")),
        "{{HEAD}}": esc(data.get("标题", "专属岗位日报")),
        "{{DATE}}": esc(data.get("日期", "")),
        "{{CHIPS}}": chips,
        "{{SUMMARY}}": rich(data.get("小结", "")),
        "{{SECTIONS}}": "\n".join(sections),
        "{{CITYFILTER}}": data.get("城市筛选", "") or "",
    }.items():
        out = out.replace(k, v)

    leftover = [t for t in ("{{TITLE}}", "{{HEAD}}", "{{DATE}}", "{{CHIPS}}",
                            "{{SUMMARY}}", "{{SECTIONS}}", "{{CITYFILTER}}") if t in out]
    if leftover:
        print("占位符未替换干净: {}".format(leftover))
        return 1
    # 校验所有 <style> 块（含城市筛选等注入块），防止误用 format() 吃掉 CSS 大括号
    for blk in re.findall(r"<style>(.*?)</style>", out, re.S):
        if "{{" in blk:
            print("CSS 区疑似被吃成双大括号, 检查是否误用了 format()")
            return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    target.write_text(out, encoding="utf-8")
    # 连同抖音二维码一起拷贝到输出目录，避免报告里二维码图裂（模板用 onerror 隐藏，
    # 但能显示更好——它是引导用户到抖音的关键入口）
    qr_src = ASSETS_DIR / "douyin-qr.png"
    if qr_src.exists():
        shutil.copy(qr_src, out_dir / "douyin-qr.png")
    print("已生成 {} （{} 个岗位）".format(target, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
