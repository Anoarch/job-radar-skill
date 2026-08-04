# -*- coding: utf-8 -*-
"""P1 自动检索 + 打分（DeepSeek LLM + Jina 搜索，两层解耦，纯标准库）。

架构：
  LLM 层  → DeepSeek V3（OpenAI 兼容 API）→ 解析/打分/组装中文-key JSON
  搜索层  → Jina AI Search（s.jina.ai）  → 联网搜真实岗位，可独立替换
  两层互不耦合：搜索不够好只换 Jina→Tavily/混元；LLM 不够好只换 DeepSeek→通义。

Key 来源：从 .env 或系统环境变量读，绝不硬编码（见 _load_env）。

打分采用「LLM 出 5 个子分 → 后端确定性合成总分」混合方案，
权重：专业0.40 / 经验0.25 / 学历0.15 / 城市0.10 / 薪资0.10。
"""
import json
import os
import re
import sys
import datetime as _dt
import calendar
import urllib.parse
import urllib.request
from pathlib import Path
from config import is_blocked, is_allowed, BUDGET_CNY_PER_DAY, EST_COST_CNY_PER_REPORT
from usage_store import is_over_budget

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ----------------------------------------------------------------------------
# .env 加载（无外部依赖，仅 setdefault 不覆盖已有环境变量）
# ----------------------------------------------------------------------------
def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()  # .env 覆盖，本地开发优先

_load_env()


# ----------------------------------------------------------------------------
# 配置（全部从环境变量读）
# ----------------------------------------------------------------------------
class Config:
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    JINA_API_KEY = os.getenv("JINA_API_KEY", "")
    JINA_SEARCH_URL = "https://s.jina.ai/"
    JINA_READER_URL = "https://r.jina.ai/"
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
    TAVILY_SEARCH_URL = "https://api.tavily.com/search"
    SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "auto")  # auto / tavily / jina
    READ_TOKEN_BUDGET = 2000     # jina 读全文时单次截断上限（降耗关键）
    SEARCH_MAX_CHARS = 6000
    STALE_DAYS = 45                 # 搜索结果页面发布日距今超过此天数 → 视为已截止归档，搜索层直接丢弃
    BUDGET_CNY_PER_DAY = BUDGET_CNY_PER_DAY   # 来自 config：全站每日检索预算上限
    TIMEOUT = 30
    WEIGHTS = {"专业": 0.40, "经验": 0.25, "学历": 0.15, "城市": 0.10, "薪资": 0.10}


# ----------------------------------------------------------------------------
# 代理感知 opener：urllib 默认不读 HTTPS_PROXY 环境变量。
# 沙箱环境需经本地代理(127.0.0.1:7897)出网，Jina 等才可达；
# 自有服务器无代理变量时自动直连。两个客户端统一复用，避免重复逻辑。
# ----------------------------------------------------------------------------
_PROXY = (os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
          or os.getenv("https_proxy") or os.getenv("http_proxy"))
_OPENER = (urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY})
) if _PROXY else None)


def _urlopen(req, timeout=30):
    if _OPENER:
        return _OPENER.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


# ----------------------------------------------------------------------------
# 中文 key 铁律：白名单校验（避免静默 0 岗位，见计划文件 §3.3）
# ----------------------------------------------------------------------------
ALLOWED_TOP = {"日期", "标题", "画像", "小结", "分区"}
ALLOWED_SEC = {"名", "说明", "岗位"}
ALLOWED_JOB = {"岗位名", "单位", "城市", "薪资", "学历要求", "经验要求", "链接",
               "子分", "匹配理由", "标签", "提醒", "投递方式", "分数", "截止日期"}
ALLOWED_SUB = {"专业", "经验", "学历", "城市", "薪资"}


class ChineseKeyError(Exception):
    pass


class BudgetExceeded(Exception):
    """每日检索预算/查询上限熔断。"""


