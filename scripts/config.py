# -*- coding: utf-8 -*-
"""岗位雷达 · 合规与配额配置（集中管理，便于维护与审计）。

合规底线：只做「公开招录类」——政府/人社局/事业单位/国企/高校/医院/公务员
公开发布的招聘公告。商业招聘平台（BOSS直聘/智联/猎聘/51job 等）一律硬拦截：
其 ToS 禁止爬取 + 不正当竞争判例 + 甚至有刑案风险（巧达科技爬 2 亿简历被查封）。
"""
import urllib.parse as _up

# ---------- 公开招录源 白/黑名单（合规护栏核心） ----------

# 命中即视为「商业平台 / 非公开招录」→ 丢弃（不区分大小写，子串匹配）。
SOURCE_BLACKLIST = [
    "zhipin", "kanzhun",    # BOSS 直聘
    "zhaopin", "智联",       # 智联招聘
    "liepin", "猎聘",        # 猎聘
    "51job", "前程",         # 51job / 前程无忧
    "lagou",                 # 拉勾
    "jobui",                 # 看准
    "boss",                  # 泛指商业平台
    "yingjiesheng",          # 应届生求职网（聚合站，按边界归入不碰）
]

# 命中即视为「允许的公开招录源」（域名后缀匹配，小写）。
SOURCE_WHITELIST_SUFFIX = [
    "gov.cn",                              # 政府 / 人社局 / 公务员局
    "chinagwy.org", "gjgwy.org",           # 公务员招考网
    "ncss.cn",                             # 国家大学生就业服务平台
    "mohrss.gov.cn",                       # 人社部 · 中国公共招聘网
    "edu.cn",                              # 高校
    "gaoxiaojob.com",                      # 高校人才网
    "sydwzk.cn", "sydw.com", "offcn.com", "huatu.com",  # 事业单位 / 公考
    "gqrczp.com",                          # 国企人才网
    "sgcc.com.cn", "cnpc.com.cn", "sinopec.com",
    "cmcc.com.cn", "crc.com.cn",           # 央企官网
    "nhc.gov.cn",                          # 国家卫健委
]

# 命中即视为允许的公开源（域名含关键字）。
SOURCE_WHITELIST_KEYWORD = [
    "wjw", "wsjkw", "health", "hrss", "renshe",
    "school", "univ", "hospital",
]


def _host_of(url):
    try:
        return _up.urlparse(url or "").netloc.lower()
    except Exception:
        return ""


def is_blocked(url):
    """硬闸：商业平台 / 非公开招录源 → True（一律丢弃，不进入报告）。"""
    h = _host_of(url)
    if not h:
        return False
    return any(b in h for b in SOURCE_BLACKLIST)


def is_allowed(url):
    """软判：公开招录源 → True；商业平台 → False；未知公开页 → 默认放行。

    说明：硬闸是 is_blocked（商业平台必丢）；白名单仅用于检索召回偏置。
    未知公开页默认放行，避免误伤医院/单位官网等合法公开招录源。
    """
    h = _host_of(url)
    if not h:
        return False
    if any(b in h for b in SOURCE_BLACKLIST):
        return False
    if any(h.endswith(s) for s in SOURCE_WHITELIST_SUFFIX):
        return True
    if any(k in h for k in SOURCE_WHITELIST_KEYWORD):
        return True
    return True


# ---------- 配额 / 预算 / 节流 ----------
FREE_QUOTA_PER_EMAIL_PER_DAY = 3      # 每邮箱每日免费份数
BUDGET_CNY_PER_DAY = 10.0             # 全站每日检索预算上限（≈200 份）
EST_COST_CNY_PER_REPORT = 0.05        # 单份估算成本（DeepSeek≈0.03 + Jina 免费）
MAX_QUERIES_PER_DAY = 600             # 第二道闸：每日查询次数上限
MIN_INTERVAL_SEC = 3                   # 全局最小提交间隔（防突发高频）
