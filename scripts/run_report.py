#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""岗位雷达 · 通用 CLI 入口（供 skill / 自动化 / 命令行调用）。

用法（用 profile.json）：
  python run_report.py --profile profile.json --out report
用法（口述画像，临时跑）：
  python run_report.py --major 临床医学 --city 北京 --edu 硕士 \
      --status 应届生 --exp 应届 --out report

输出：<out>/index.html（纯静态零 JS）+ <out>/data.json

依赖：同目录的 retriever.py / config.py / usage_store.py / build_delivery.py / assets/
"""
import argparse
import json
import sys
import os
import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)  # 让 .env 加载、assets 路径正确

from retriever import build_report_from_agent, BudgetExceeded
import build_delivery


def main():
    ap = argparse.ArgumentParser(description="岗位雷达 · 生成专属岗位日报")
    ap.add_argument("--profile", help="profile.json 路径（优先于下方散参）")
    ap.add_argument("--major", default="", help="专业方向")
    ap.add_argument("--city", default="全国", help="意向城市（多个用 / 分隔）")
    ap.add_argument("--edu", default="", help="学历")
    ap.add_argument("--status", default="", help="求职状态（如 应届生 / 社招）")
    ap.add_argument("--exp", default="", help="工作年限及经验")
    ap.add_argument("--email", default="", help="接收邮箱（仅记录，默认不发）")
    ap.add_argument("--remark", default="", help="备注 / 特殊诉求")
    ap.add_argument("--out", default="report", help="输出目录（生成 index.html）")
    args = ap.parse_args()

    if args.profile:
        p = Path(args.profile)
        if not p.exists():
            print("ERROR: profile 文件不存在: {}".format(p))
            return 2
        profile = json.loads(p.read_text(encoding="utf-8"))
    else:
        profile = {
            "专业": args.major, "城市": args.city, "学历": args.edu,
            "状态": args.status, "经验": args.exp, "邮箱": args.email,
            "备注": args.remark, "画像": [], "日期": "",
        }

    try:
        data, src = build_report_from_agent(profile)
    except BudgetExceeded as e:
        print("ERROR: 今日检索预算已用完 - {}".format(e))
        return 3
    if data is None:
        print("ERROR: 未配置 DEEPSEEK_API_KEY，或检索全部失败。"
              "请在环境变量配置 DEEPSEEK_API_KEY（Tavily 可留空，自动用 keyless 免费模式）。")
        return 1

    today = datetime.date.today().strftime("%Y-%m-%d")
    data.setdefault("日期", today)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 复用 build_delivery.main() 渲染（通过 argv 注入 json + 输出目录）
    sys.argv = ["build_delivery.py", str(json_path), str(out_dir)]
    rc = build_delivery.main()
    if rc != 0:
        print("ERROR: 渲染失败 rc={}".format(rc))
        return rc

    print("OK source={} report={}".format(src, out_dir / "index.html"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
