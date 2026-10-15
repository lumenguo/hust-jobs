# -*- coding: utf-8 -*-
"""
用公众号「华中科技大学就业指导与服务中心」文章核对/修订现有招聘信息。

逻辑：
  1. 每篇文章按公司名/标题关键词匹配现有条目（主表 + 未注明专栏）
  2. 从文章正文提取 宣讲时间 / 报名截止 / 地点 等时间信息
  3. 修订规则：
     - 专栏条目缺宣讲时间 → 补充（标注来源）
     - 主表条目时间与公众号冲突 → 以公众号最新发布为准，记录差异
     - 一致 → 确认（记为 confirmed）
  4. 输出 data/revisions.json（修订记录），并回写 jobs.json / jobs_notime.json

用法：python revise.py          # 执行核对修订
      python revise.py --dry    # 只预览不落盘
"""
import json
import os
import re
import sys
import time
import difflib

MATCH_THRESHOLD = 0.72   # 匹配阈值（低于此不认定同一单位，防误配）

ROOT = os.path.dirname(os.path.abspath(__file__))
WX = os.path.join(ROOT, "data", "wechat_articles.json")
JOBS = os.path.join(ROOT, "data", "jobs.json")
NT = os.path.join(ROOT, "data", "jobs_notime.json")
REV = os.path.join(ROOT, "data", "revisions.json")

STOP_WORDS = re.compile(
    r"招聘|宣讲会|宣讲|双选会|招聘会|校园|启动|公告|简章|正式|秋招|春招|2027|2026|2028|届|供需|"
    r"华中科技|华中大|就业|指导|服务|中心|武汉|专场|岗位|期待|加入|我们|邀请|诚聘|报名|通知|"
    r"【|】|\||招聘季|官宣|来了|开启|启动|集结|进行时|一览|汇总|一览表|速览|发布|空中|线下|线上|"
    r"【宣讲会】|来袭|预热|来袭|报名|参会|企业|单位|博士|硕士|本科|专业|同学|生源地")

# 泛词：仅凭它不足以认定同一家单位（如"管理培训生"会误连两家不同公司）
GENERIC = (
    "管理培训生", "培训生", "实习生", "应届生", "毕业生", "校园招聘", "秋季", "春季",
    "股份有限公司", "有限责任公司", "有限公司", "股份公司", "集团公司",
    "集团", "股份", "科技", "公司", "研究院", "研究所", "高校", "学院",
    "招聘", "宣讲", "双选", "就业", "人才", "中国", "国际", "武汉", "深圳", "北京",
    "上海", "广州", "杭州", "成都", "西安", "南京", "苏州", "长沙", "岗位", "offer",
)

# 单位后缀（用于原标题→核心公司名的裁剪）
SUFFIX = re.compile(
    r"(?:股份有限公司|有限责任公司|集团有限公司|有限公司|股份公司|集团公司|"
    r"研究院|研究所|大学|学院|集团|公司)$")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def _strip_generic(s):
    """剥掉通用词后缀/词缀，返回实质部分（为空说明整个词都是通用成分）"""
    prev = None
    while prev != s:
        prev = s
        for g in sorted(GENERIC, key=len, reverse=True):
            s = s.replace(g, "")
    return s


def _is_generic(t):
    """是否为泛词（不足以认定同一家单位）"""
    if t in GENERIC:
        return True
    if any(g in t and len(t) <= len(g) + 1 for g in GENERIC):
        return True
    # 整词由通用成分构成（如「股份有限公司」）→ 无实体信息
    return not _strip_generic(t).strip("（）()·- ")


