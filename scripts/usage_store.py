# -*- coding: utf-8 -*-
"""每日用量持久化（JSON）。邮箱即身份（无注册），预算熔断 + 免费额度。

存于 deliveries/_data/usage.json，按日期键自然重置（读时若日期 != 今天则新建）。
"""
import json
import datetime as _dt
from pathlib import Path
from config import (FREE_QUOTA_PER_EMAIL_PER_DAY, BUDGET_CNY_PER_DAY,
                    EST_COST_CNY_PER_REPORT, MAX_QUERIES_PER_DAY)

STORE = Path(__file__).resolve().parent / "deliveries" / "_data" / "usage.json"


def _today():
    return _dt.date.today().isoformat()


def _load():
    if not STORE.exists():
        return {}
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _day():
    d = _load()
    t = _today()
    if d.get("date") != t:
        d = {"date": t, "queries": 0, "cost_cny": 0.0, "by_email": {}}
        _save(d)
    return d


def queries_today():
    return _day().get("queries", 0)


def cost_today():
    return _day().get("cost_cny", 0.0)


def quota_used(email):
    return _day().get("by_email", {}).get(email, 0)


def is_over_budget():
    """全局预算/查询上限熔断。"""
    return (cost_today() >= BUDGET_CNY_PER_DAY) or (queries_today() >= MAX_QUERIES_PER_DAY)


def is_over_quota(email):
    """单邮箱免费额度耗尽。"""
    return quota_used(email) >= FREE_QUOTA_PER_EMAIL_PER_DAY


def add_report(email, cost_cny=None):
    """生成成功一份后调用：累加查询数 / 成本 / 该邮箱额度。"""
    d = _day()
    d["queries"] = d.get("queries", 0) + 1
    d["cost_cny"] = round(d.get("cost_cny", 0.0) + (cost_cny or EST_COST_CNY_PER_REPORT), 4)
    by = d.setdefault("by_email", {})
    by[email] = by.get(email, 0) + 1
    _save(d)
