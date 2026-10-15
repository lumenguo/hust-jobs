# -*- coding: utf-8 -*-
"""
增量更新：对比源站列表与本地数据，抓取新增招聘信息并重新生成 HTML。

用法:
  python update.py            # 增量检查并更新（默认扫前 3 页）
  python update.py --check    # 只检查是否有更新，不写入
  python update.py --full     # 全量比对（扫全部页，可识别已下线条目）
"""
import os
import re
import sys
import time
import json

from crawl import fetch, parse_list, BASE, START
import reparse
from reparse import ROOT, RAW_DIR, DATA_FILE, parse_one, load, save

STATE_FILE = os.path.join(ROOT, "data", "state.json")
CHECK_PAGES = 3


def raw_filename(url):
    tail = url.split("job.hust.edu.cn/")[-1]
    return re.sub(r"[^\w\-.]", "_", tail)[:80] + ".html"


def fetch_list(pages=CHECK_PAGES):
    """抓取源站列表前 N 页"""
    first = fetch(START)
    if not first:
        raise RuntimeError("无法访问源站列表页")
    items, total, max_page = parse_list(first)
    pages = min(pages, max_page) if pages else max_page
    for p in range(2, pages + 1):
        t = fetch(f"{BASE}/searchJob_{p}.do?type=0&fbsj=0")
        if t:
            items.extend(parse_list(t)[0])
    return items, total, max_page


def find_new(data, list_items):
    """找出本地没有的条目（按 URL 与 标题+时间 双重判重）"""
    known_url = {it["url"] for it in data["items"]}
    known_key = {(it["title"], it.get("time")) for it in data["items"]}
    new, seen = [], set()
    for it in list_items:
        key = (it["title"], it.get("time"))
        if it["url"] in known_url or key in known_key or key in seen:
            continue
        seen.add(key)
        new.append(it)
    return new


def enrich(item, verbose=True):
    """下载详情页原始 HTML 并解析出正文/元信息"""
    t = fetch(item["url"])
    if not t:
        return False
    fn = raw_filename(item["url"])
    with open(os.path.join(RAW_DIR, fn), "w", encoding="utf-8") as f:
        f.write(t)
    item["raw"] = "raw/" + fn
    body, text, meta, n_img = parse_one(os.path.join(RAW_DIR, fn), item["url"], verbose)
    item["body"] = body
    item["body_text_len"] = len(text)
    if meta:
        item["meta"] = meta
    if "job.hust.edu.cn" not in item["url"] and "weixin" in item["url"]:
        item["external"] = True
    return True


