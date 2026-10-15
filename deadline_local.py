# -*- coding: utf-8 -*-
"""
从华科就业网公告原文中提取「简历投递截止时间」。

思路：
  1. 正文/标题转纯文本，按句子切分
  2. 句子同时命中「投递类关键词」+「截止类关键词」→ 候选句
  3. 从候选句的「截止」之后取日期（区间取末端），缺省年份按条目发布日期推断
  4. 输出 data/deadlines_local.json，每条带原文依据（sentence）便于人工核对

用法：
  python deadline_local.py            # 统计 + 抽样预览
  python deadline_local.py --save     # 落盘
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(ROOT, "data", "jobs.json")
NT = os.path.join(ROOT, "data", "jobs_notime.json")
OUT = os.path.join(ROOT, "data", "deadlines_local.json")

# ---------- 日期正则 ----------
_D = (r"(?:(?P<y>\d{4})\s*[-年/.]\s*)?(?P<m>\d{1,2})\s*[月\-/.]\s*(?P<d>\d{1,2})\s*日?"
      r"(?:\s*[（(]\s*周[一二三四五六日天]\s*[)）]\s*)?"
      r"(?:\s*(?P<H>\d{1,2})\s*[:：]\s*(?P<M>\d{2}))?"
      r"(?:\s*[-—~至到]\s*(?P<H2>\d{1,2})\s*[:：]\s*(?P<M2>\d{2}))?")
RX_DT = re.compile(_D)

# 投递类：能表明是「投简历/网申」而非宣讲会本身
POS = re.compile(r"(简历|网申|网上申请|网投|投递|报名|申请|应聘|提交材料|意向登记|岗位申报|线上申请|注册)")
# 截止类
DEAD = re.compile(r"(截止|截至|结束|关闭|最后期限|deadline|Deadline|DEADLINE|前)")
# 明确指向宣讲会/宣讲本身的报名截止 → 不算简历投递截止
TALK_ONLY = re.compile(r"(宣讲会?|双选会|招聘会|空中宣讲|线下宣讲|讲座|分享会)")
# 「报名参会」「报名参会名额」这类是参会报名
JOIN = re.compile(r"(报名参会|参会报名|报名截止于宣讲|报名参?加?宣讲)")

TAG = re.compile(r"<[^>]+>")

# 「截止」类触发词（其后跟日期才算）
DEAD_PATS = [
    (r"(?:简历|网申|网上申请|网投|岗位)?\s*投递\s*截止\s*(?:时间|日期)?\s*[:：]?\s*", "投递截止"),
    (r"报名\s*截止\s*(?:时间|日期)?\s*[:：]?\s*", "报名截止"),
    (r"(?:网申|网上申请|简历接收|接收简历|应聘登记|简历提交)\s*(?:截止|截至)\s*(?:时间|日期)?\s*[:：]?\s*", "网申截止"),
    (r"(?:网申|投递|报名|申请)\s*(?:时间|日期)\s*[:：]?\s*", "投递区间"),
    (r"报名\s*(?:时间|日期)\s*[:：]?\s*", "报名区间"),
    (r"截止\s*(?:时间|日期)\s*[:：]?\s*", "截止时间"),
    (r"截至\s*(?:时间|日期)?\s*[:：]?\s*", "截至"),
    (r"(?:报名|投递|网申|申请)\s*(?:通道)?\s*(?:将于|于)?\s*", "通道关闭"),
]
# 「X月X日前投递/报名」式
BEFORE_PAT = re.compile(r"(?:于|在|请)?\s*(" + _D + r")\s*(?:\d{1,2}\s*[:：]\s*\d{2}\s*)?[点时]?\s*(?:之)?前\s*(?:完成)?\s*"
                        r"(?:投递|报名|网申|提交|申请|注册|登录|填报|填写|投递简历|提交简历)")
# 「即日起至 X」
FROMNOW_PAT = re.compile(r"(?:即日起|即日|自本公告发布之日(?:起)?)\s*(?:至|到|—|-|~)\s*(" + _D + r")")
# 附近出现这些词 → 说明该日期不是简历投递截止
NEAR_NEG = re.compile(r"(入职|报到|体检|取得.{0,12}(?:资格|毕业|学历|学位)|毕业时间|Offer|offer|发放|笔试|面试|测评|宣讲时间|宣讲会时间|宣讲会|双选会|招聘会|讲座|分享会|开奖|抽奖|投票|活动|专利|科研成果|年薪)")


def to_text(html):
    t = TAG.sub(" ", html or "")
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # 关键：正文常被「10月1 4 日」这样拆开数字，先合并数字间的空格
    t = re.sub(r"(?<=\d)[ \t\u3000]+(?=\d)", "", t)
    t = re.sub(r"[ \t\r\f\v\u3000]+", " ", t)
    return t


def sentences(text):
    return [s.strip() for s in re.split(r"[。；;\n\r]+", text) if s.strip()]


def norm(m, year):
    y = m.group("y") or year
    try:
        mo, d = int(m.group("m")), int(m.group("d"))
    except (TypeError, ValueError):
        return None, None, None
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None, None, None
    try:
        y = int(y)
    except ValueError:
        return None, None, None
    date_s = "%04d-%02d-%02d" % (y, mo, d)
    s = date_s
    if m.group("H"):
        h = int(m.group("H"))
        if h <= 24:
            s += " %02d:%s" % (h, m.group("M"))
    return s, date_s, (y, mo, d)


def guess_year(item_date, mo):
    """缺省年份：按条目发布/宣讲日期推断，跨年时 +1"""
    m = re.match(r"(\d{4})", item_date or "")
    y = int(m.group(1)) if m else 2026
    m2 = re.match(r"\d{4}-(\d{2})", item_date or "")
    if m2:
        try:
            im = int(m2.group(1))
        except ValueError:
            im = 1
        if mo < im - 6:      # 例如条目在 12 月、日期写 1 月 → 次年
            y += 1
        elif mo - im > 6:    # 条目在 1 月、日期写 12 月 → 去年（不合理，取同年）
            pass
    return y


def pick_date(seg, year):
    """取片段中第一个日期；若是「A 至 B」区间则取末端 B"""
    ms = list(RX_DT.finditer(seg))
    if not ms:
        return None
    m = ms[0]
    rest = seg[m.end():m.end() + 45]
    m2 = re.match(r"\s*(?:[-—~－至到])\s*(?![：:])", rest)
    if m2:
        m3 = RX_DT.search(rest, m2.end())
        if m3 and m3.group("m"):
            m = m3
    try:
        y = guess_year(year, int(m.group("m"))) if not m.group("y") else int(m.group("y"))
    except (TypeError, ValueError):
        y = year
    return norm(m, y)


LABEL_RANK = {
    "投递截止": 6, "报名截止": 6, "网申截止": 6, "前投递": 5,
    "截止时间": 4, "截至": 3, "投递区间": 2, "报名区间": 2, "即日起至": 2, "通道关闭": 1,
}


def plausible(ds, item_date):
    """截止日期合理性：不早于条目日期 10 天，且不晚于条目日期 240 天"""
    if not item_date:
        return True
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", item_date)
    if not m:
        return True
    try:
        import datetime
        a = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        mm = re.match(r"(\d{4})-(\d{2})-(\d{2})", ds)
        b = datetime.date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)))
        delta = (b - a).days
        return -10 <= delta <= 240
    except Exception:
        return True


def extract(item_date, texts):
    """texts: [(来源标签, 文本)]，返回 dict 或 None"""
    hits = []
    for src, text in texts:
        for pat, label in DEAD_PATS:
            for m in re.finditer(pat, text):
                seg = text[m.end():m.end() + 60]
                if NEAR_NEG.search(seg[:38]):
                    continue
                ctx = text[max(0, m.start() - 45):m.end() + 60]
                if not POS.search(ctx):
                    continue
                # 只有「报名/申请」且整段在说宣讲会/参会 → 是参会报名，不是简历投递
                if set(POS.findall(ctx)) <= {"报名", "申请"} and (TALK_ONLY.search(ctx) or JOIN.search(ctx)):
                    continue
                r = pick_date(seg, item_date)
                if not r:
                    continue
                s, ds, ymd = r
                hits.append({
                    "deadline": s, "date": ds, "source": src, "label": label,
                    "sentence": ctx[:170], "explicit_year": bool(re.search(r"\d{4}", seg[:20])),
                })
        for rx, label in ((BEFORE_PAT, "前投递"), (FROMNOW_PAT, "即日起至")):
            for m in rx.finditer(text):
                ctx = text[max(0, m.start() - 45):m.end() + 45]
                if NEAR_NEG.search(ctx):
                    continue
                try:
                    y = int(m.group("y")) if m.group("y") else guess_year(item_date, int(m.group("m")))
                except (TypeError, ValueError):
                    continue
                s, ds, ymd = norm(m, y)
                if not ds:
                    continue
                hits.append({
                    "deadline": s, "date": ds, "source": src, "label": label,
                    "sentence": ctx[:170], "explicit_year": bool(m.group("y")),
                })
    # 过滤：无有效日期 / 明显不合理的日期
    hits = [h for h in hits if h.get("date") and plausible(h["date"], item_date)]
    if not hits:
        return None
    order = {"正文": 2, "标题": 1, "摘要": 0}
    hits.sort(key=lambda h: (h["explicit_year"], LABEL_RANK.get(h["label"], 0),
                             order.get(h["source"], 0)), reverse=True)
    return hits[0]


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


NOISE = re.compile(r"(20\d\d\s*届|20\d\d\s*年|20\d\d|秋季|春季|校园招聘|秋招|春招|宣讲会|宣讲|双选会|"
                   r"招聘会|招聘公告|招聘简章|招聘启事|公告|简章|启事|正式启动|启动|来袭|官宣|"
                   r"[【】\[\]()（）|｜丨]|专场|邀请函|座谈|空中|线下|线上|全球|校招)")


def company_of(title):
    """从标题里洗出单位名（用于联网检索）"""
    t = re.split(r"[|｜丨]\s*", title or "")[0]
    t = NOISE.sub(" ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ·、,，。!！-—~ ")
    return t[:24]


def main():
    save = "--save" in sys.argv
    res = {"main": {}, "notime": {}}
    stat = {"main": [0, 0], "notime": [0, 0]}

    j = load(JOBS)
    for it in j["items"]:
        key = it.get("url") or it.get("title")
        stat["main"][1] += 1
        texts = [
            ("正文", to_text(it.get("body"))),
            ("标题", it.get("title") or ""),
        ]
        h = extract(it.get("time") or it.get("date"), texts)
        if h:
            h["title"] = it.get("title")
            h["item_date"] = it.get("time") or it.get("date")
            h["url"] = it.get("url")
            res["main"][key] = h
            stat["main"][0] += 1

    n = load(NT)
    for it in n["items"]:
        key = it.get("url") or it.get("title")
        stat["notime"][1] += 1
        texts = [
            ("正文", to_text(it.get("body"))),
            ("标题", it.get("title") or ""),
        ]
        h = extract(it.get("date") or (it.get("meta") or {}).get("发布日期"), texts)
        if h:
            h["title"] = it.get("title")
            h["item_date"] = it.get("date")
            h["url"] = it.get("url")
            res["notime"][key] = h
            stat["notime"][0] += 1

    print("主表 命中 %d / %d" % (stat["main"][0], stat["main"][1]))
    print("未注明专栏 命中 %d / %d" % (stat["notime"][0], stat["notime"][1]))

    if save:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("已写入", OUT)
        # 生成「待联网补充」清单
        todo = []
        got_main = set(res["main"].keys())
        for it in j["items"]:
            k = it.get("url") or it.get("title")
            if k in got_main:
                continue
            todo.append({"kind": "main", "key": k, "company": company_of(it.get("title")),
                         "title": it.get("title"), "url": it.get("url"),
                         "date": it.get("time") or it.get("date")})
        got_nt = set(res["notime"].keys())
        for it in n["items"]:
            k = it.get("url") or it.get("title")
            if k in got_nt:
                continue
            d = it.get("date") or ""
            if d < "2026-09-01":      # 较早的公告，投递窗口大概率已过，不占用联网预算
                continue
            todo.append({"kind": "notime", "key": k, "company": company_of(it.get("title")),
                         "title": it.get("title"), "url": it.get("url"), "date": d})
        tp = os.path.join(ROOT, "data", "deadline_todo.json")
        with open(tp, "w", encoding="utf-8") as f:
            json.dump(todo, f, ensure_ascii=False, indent=1)
        print("待联网补充 %d 条 -> %s" % (len(todo), tp))
    else:
        print("\n--- 主表样本 ---")
        for i, (k, v) in enumerate(list(res["main"].items())[:25]):
            print("%s | %s | %s\n   %s" % (v["date"], v["source"], v["title"][:40], v["sentence"][:110]))
        print("\n--- 专栏样本 ---")
        for i, (k, v) in enumerate(list(res["notime"].items())[:15]):
            print("%s | %s | %s\n   %s" % (v["date"], v["source"], v["title"][:40], v["sentence"][:110]))


if __name__ == "__main__":
    main()