def validate_chinese_keys(data):
    """递归校验：任何 key 不在白名单 → 抛 ChineseKeyError。"""
    def check_obj(obj, allowed, path):
        if not isinstance(obj, dict):
            return
        for k, v in obj.items():
            if k not in allowed:
                raise ChineseKeyError("非法 key '{}' 在 {}".format(k, path))
            if k == "分区":
                for i, sec in enumerate(v):
                    check_obj(sec, ALLOWED_SEC, "{}[{}]".format(path, i))
                    for j, job in enumerate(sec.get("岗位", [])):
                        check_obj(job, ALLOWED_JOB, "{}[{}].岗位[{}]".format(path, i, j))
            elif k == "子分" and isinstance(v, dict):
                for sk in v:
                    if sk not in ALLOWED_SUB:
                        raise ChineseKeyError("非法子分 key '{}'".format(sk))
            elif isinstance(v, dict):
                check_obj(v, allowed, path + "." + k)
    check_obj(data, ALLOWED_TOP, "root")


# ----------------------------------------------------------------------------
# 打分：子分 → 总分 → 分区阈值
# ----------------------------------------------------------------------------
def attach_total_scores(data):
    """LLM 给的「子分」确定性合成总分，并填「分数」字段（build_delivery.py 读它）。"""
    for sec in data.get("分区", []):
        for job in sec.get("岗位", []):
            sub = job.pop("子分", None)
            if sub:
                total = round(sum(sub.get(k, 0) * w for k, w in Config.WEIGHTS.items()))
                job["分数"] = total
            job.setdefault("分数", 0)
    return data


def rezone(data):
    """按阈值重排分区：≥70 高匹配 / 40-69 可以一试 / <40 学历不符·仅供参考。"""
    high, mid, low = [], [], []
    for sec in data.get("分区", []):
        for job in sec.get("岗位", []):
            s = job.get("分数", 0)
            (high if s >= 70 else mid if s >= 40 else low).append(job)
    zones = []
    if high:
        zones.append({"名": "高匹配", "说明": "专业/学历/城市都对得上", "岗位": high})
    if mid:
        zones.append({"名": "可以一试", "说明": "有一定差距但值得关注", "岗位": mid})
    if low:
        zones.append({"名": "学历不符·仅供参考", "说明": "硬性门槛未达，仅作了解", "岗位": low})
    data["分区"] = zones
    return data


# ----------------------------------------------------------------------------
# 新鲜度闸门：剔除已截止岗位，保留未来/未注明；并追加核实提示
# ----------------------------------------------------------------------------
def _parse_deadline(text):
    """解析中文/ISO 截止日期 → date；无法解析返回 None（视为未注明）。"""
    if not text or "未注明" in text:
        return None
    t = text.strip()
    # ISO: 2026-08-15 / 2026/08/15 / 2026年08月15日
    m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return _dt.date(y, mo, d)
        except ValueError:
            pass
    # 仅 月日: 8月15日 → 当年
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", t)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            return _dt.date(_dt.date.today().year, mo, d)
        except ValueError:
            pass
    # 仅 年月: 2026年8月 → 该月最后一天
    m = re.search(r"(\d{4})年(\d{1,2})月", t)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            last = calendar.monthrange(y, mo)[1]
            return _dt.date(y, mo, last)
    return None


def _parse_jina_date(s):
    """解析 Jina 结果的 date 字段（如 'Apr 30, 2026' / '2026-04-30'）→ date。"""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def filter_expired(data, today=None):
    """新鲜度闸门：过期岗直接丢弃；未注明保留但提示核实；小结追加提示。
    返回 (data, stats)。必须在 attach_total_scores / rezone 之前调用。"""
    today = today or _dt.date.today()
    dropped, kept, unverified = 0, 0, 0
    new_zones = []
    for sec in data.get("分区", []):
        new_jobs = []
        for job in sec.get("岗位", []):
            pd = _parse_deadline(job.get("截止日期") or "")
            if pd is not None and pd < today:
                dropped += 1
                continue
            if pd is None:
                unverified += 1
            kept += 1
            new_jobs.append(job)
        if new_jobs:
            sec = dict(sec)
            sec["岗位"] = new_jobs
            new_zones.append(sec)
    data["分区"] = new_zones

    note = ("<br>⚠️ <b>新鲜度提示</b>：检索结果来自公开网页，可能含已截止公告。"
            "请务必点「查看原文」核对报名截止日期；标「未注明」的岗位需自行向单位确认。")
    if kept == 0:
        note = ("<br>⚠️ 本次未检索到明确在招的岗位（多为已截止公告）。"
                "可尝试更换城市/专业，或稍后重试。") + note
    data["小结"] = (data.get("小结") or "") + note
    return data, {"dropped": dropped, "kept": kept, "unverified": unverified}