def company_tokens(title):
    """从标题提取单位实体词（用于跨数据匹配），过滤泛词"""
    t = STOP_WORDS.sub(" ", title or "")
    # 去掉日期/时间串
    t = re.sub(r"\d{1,4}\s*[年\-/.]?\s*\d{0,2}\s*[月日]?\s*\d{0,2}[:：]?\d{0,2}", " ", t)
    t = re.sub(r"[^\w一-龥]", " ", t)
    out = []
    for w in t.split():
        w = w.strip()
        if len(w) < 2 or _is_generic(w):
            continue
        if w.isdigit():
            continue
        out.append(w)
    # 原文中的连续实体片段（如「华为数字能源」「欧莱雅(中国)」）
    for m in re.finditer(r"[一-龥A-Za-z][一-龥A-Za-z（(）)·]{1,}", title or ""):
        s = m.group(0)
        if len(s) < 2 or _is_generic(s):
            continue
        if STOP_WORDS.search(s) and len(s) <= 4:
            continue
        out.append(SUFFIX.sub("", s)[:14])
    # 去重，长词优先
    out = sorted(set(w for w in out if len(w) >= 2), key=len, reverse=True)
    return out


# 日期+时刻的通用片段（支持 2026-10-13 / 2026年10月13日 / 10月13日 三种写法）
_D = (r"(?:(?P<y>\d{4})\s*[-年/.]\s*)?(?P<m>\d{1,2})\s*[月\-/.]\s*(?P<d>\d{1,2})\s*日?"
      r"(?:\s*[（(]\s*周[一二三四五六日天]\s*[)）]\s*)?"
      r"(?:\s*(?P<H>\d{1,2})\s*[:：]\s*(?P<M>\d{2}))?"
      r"(?:\s*[-—~至]\s*(?P<H2>\d{1,2})\s*[:：]\s*(?P<M2>\d{2}))?")
_RX_DT = re.compile(_D)

# 带「时间：」前缀的优先级最高
_RX_LABEL = r"(?:宣讲会?时间|宣讲时间|活动时间|举办时间|时间)\s*[:：]\s*"
DEFAULT_YEAR = time.strftime("%Y")  # 缺省年份（无年份写法按当前年补足）


def _norm_dt(m, year=DEFAULT_YEAR):
    """把正则匹配结果归一成 (标准串, 日期串)"""
    y = m.group("y") or year
    try:
        mo, d = int(m.group("m")), int(m.group("d"))
    except (TypeError, ValueError):
        return None, None
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None, None
    date_s = "%s-%02d-%02d" % (y, mo, d)
    s = date_s
    if m.group("H"):
        s += " %02d:%s" % (int(m.group("H")), m.group("M"))
        if m.group("H2"):
            s += "-%02d:%s" % (int(m.group("H2")), m.group("M2"))
    return s, date_s


def _first_dt(text, label_only=False, year=DEFAULT_YEAR):
    """在文本中找第一个日期(时间)；label_only=True 则只认带「时间：」前缀的"""
    if label_only:
        m = re.search(_RX_LABEL + _D, text, re.I)
        return _norm_dt(m, year) if m else (None, None)
    m = _RX_DT.search(text)
    return _norm_dt(m, year) if m else (None, None)


def extract_times(art):
    """从公众号文章（标题 + 正文）提取宣讲时间 / 截止 / 地点 / 笔试面试"""
    body = re.sub(r"[ \t\r\f\v]+", " ", art.get("body_text") or "")
    title = art.get("title") or ""
    full = title + "\n" + body
    out = {}

    # 缺省年份：取文章发布年份（无年份写法按发布年补足）
    pub = art.get("publish_time") or fmt_ts(art.get("publish_ts"))
    my = re.match(r"(\d{4})", pub or "")
    year = my.group(1) if my else DEFAULT_YEAR

    # --- 宣讲时间：正文带标签的最优先，其次正文裸日期，最后标题 ---
    for txt, lo, src in ((body, True, "正文·宣讲会信息"), (body, False, "正文"), (title, False, "标题")):
        s, ds = _first_dt(txt, label_only=lo, year=year)
        if ds:
            out["talk_time"] = s
            out["talk_date"] = ds
            out["talk_from"] = src
            break

    # --- 报名/投递截止 ---
    m = re.search(r"(?:报名|投递|申请|网申|简历)\s*截止时间?\s*[:：]?\s*" + _D, full) \
        or re.search(r"截止\s*(?:时间)?\s*[:：]\s*" + _D, full)
    if m:
        s, ds = _norm_dt(m)
        if ds:
            out["deadline"] = s

    # --- 地点 ---
    m = re.search(r"(?:宣讲|举办|活动)?地点\s*[:：]\s*([^\n|]{3,30})", body)
    if m:
        v = m.group(1).strip().rstrip("。，、； ")
        v = re.sub(r"\s{2,}", " ", v)
        if v and not any(w in v for w in ("详见", "如下", "另行", "见下", "待定")):
            out["place"] = v

    # --- 笔试/面试/测评安排 ---
    for kw in ("笔试", "面试", "测评", "初面", "复面"):
        m = re.search(kw + r"[^。\n]{0,6}?时间\s*[:：]\s*" + _D, full)
        if m:
            s, ds = _norm_dt(m)
            if ds:
                out.setdefault("exam", []).append({"type": kw, "time": s})
                break

    return out


