# -*- coding: utf-8 -*-
"""
华中科技大学就业信息网「招聘信息」栏目爬虫（无宣讲时间的公告类）。

主报告收录的是宣讲会列表（searchJob type=0，均带举办时间）；
本脚本抓取 /zpxx123123/ 招聘信息栏目的公告（网申/简章类，通常不注明宣讲时间），
单独存入 data/jobs_notime.json，供报告「未注明宣讲时间」专栏使用。

  python crawl_notime.py            # 增量抓取（默认从第1页抓到 2026-09-01 之前）
  python crawl_notime.py --full     # 全量重抓（会保留已抓过的详情缓存）
"""
import os
import re
import json
import time
import html
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from crawl import fetch, BASE

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(ROOT, "raw", "notime")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RAW_DIR, exist_ok=True)

LIST_URL = BASE + "/zpxx123123/index{}.htm"  # "" / "_2" / "_3" ...
CUTOFF = "2026-09-01"      # 与主表时间窗对齐，早于此日期的公告不收录
MAX_PAGES = 40             # 安全上限
UA_HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse_list(text):
    """解析 nytzlist：<li><h4><a href>title</a></h4><time>[date]</time></li>"""
    items = []
    for m in re.finditer(
        r'(?is)<li>\s*<h4>\s*<a href="([^"]+)"[^>]*>(.*?)</a>\s*</h4>\s*<time>\s*\[?([\d\-]+)\]?\s*</time>',
        text):
        href, title, date = m.groups()
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", title))).strip()
        items.append({
            "title": title,
            "date": date.strip(),
            "url": urllib.parse.urljoin(BASE, href),
        })
    return items


def fetch_list():
    """逐页抓列表，直到发布日期早于 CUTOFF 或达到 MAX_PAGES"""
    all_items, seen = [], set()
    for p in range(1, MAX_PAGES + 1):
        url = LIST_URL.format("" if p == 1 else f"_{p}")
        t = fetch(url)
        if not t:
            print(f"  第{p}页抓取失败，停止")
            break
        got = parse_list(t)
        if not got:
            break
        new = [it for it in got if it["url"] not in seen]
        for it in new:
            seen.add(it["url"])
        all_items.extend(new)
        oldest = min((it["date"] for it in got), default="")
        print(f"  第{p}页: {len(got)} 条（本页最早 {oldest}）")
        if oldest and oldest < CUTOFF:
            break
        time.sleep(0.3)
    # 过滤掉过早的
    kept = [it for it in all_items if it["date"] >= CUTOFF]
    return kept


def parse_detail(text):
    """解析招聘信息详情页：发布时间 + 正文 + 元信息"""
    meta = {}
    m = re.search(r'(?is)<div class="time">(.*?)</div>', text)
    if m:
        mm = re.search(r"发布时间[:：]\s*([\d\-]+)", re.sub(r"<[^>]+>", " ", m.group(1)))
        if mm:
            meta["发布日期"] = mm.group(1)
    body = ""
    for pat in [
        r'(?is)<div class="arc-con[^"]*">(.*?)<div class="contact"',
        r'(?is)<div class="arc-con[^"]*">(.*)',
    ]:
        m = re.search(pat, text)
        if m and len(re.sub(r"<[^>]+>", "", m.group(1)).strip()) > 100:
            body = m.group(1)
            break
    if not body:
        m = re.search(r'(?is)<div class="txt">(.*?)</div>\s*</div>', text)
        if m:
            body = m.group(1)
    # 清理
    body = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<!--.*?-->", "", body)
    # 图片绝对化 + 去属性
    def _img(mm):
        tag = mm.group(0)
        src = re.search(r'src="([^"]+)"', tag)
        if src:
            u = src.group(1)
            if not u.startswith(("http", "data:")):
                tag = tag.replace(u, urllib.parse.urljoin(BASE, u))
        return tag
    body = re.sub(r"(?is)<img[^>]*>", _img, body)
    return body, meta


def mentions_talk_time(body, title):
    """公告正文是否注明了具体宣讲/见面会时间"""
    b = body or ""
    if re.search(r"(?is)(宣讲会|见面会|双选会|招聘会)[^。]{0,60}\d{4}\s*[-年]\s*\d{1,2}\s*[月-]\s*\d{1,2}", b):
        return True
    if re.search(r"(?is)\d{1,2}\s*月\s*\d{1,2}\s*日[^。]{0,40}(宣讲|见面会)", b):
        return True
    if re.search(r"(?is)(时间|地点)[:：].{0,40}(宣讲|报告厅|活动中心)", b):
        return False  # 形如"时间地点另行通知"不算注明
    return False


def raw_filename(url):
    tail = url.split("job.hust.edu.cn/")[-1]
    return re.sub(r"[^\w\-.]", "_", tail)[:80] + ".html"


def enrich(item):
    """站内详情页才抓正文；站外链接（微信/政府网等）只保留标题与链接"""
    if "job.hust.edu.cn" not in item["url"]:
        item["external"] = True
        return False
    t = fetch(item["url"])
    if not t:
        return False
    fn = raw_filename(item["url"])
    with open(os.path.join(RAW_DIR, fn), "w", encoding="utf-8") as f:
        f.write(t)
    body, meta = parse_detail(t)
    item["raw"] = "raw/notime/" + fn
    item["body"] = body
    if meta:
        item["meta"] = meta
    if not item.get("date") and meta.get("发布日期"):
        item["date"] = meta["发布日期"]
    return True


def main():
    full = "--full" in os.sys.argv if hasattr(os, "sys") else "--full" in __import__("sys").argv
    out = os.path.join(DATA_DIR, "jobs_notime.json")
    old = {}
    if os.path.exists(out):
        try:
            old = {i["url"]: i for i in json.load(open(out, encoding="utf-8"))["items"]}
        except Exception:
            old = {}

    print("== 抓取「招聘信息」列表 ==")
    items = fetch_list()
    print(f"列表合计: {len(items)} 条（>= {CUTOFF}）")

    # 增量：已抓过且详情成功的跳过
    todo = [it for it in items if not (full is False and old.get(it["url"], {}).get("body"))]
    print(f"需抓详情: {len(todo)} 条（已有缓存 {len(items) - len(todo)} 条）")

    ok = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(enrich, it): it for it in todo}
        done = 0
        for f in as_completed(futs):
            it = futs[f]
            try:
                if f.result():
                    ok += 1
            except Exception as e:
                print("  [ERR]", it["title"][:30], e)
            done += 1
            if done % 20 == 0 or done == len(todo):
                print(f"  进度 {done}/{len(todo)}")

    # 合并旧缓存
    merged = {}
    for u, it in old.items():
        if u not in {x["url"] for x in items} and full:
            continue  # 全量模式下丢弃已下线的
        merged[u] = it
    for it in items:
        if it.get("body") or it["url"] not in merged:
            merged[it["url"]] = it
    items = sorted(merged.values(), key=lambda x: (x.get("date") or ""), reverse=True)

    with open(out, "w", encoding="utf-8") as f:
        json.dump({"source": LIST_URL.format(""), "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "cutoff": CUTOFF, "count": len(items), "items": items},
                  f, ensure_ascii=False, indent=1)
    has_body = sum(1 for i in items if i.get("body"))
    print(f"已保存: {out}  共 {len(items)} 条（含正文 {has_body}，外链 {len(items) - has_body - sum(1 for i in items if not i.get('body'))}）")


if __name__ == "__main__":
    import sys
    main()