def enforce_source_whitelist(data):
    """输出层硬闸：丢弃任何链接命中商业平台黑名单的岗位（即便 LLM 编出来）。
    返回 (data, stats)。必须在 validate_chinese_keys 之后、rezone 之前调用。"""
    dropped = 0
    new_zones = []
    for sec in data.get("分区", []):
        new_jobs = []
        for job in sec.get("岗位", []):
            link = job.get("链接") or ""
            if link and is_blocked(link):
                dropped += 1
                continue
            new_jobs.append(job)
        if new_jobs:
            sec = dict(sec)
            sec["岗位"] = new_jobs
            new_zones.append(sec)
    data["分区"] = new_zones
    if dropped:
        note = "<br>⚠️ 已自动剔除 {} 条来自商业招聘平台的链接（岗位雷达只汇总公开发布类招录，不碰 BOSS/智联/猎聘/51job 等）。".format(dropped)
        data["小结"] = (data.get("小结") or "") + note
    return data, {"dropped_blocked": dropped}


# ----------------------------------------------------------------------------
# 检索 agent：搜索层 + LLM 层（两层解耦）
# ----------------------------------------------------------------------------
SYSTEM_PROMPT = """你是一个招聘检索与匹配助手"岗位雷达"。下面会给你若干【搜索结果片段】（来自联网搜索），
请你从中筛选真实、近期（2026年）、可投递的招聘岗位，并给出结构化结果。

【质量红线】
- 必须提取「截止日期」：优先用原文明确的 报名截止/截止日期；若原文只有搜索结果自带的 date（页面发布日），且无明确报名截止，则填 "发布日 YYYY-MM-DD（请核实截止）"。早于今天(<<TODAY>>)的岗位直接丢弃；两者皆无的填"未注明"并保留（用户需自行核实）。绝不收录已截止岗位。
- 搜索层已按页面发布日过滤掉距今超 45 天的旧页面，你只需处理剩余结果；若某结果仍带早于今天的发布日，按过期处理。
- 宁缺毋滥：中介广告、纯提成/无底薪/保险/地推 直接丢弃。
- 学历必须核验：本科画像下，硕士起岗位归入"学历不符"区，不要混进高匹配。
- 每个岗位必须可跳转（给原文链接），无链接不收录。
- 匹配理由必须具体（点名画像哪段对上 JD 哪条），空泛理由退回重生成。
- 只使用搜索结果里真实出现过的岗位与链接，不得编造。
- 【数据源红线】只收录<b>政府/人社局/事业单位/国企/高校/医院/公务员公开发布</b>的招聘公告。若搜索结果中出现 BOSS直聘/智联/猎聘/51job 等<b>商业招聘平台</b>链接，一律不得收录（这些平台 ToS 禁止爬取，且属专有数据）。
- 优先收录 2026 年发布、正在报名的近期公告；体制内/事业单位/国企公告多带明确截止日，务必提取。

【输出格式】严格返回如下 JSON（key 全中文，不要任何解释文字）：
{
  "日期": "2026-08-04",
  "标题": "{专业方向} · {城市} 专属岗位日报",
  "画像": ["{专业方向}","{学历}","{工作年限及经验}","{城市}","{求职状态/期望}"],
  "小结": "≤120字，可含 <b> 强调主推",
  "分区": [
    {"名":"高匹配","说明":"…","岗位":[ {
        "岗位名":"…","单位":"…","城市":"…","薪资":"…",
        "学历要求":"…","经验要求":"…","链接":"…",
        "截止日期":"2026-08-15 或 未注明",
        "子分":{"专业":0-100,"经验":0-100,"学历":0-100,"城市":0-100,"薪资":0-100},
        "匹配理由":"…","标签":[{"文":"国企","型":"ok|warn"}],
        "提醒":"…(可选)","投递方式":"…(可选)"
    } ]}
  ]
}
注意：先给"子分"对象，总分由后端按权重计算，你不要算总分。"""