def normalize_for_cmp(s):
    return re.sub(r"[\s【】\[\]()（）|｜·：:，,。、'\"\-—~]", "", s or "").lower()


def match_items(art, items_main, items_nt):
    """将一篇文章匹配到现有条目（主表优先，专栏其次）"""
    at = normalize_for_cmp(art.get("title", ""))
    toks = company_tokens(art.get("title", ""))
    results = []  # (kind, item, score)

    for kind, items in (("main", items_main), ("notime", items_nt)):
        for it in items:
            it_t = normalize_for_cmp(it.get("title", ""))
            if not it_t:
                continue
            score = 0.0
            # 1) 标题整体相似度（作为辅助，单独不足以判同一单位）
            ratio = difflib.SequenceMatcher(None, at, it_t).ratio()
            # 2) 单位实体命中（双向子串匹配，实体长度≥2且非泛词）
            ent_hit = 0
            for tk in set(toks):
                if len(tk) >= 2 and tk in it_t:
                    ent_hit = max(ent_hit, min(len(tk), 10))
            for tk in set(company_tokens(it.get("title", ""))):
                if len(tk) >= 2 and tk in at:
                    ent_hit = max(ent_hit, min(len(tk), 10))
            if ent_hit >= 3:
                # 实体词越长越可信：3字→0.80，6字→0.88，10字→0.95
                score = min(0.95, 0.72 + ent_hit * 0.025)
            elif ent_hit == 2:
                score = 0.70   # 仅2字实体，需标题相似度高才采信
                score = 0.70 if ratio >= 0.6 else 0.55
            # 3) 标题高度相似（同文改写）也可采信
            if ratio >= 0.72:
                score = max(score, 0.80)
            if score >= MATCH_THRESHOLD:
                results.append((kind, it, round(score, 3)))

    results.sort(key=lambda x: -x[2])
    # 同类只取最高分一条，防一篇文章误配多条
    seen_kind = {}
    final = []
    for kind, it, sc in results:
        if kind in seen_kind:
            continue
        seen_kind[kind] = True
        final.append((kind, it, sc))
    return final


