# -*- coding: utf-8 -*-
"""
合并「简历投递截止时间」数据源 → data/deadlines.json

数据源优先级：
  1. local —— 就业网公告原文自动提取（带原句依据，最权威）
  2. web   —— 联网检索补充（企业官网/第三方平台），仅补充本地未覆盖的条目

输出结构：{ "<条目url>": {date, source, label, evidence, source_url, source_name, confidence} }
"""
import glob
import json
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(ROOT, "data", "deadlines_local.json")
WEBDIR = os.path.join(ROOT, "data", "web")
JOBS = os.path.join(ROOT, "data", "jobs.json")
NT = os.path.join(ROOT, "data", "jobs_notime.json")
OUT = os.path.join(ROOT, "data", "deadlines.json")

SRC_LABEL = {"local": "公告原文", "web": "联网核对"}


def valid(d):
    return bool(re.match(r"^20\d\d-\d\d-\d\d$", d or ""))


def main():
    merged = {}
    stat = Counter()

    # ---------- 1. 本地原文提取 ----------
    if os.path.exists(LOCAL):
        L = json.load(open(LOCAL, encoding="utf-8"))
        for kind in ("main", "notime"):
            for url, h in (L.get(kind) or {}).items():
                if not valid(h.get("date")):
                    continue
                merged[url] = {
                    "date": h["date"],
                    "time": h.get("deadline", ""),
                    "source": "local",
                    "label": h.get("label", ""),
                    "evidence": (h.get("sentence") or "")[:200],
                    "item_kind": kind,
                }
                stat["local_" + kind] += 1

    # ---------- 2. 联网检索结果 ----------
    for p in sorted(glob.glob(os.path.join(WEBDIR, "res_*.json"))):
        try:
            arr = json.load(open(p, encoding="utf-8"))
        except Exception:
            print("跳过坏文件", os.path.basename(p))
            continue
        for r in arr:
            k = (r.get("key") or "").strip()
            rtype = (r.get("type") or ("ongoing" if r.get("note") and not r.get("deadline") else "date"))
            d = (r.get("deadline") or "").strip()
            if not k:
                continue
            if rtype == "ongoing":
                if k in merged:
                    stat["web_dup"] += 1
                    continue
                merged[k] = {
                    "date": "",
                    "type": "ongoing",
                    "note": (r.get("note") or "招满即止/尽快投递").strip(),
                    "source": "web",
                    "label": r.get("source_name", ""),
                    "evidence": "",
                    "source_url": r.get("source", ""),
                    "confidence": r.get("confidence", "mid"),
                }
                stat["ongoing"] += 1
                continue
            if not valid(d):
                continue
            if k in merged:            # 本地原文已覆盖，保留原文依据
                stat["web_dup"] += 1
                continue
            merged[k] = {
                "date": d,
                "time": r.get("deadline_text", ""),
                "source": "web",
                "label": r.get("source_name", ""),
                "evidence": "",
                "source_url": r.get("source", ""),
                "confidence": r.get("confidence", "mid"),
            }
            stat["web"] += 1

    # ---------- 3. 校验：key 必须真实存在于条目中 ----------
    j = json.load(open(JOBS, encoding="utf-8"))
    n = json.load(open(NT, encoding="utf-8"))
    urls = {i.get("url") for i in j["items"]} | {i.get("url") for i in n["items"]}
    orphan = [k for k in merged if k not in urls]
    for k in orphan:
        merged.pop(k, None)
    if orphan:
        print("剔除无效 key（不在条目中）：%d" % len(orphan))

    # ---------- 4. 分布预览 ----------
    by = Counter(v["date"] for v in merged.values())
    n_ong = sum(1 for v in merged.values() if not v.get("date"))
    print("合并完成：本地原文 %d 条，联网补充 %d 条（其中招满即止 %d 条），重复跳过 %d 条"
          % (stat["local_main"] + stat["local_notime"], stat["web"], stat["ongoing"], stat["web_dup"]))
    print("命中条目合计 %d 条（具体截止日期 %d · 招满即止 %d）" % (len(merged), len(merged) - n_ong, n_ong))
    print("\n截止日期分布（Top 25）：")
    for d, c in sorted(by.items()):
        if d < "2026-09-01":
            continue
        print("  %s  %3d %s" % (d, c, "#" * min(c, 60)))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    print("\n已写入", OUT)


if __name__ == "__main__":
    main()