class TavilyClient:
    """Tavily Search —— AI 原生搜索，返回 title+url+content 摘要，无需额外读全文。
    支持 keyless（默认,零注册）与 Bearer key 两种模式。免费档 1000 credits/月。
    content 摘要已足够 LLM 打分，因此搜索层不再把整篇公告全文拉回 → token 消耗降 ~95%。"""

    def _search(self, query):
        payload = json.dumps({
            "query": query,
            "max_results": 8,
            "search_depth": "advanced",  # 深度召回,提升招聘公告命中率
            "days": 60,                 # 时间窗:只收近 60 天发布
            "include_answer": False,
            "include_raw_content": False,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if Config.TAVILY_API_KEY:
            headers["Authorization"] = "Bearer " + Config.TAVILY_API_KEY
        else:
            # 零注册 keyless 模式（rate-limited,适合轻量/探索/别人零配置试用）
            headers["X-Tavily-Access-Mode"] = "keyless"
        req = urllib.request.Request(
            Config.TAVILY_SEARCH_URL, data=payload, headers=headers, method="POST")
        with _urlopen(req, timeout=Config.TIMEOUT) as r:
            obj = json.loads(r.read().decode("utf-8"))
        items = obj.get("results") or []
        lines, dropped = [], 0
        for it in items:
            url = it.get("url", "")
            if is_blocked(url):
                dropped += 1
                continue
            title = it.get("title", "")
            content = (it.get("content") or "").strip()
            # 编码兜底：个别 GBK 站点 content 可能乱码，尝试修复
            try:
                content.encode("utf-8")
            except UnicodeEncodeError:
                try:
                    content = content.encode("latin-1").decode("gb18030", "ignore")
                except Exception:
                    pass
            pub = it.get("published_date") or ""
            lines.append("【标题】{}\n【链接】{}\n【发布】{}\n【摘要】{}".format(
                title, url, pub, content[:800]))
        if not lines:
            return "(Tavily 未返回有效结果)"
        blob = "\n---\n".join(lines)
        if dropped:
            blob = "[搜索层已过滤 {} 条商业平台链接]\n".format(dropped) + blob
        return blob

    def search(self, query):
        try:
            return self._search(query)
        except urllib.error.HTTPError as e:
            return "搜索失败: Tavily HTTP {}".format(e.code)
        except Exception as e:
            return "搜索失败: {}（若持续,请检查网络或代理设置）".format(e)


class _JinaSearchClient:
    """Jina 搜索（s.jina.ai）—— 作为 Tavily 不可用时的兜底。保留原逻辑。"""

    def _search(self, query):
        url = "https://s.jina.ai/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + Config.JINA_API_KEY,
                # 必须带浏览器 UA：Jina 会直接 403 掉 Python-urllib 默认 UA
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        with _urlopen(req, timeout=Config.TIMEOUT) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        # 解析 JSON，按页面发布日过滤掉过期归档页（保留无 date 的，留给 LLM 自行判断）
        try:
            obj = json.loads(raw)
            items = obj.get("data") if isinstance(obj, dict) else None
            if isinstance(items, list) and items:
                cutoff = _dt.date.today() - _dt.timedelta(days=Config.STALE_DAYS)
                kept, dropped = [], 0
                for it in items:
                    # 搜索层硬闸：命中商业平台黑名单的链接直接丢（不进 LLM）
                    if is_blocked(it.get("url", "")):
                        dropped += 1
                        continue
                    d = _parse_jina_date(it.get("date"))
                    if d is not None and d < cutoff:
                        dropped += 1
                        continue
                    kept.append(it)
                obj["data"] = kept
                raw = json.dumps(obj, ensure_ascii=False)
                if dropped:
                    raw = "[搜索层已过滤 {} 条发布超 {} 天的旧页面]\n".format(
                        dropped, Config.STALE_DAYS) + raw
        except Exception:
            pass  # 非 JSON / 解析失败 → 保留原文，不当丢
        # s.jina.ai 一次返回前 5 条结果的完整正文，体积较大；截断以控制下游 LLM token 成本
        if len(raw) > Config.SEARCH_MAX_CHARS:
            raw = raw[:Config.SEARCH_MAX_CHARS] + "\n…(结果已截断)"
        return raw

    def search(self, query):
        if not Config.JINA_API_KEY:
            return "（未配置 JINA_API_KEY，Jina 搜索层不可用）"
        try:
            return self._search(query)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return "搜索失败: Jina 返回 401（Key 无效/未激活，请在 Jina 控制台核对 API Key）"
            if e.code == 429:
                return "搜索失败: Jina 限流(429)，稍后重试"
            return "搜索失败: Jina 返回 HTTP {}".format(e.code)
        except Exception as e:
            return "搜索失败: {}（若持续，请检查网络或代理设置）".format(e)


class WebSearchClient:
    """搜索层编排：Tavily 优先（免费 keyless / 自带 key），jina 搜索兜底。
    两层解耦：搜索不够好只换 Tavily→Jina→其他；LLM 不够好只换 DeepSeek→通义。"""

    def __init__(self):
        self.tavily = TavilyClient()
        self._jina = _JinaSearchClient()

    def search(self, query):
        provider = Config.SEARCH_PROVIDER
        # Tavily 优先（auto / tavily）
        if provider in ("auto", "tavily"):
            r = self.tavily.search(query)
            if r and not r.startswith("搜索失败") and "未返回有效结果" not in r:
                return r
        # jina 兜底（auto / jina 且配了 key）
        if provider in ("auto", "jina") and Config.JINA_API_KEY:
            return self._jina.search(query)
        # 都不可用：诚实返回提示
        if provider in ("auto", "tavily"):
            return "(搜索层暂不可用;请配置 TAVILY_API_KEY 提升额度,或设 SEARCH_PROVIDER=jina 并配置 JINA_API_KEY)"
        return "(搜索层暂不可用;请配置 JINA_API_KEY)"


class LLMClient:
    """LLM 层：DeepSeek（OpenAI 兼容）。可独立替换为混元/通义。"""

    def complete_json(self, system, user):
        payload = json.dumps({
            "model": Config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
            data=payload,
            headers={
                "Authorization": "Bearer " + Config.DEEPSEEK_API_KEY,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with _urlopen(req, timeout=Config.TIMEOUT) as r:
            resp = json.loads(r.read().decode("utf-8"))
        return json.loads(resp["choices"][0]["message"]["content"])


class SearchAgent:
    """封装一次「搜索 + LLM 解析」调用。两层可独立替换。"""

    def __init__(self, profile):
        self.profile = profile
        self.search_client = WebSearchClient()
        self.llm = LLMClient()

    def _build_queries(self):
        p = self.profile
        cities = [c for c in re.split(r"[/、，,\s]+", p.get("城市") or "全国") if c] or ["全国"]
        major = p.get("专业") or "应届生"
        status = p.get("状态", "")
        edu = p.get("学历", "")
        queries = []
        # ------------------------------------------------------------------
        # 专业 → 领域通道词映射（解决医学/法律/教育等专业被通用模板带偏）
        # 每个类目：(专业关键词列表, [领域通道词])
        # 匹配策略：专业字段含任一关键词即追加对应通道词；多个类目叠加去重。
        # 无匹配时走通用兜底（事业/国企），保证任何专业都不会零 query。
        # ------------------------------------------------------------------
        DOMAIN_CHANNELS = [
            # 医学/卫生/药学/护理
            (["医学", "药学", "护理", "临床", "中医", "中药", "口腔", "公共卫生",
              "医学影像", "医学检验", "康复", "麻醉", "助产", "营养"],
             ["医院", "卫健委", "公立医院", "附属医院"]),
            # 法律/司法/公安
            (["法律", "法学", "司法", "检察", "公安", "警察", "监狱", "律师", "公证"],
             ["司法所", "法院", "检察院", "公安局"]),
            # 教育/师范/教师
            (["教育", "师范", "教师", "学前", "学科教学", "汉语国际", "对外汉语"],
             ["中小学", "教育局", "高校 辅导员", "党校"]),
            # 工科/计算机/电子
            (["计算机", "软件", "电子", "通信", "电气", "机械", "土木", "建筑", "化工",
              "材料", "人工智能", "AI", "数据", "网络", "自动化", "光电", "航空航天",
              "船舶", "汽车", "能源", "动力"],
             ["研究所", "国企", "央企"]),
            # 理科
            (["数学", "物理", "化学", "生物", "统计", "地理", "地质", "天文", "生态", "环境"],
             ["研究所", "实验室", "高校 科研"]),
            # 文科/文史哲/外语
            (["中文", "历史", "哲学", "新闻", "传播", "外语", "英语", "日语", "俄语",
              "韩语", "翻译", "政治", "马克思", "社会学", "心理", "图书", "档案", "文物"],
             ["博物馆", "图书馆", "高校 行政", "党校"]),
            # 经济/管理/财会
            (["会计", "金融", "经济", "管理", "工商", "公共管理", "税务", "财政", "审计",
              "市场营销", "人力资源", "MBA"],
             ["银行", "财政局", "审计局"]),
        ]
        channels = []
        for keys, chs in DOMAIN_CHANNELS:
            if any(k in major for k in keys):
                channels.extend(chs)
        # 去重保序
        seen, channels_uniq = set(), []
        for ch in channels:
            if ch not in seen:
                seen.add(ch)
                channels_uniq.append(ch)
        # 通用兜底：未匹配任何专业类目 → 给事业/国企通道
        if not channels_uniq:
            channels_uniq = ["事业单位", "国企"]
        # 每个城市生成：通用 query + 领域专属 query（最多前 2 个城市，避免 token 浪费）
        for c in cities[:2]:
            queries.append("{} {} 事业单位 公开招聘 2026 报名".format(c, major))
            for ch in channels_uniq[:3]:  # 每个城市最多追加 3 条领域通道
                queries.append("{} {} {} 招聘 2026 报名".format(c, major, ch))
        if status == "应届生":
            queries.append("{} {} 校园招聘 2026 应届 事业单位".format(cities[0], major))
        # 全局去重 + 截断到 6 条
        seen, uniq = set(), []
        for q in queries:
            if q not in seen:
                seen.add(q)
                uniq.append(q)
        return uniq[:6]

    def _user_prompt(self, search_blob):
        p = self.profile
        cities = [c for c in re.split(r"[/、，,\s]+", p.get("城市") or "全国") if c] or ["全国"]
        city_line = "、".join(cities)
        return (
            "【用户画像】\n"
            "专业方向：{major}\n意向城市：{city}\n学历：{edu}\n求职状态：{status}\n"
            "工作年限及经验：{exp}\n备注：{remark}\n\n"
            "【检索要求】\n覆盖体制内/编制岗、社招专业岗、泛职能岗三类；"
            "每个城市至少 2-3 个真实岗位；优先近期(2026)可投递。\n\n"
            "【搜索结果片段】\n{blob}\n\n"
            "请基于以上搜索结果，按要求输出 JSON。"
        ).format(
            major=p.get("专业", ""), city=city_line, edu=p.get("学历", ""),
            status=p.get("状态", ""), exp=p.get("经验", ""),
            remark=p.get("备注", ""), blob=search_blob,
        )

    def run(self):
        """搜索 + LLM 解析，返回中文-key 报告 JSON；无 Key 返回 None。"""
        if not Config.DEEPSEEK_API_KEY:
            return None
        if is_over_budget():
            raise BudgetExceeded(
                "今日检索预算已用完（¥{:.1f}/日上限），明早 0 点自动重置。"
                "已生成的报告仍可正常查看。".format(BUDGET_CNY_PER_DAY))
        queries = self._build_queries()
        snippets = []
        for q in queries:
            snippets.append("### 搜索词: {}\n{}".format(q, self.search_client.search(q)))
        search_blob = "\n\n".join(snippets)
        system = SYSTEM_PROMPT.replace("<<TODAY>>", _dt.date.today().isoformat())
        return self.llm.complete_json(system, self._user_prompt(search_blob))


def build_report_from_agent(profile):
    """P1 主入口：调 search_agent → 校验 → 新鲜度闸门 → 打分 → 重排。
    返回 (data, source)，source='agent' 表示真检索，None 表示需回退 P0 样例。"""
    agent = SearchAgent(profile)
    raw = agent.run()
    if raw is None:
        return None, "fallback_sample"
    validate_chinese_keys(raw)      # 铁律①：错 key 直接抛异常，绝不静默
    raw, stats = filter_expired(raw)  # 新鲜度闸门：先剔过期，再打分
    raw, stats2 = enforce_source_whitelist(raw)  # 输出层硬闸：剔商业平台链接
    attach_total_scores(raw)        # 子分 → 总分
    rezone(raw)                     # 按阈值重排分区
    return raw, "agent"