def fmt_ts(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except Exception:
        return ""


def main():
    dry = "--dry" in sys.argv
    D = load(WX)
    arts = [a for a in D.get("articles", []) if a.get("fetched") and a.get("body_text")]
    jobs = load(JOBS)
    ntd = load(NT)
    items_main, items_nt = jobs["items"], ntd["items"]

    print(f"公众号文章 {len(arts)} 篇 ｜ 主表 {len(items_main)} 条 ｜ 专栏 {len(items_nt)} 条\n")

    revisions = []
    matched_arts = 0

    for art in arts:
        times = extract_times(art)
        if not times.get("talk_date"):
            continue
        matches = match_items(art, items_main, items_nt)
        if not matches:
            continue
        matched_arts += 1
        src = {
            "source_title": art.get("title", ""),
            "source_url": art.get("url", ""),
            "source_publish": art.get("publish_time") or fmt_ts(art.get("publish_ts")),
            "extract_from": times.get("talk_from", ""),
        }
        for kind, it, score in matches:
            url = it.get("url", "")
            old_time = (it.get("time") or "").strip()          # 主表 = 举办时间
            old_talk = (it.get("talk_time") or "").strip()     # 专栏补注的宣讲时间
            new_talk = times.get("talk_time", "")
            rec = None
            action = ""

            if kind == "notime":
                # 专栏：缺宣讲时间则补充
                if new_talk and new_talk != old_talk:
                    action = "supplement"
                    rec = {
                        "url": url, "item_title": it.get("title", ""),
                        "action": action, "field": "宣讲时间",
                        "old": old_talk or "（未注明）", "new": new_talk,
                        **src, "match_score": score,
                        "revised_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    it["talk_time"] = new_talk
                    if times.get("deadline"):
                        it["deadline"] = times["deadline"]
                    if times.get("place") and not (it.get("place_extracted") or "").strip():
                        it["place_extracted"] = times["place"]
                    it["revision"] = {**src, "action": action}
            else:
                # 主表：核对现有举办时间（以公众号最新发布为准）
                if new_talk:
                    d_old = re.sub(r"^(\d{4}-\d{2}-\d{2}).*", r"\1", old_time)
                    d_new = times.get("talk_date", "")
                    if d_new:
                        if d_old and d_new != d_old:
                            # 冲突：以公众号为准，修正日期
                            action = "correct"
                            rec = {
                                "url": url, "item_title": it.get("title", ""),
                                "action": action, "field": "宣讲时间",
                                "old": old_time, "new": new_talk,
                                "diff": (f"原记录举办日期 {d_old}，公众号发布为 {d_new}"
                                         f"（《{src['source_title'][:20]}》{src['source_publish'][:10]}），"
                                         f"以公众号最新发布为准"),
                                **src, "match_score": score,
                                "revised_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            it["time_original"] = old_time
                            it["time"] = new_talk
                        elif d_new == d_old and new_talk != old_time:
                            # 一致但公众号给出了更精确的时刻 → 补全
                            action = "refine"
                            rec = {
                                "url": url, "item_title": it.get("title", ""),
                                "action": action, "field": "宣讲时间",
                                "old": old_time, "new": new_talk,
                                "diff": f"日期一致，据公众号补充具体时刻（{times.get('talk_from','')}）",
                                **src, "match_score": score,
                                "revised_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            it["time"] = new_talk
                        elif d_new == d_old:
                            # 完全一致 → 交叉确认
                            action = "confirm"
                            rec = {
                                "url": url, "item_title": it.get("title", ""),
                                "action": action, "field": "宣讲时间",
                                "old": old_time, "new": new_talk,
                                **src, "match_score": score,
                                "revised_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        # 补充字段（截止 / 地点 / 笔试面试）
                        for k, label in (("deadline", "报名截止"), ("place", "地点"), ("exam", "笔试面试")):
                            if times.get(k) and not it.get(k):
                                it[k] = times[k]
                        it["revision"] = {**src, "action": action,
                                          "note": rec.get("diff", "")}
            if rec:
                revisions.append(rec)
                mark = {"supplement": "补充", "correct": "修正", "confirm": "确认",
                        "refine": "补全时刻"}.get(action, action)
                print(f"  [{mark}] {it.get('title','')[:34]}")
                print(f"        {rec['old']} → {rec.get('new','')}  ←《{src['source_title'][:26]}》({src['source_publish'][:10]})")
                if rec.get("diff"):
                    print(f"        差异: {rec['diff']}")

    print(f"\n匹配到条目的文章 {matched_arts} 篇，产生修订记录 {len(revisions)} 条")
    from collections import Counter
    print("动作分布:", Counter(r["action"] for r in revisions).most_common())

    if dry:
        print("(--dry 模式，不落盘)")
        return

    save(REV, {"revised_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "source_account": D.get("account", ""),
               "count": len(revisions), "revisions": revisions})
    save(JOBS, jobs)
    save(NT, ntd)
    print(f"已写入 {REV} 并回写 jobs.json / jobs_notime.json")


if __name__ == "__main__":
    main()