def rebuild_html():
    """重新生成 HTML 报告（子进程执行，避免模块级副作用）"""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "build_html.py")],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("[build_html 失败]", r.stderr[-500:])
    elif r.stdout.strip():
        print("  " + r.stdout.strip())
    return r.returncode == 0


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    json.dump(st, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def check(pages=CHECK_PAGES, use_cache=True, cache_sec=60):
    """快速检查是否有更新。带 60 秒缓存，避免频繁打源站。"""
    data = load()
    st = load_state()
    if use_cache and st.get("last_check") and "result" in st:
        # 缓存需同时满足：未过期、且本地条目数与缓存时一致（否则判为失效）
        fresh = time.time() - st["last_check"] < cache_sec
        same = st["result"].get("local_count") == len(data["items"])
        if fresh and same:
            r = dict(st["result"])
            r["cached"] = True
            return r
    try:
        list_items, total, max_page = fetch_list(pages)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    new = find_new(data, list_items)
    result = {
        "ok": True,
        "has_update": len(new) > 0,
        "new_count": len(new),
        "new_titles": [n["title"] for n in new[:20]],
        "site_total": total,
        "local_count": len(data["items"]),
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    st["last_check"] = time.time()
    st["result"] = result
    save_state(st)
    return result


def crawl_notime():
    """增量刷新「未注明宣讲时间」专栏（招聘信息栏目公告）"""
    import subprocess
    before = {}
    nf = os.path.join(ROOT, "data", "jobs_notime.json")
    if os.path.exists(nf):
        try:
            before = {i["url"] for i in json.load(open(nf, encoding="utf-8"))["items"]}
        except Exception:
            pass
    r = subprocess.run([sys.executable, os.path.join(ROOT, "crawl_notime.py")],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("[crawl_notime 失败]", (r.stderr or "")[-400:])
        return False
    after = {}
    if os.path.exists(nf):
        try:
            after = {i["url"] for i in json.load(open(nf, encoding="utf-8"))["items"]}
        except Exception:
            pass
    diff = len(after - before)
    if diff:
        print(f"  [专栏] 新增 {diff} 条未注明宣讲时间的公告")
    else:
        print("  [专栏] 无新增公告")
    return True


def refresh_deadlines():
    """重新核对简历投递截止时间：公告原文提取 + 合并已抓取的联网核对结果"""
    import subprocess
    dl = os.path.join(ROOT, "data", "deadlines.json")

    def _load():
        try:
            return json.load(open(dl, encoding="utf-8"))
        except Exception:
            return {}

    before = _load()
    # deadline_local.py 必须带 --save：否则不落盘 deadlines_local.json /
    # deadline_todo.json，新增条目既不会被提取，也不会进入待联网队列
    for script in (("deadline_local.py", "--save"), "merge_deadlines.py"):
        cmd = [sys.executable, os.path.join(ROOT, script if isinstance(script, str) else script[0])]
        if not isinstance(script, str):
            cmd += script[1:]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print("[%s 失败]" % script, (r.stderr or "")[-400:])
            return {"total": len(before), "changed": False,
                    "date": 0, "ongoing": 0}
    after = _load()
    n_date = sum(1 for v in after.values() if v.get("date"))
    n_ong = len(after) - n_date
    # 按内容比对（条数不变但类型可能从 ongoing 变成具体日期）
    changed = (json.dumps(before, sort_keys=True, ensure_ascii=False)
               != json.dumps(after, sort_keys=True, ensure_ascii=False))
    if changed:
        print(f"  [投递截止核对] 命中条目 {len(before)} → {len(after)} 条"
              f"（具体日期 {n_date} · 招满即止 {n_ong}）")
    else:
        print(f"  [投递截止核对] 无变化（具体日期 {n_date} · 招满即止 {n_ong}）")
    return {"total": len(after), "changed": changed, "date": n_date, "ongoing": n_ong}


def revise_by_wechat():
    """用公众号文章核对/修订现有条目时间信息"""
    import subprocess
    wx = os.path.join(ROOT, "data", "wechat_articles.json")
    if not os.path.exists(wx):
        return 0
    rf = os.path.join(ROOT, "data", "revisions.json")
    try:
        before = len(json.load(open(rf, encoding="utf-8")).get("revisions", []))
    except Exception:
        before = 0
    r = subprocess.run([sys.executable, os.path.join(ROOT, "revise.py")],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("[revise 失败]", (r.stderr or "")[-400:])
        return 0
    try:
        after = len(json.load(open(rf, encoding="utf-8")).get("revisions", []))
    except Exception:
        after = 0
    if after != before:
        print(f"  [公众号核对] 修订记录 {before} → {after} 条")
    return after


def apply(pages=CHECK_PAGES, full=False):
    """执行更新：抓新增条目 -> 合并 -> 保存 -> 重建 HTML"""
    data = load()
    list_items, total, max_page = fetch_list(pages if not full else None)
    new = find_new(data, list_items)

    added, removed = [], []
    if new:
        print(f"发现 {len(new)} 条新信息，开始抓取详情…")
        for it in new:
            ok = enrich(it)
            print(f"  {'+' if ok else 'x'} {it['title'][:40]}")
            if ok:
                added.append(it)
        if added:
            data["items"] = added + data["items"]

    if full:
        live = {it["url"] for it in list_items}
        removed = [it["title"] for it in data["items"] if it["url"] not in live]
        data["items"] = [it for it in data["items"] if it["url"] in live]
        if removed:
            print(f"清理已下线条目 {len(removed)} 条")

    # 专栏二（未注明宣讲时间）独立增量刷新
    notime_ok = crawl_notime()

    # 公众号信息源核对修订（补充/修正宣讲时间，冲突以公众号为准）
    rev_n = revise_by_wechat()

    # 先落盘：截止时间提取脚本是从 jobs.json 读条目的，
    # 若放到后面保存，本次新增的条目要等下一轮才补上截止时间
    data["count"] = len(data["items"])
    data["total"] = total or data.get("total")
    if added or removed:
        data["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        data["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save(data)

    # 简历投递截止时间重新核对（公告原文提取 + 已抓取的联网核对结果）
    dl = refresh_deadlines()

    if added or removed or notime_ok or dl["changed"]:
        rebuild_html()
    if added or removed:
        print(f"已更新并重建 HTML：新增 {len(added)} 条，共 {len(data['items'])} 条")
    elif dl["changed"]:
        print("已更新并重建 HTML：投递截止时间数据有变化")

    result = {
        "ok": True,
        "added": len(added),
        "removed": len(removed),
        "added_titles": [a["title"] for a in added],
        "count": len(data["items"]),
        "updated_at": data.get("last_update") or data.get("last_check"),
        "deadlines": dl,
        "rebuilt": bool(added or removed or notime_ok or dl["changed"]),
    }
    st = load_state()
    st["last_check"] = time.time()
    st["result"] = {"ok": True, "has_update": False, "new_count": 0,
                    "new_titles": [], "site_total": total,
                    "local_count": len(data["items"]),
                    "checked_at": result["updated_at"]}
    save_state(st)
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        print(json.dumps(check(), ensure_ascii=False, indent=1))
    else:
        r = apply(full=("--full" in args))
        print(json.dumps(r, ensure_ascii=False, indent=1))
