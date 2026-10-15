# -*- coding: utf-8 -*-
"""把待联网清单按优先级排序并切成 N 个分片，供并行检索使用。

自动排除已有结果的条目：
  - data/deadlines_local.json（公告原文已提取出截止时间）
  - data/web/res_*.json（历次联网检索已命中，含招满即止类）
因此重复运行本脚本只会产出「仍未覆盖」的清单。
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TODO = os.path.join(ROOT, "data", "deadline_todo.json")
DIR = os.path.join(ROOT, "data", "web")

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 480

os.makedirs(DIR, exist_ok=True)
todo = json.load(open(TODO, encoding="utf-8"))

# ---------- 收集已覆盖的 key ----------
covered = set()
L = os.path.join(ROOT, "data", "deadlines_local.json")
if os.path.exists(L):
    loc = json.load(open(L, encoding="utf-8"))
    for kind in ("main", "notime"):
        covered |= set((loc.get(kind) or {}).keys())
for p in glob.glob(os.path.join(DIR, "res_*.json")):
    try:
        arr = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    covered |= {r["key"] for r in arr if r.get("key")}

skip = len(covered)
todo = [x for x in todo if x["key"] not in covered]


def dkey(x):
    s = re.sub(r"\D", "", x.get("date") or "")[:8]
    return int(s) if s else 0


# 主表优先 + 日期倒序
todo.sort(key=lambda x: (0 if x["kind"] == "main" else 1, -dkey(x)))
sel = todo[:LIMIT]
print("已覆盖 %d 条，剩余待查 %d，本批取 %d（main %d / notime %d）" % (
    skip, len(todo), len(sel),
    sum(1 for x in sel if x["kind"] == "main"),
    sum(1 for x in sel if x["kind"] == "notime")))

buckets = [[] for _ in range(N)]
for i, x in enumerate(sel):
    buckets[i % N].append(x)

for i, b in enumerate(buckets):
    p = os.path.join(DIR, "todo_%d.json" % i)
    json.dump(b, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("todo_%d.json: %d 条" % (i, len(b)))
