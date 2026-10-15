# -*- coding: utf-8 -*-
"""
华中科技大学就业信息网 招聘信息爬虫
目标: https://job.hust.edu.cn/searchJob.do?type=0&fbsj=0
输出: data/jobs.json + raw/ 原始详情页
"""
import os
import re
import json
import time
import html
import ssl
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

ssl._create_default_https_context = ssl._create_unverified_context

BASE = "https://job.hust.edu.cn"
START = "https://job.hust.edu.cn/searchJob.do?type=0&fbsj=0"
ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(ROOT, "raw")
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": START,
}


def fetch(url, retries=3, timeout=30):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            for enc in ("utf-8", "gb18030"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:
            if i == retries - 1:
                print(f"  [FAIL] {url}: {e}")
                return None
            time.sleep(1.5 * (i + 1))
    return None


# ---------------- 列表页 ----------------
def parse_list(text):
    """解析列表页，返回 (items, total, max_page)"""
    items = []
    # 每条: <li><span class="n1"><a href=".." title="..">..</a></span><span class="n2">时间</span><span class="n3">地点</span></li>
    for m in re.finditer(
        r'<span class="n1">\s*<a href="([^"]+)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<span class="n2">(.*?)</span>\s*<span class="n3">(.*?)</span>',
        text, re.S):
        href, title, _t, tm, place = m.groups()
        items.append({
            "title": html.unescape(title).strip(),
            "time": re.sub(r"\s+", " ", html.unescape(tm)).strip(),
            "place": re.sub(r"\s+", " ", html.unescape(place)).strip(),
            "url": urllib.parse.urljoin(BASE, href),
        })
    total = None
    mt = re.search(r"共(\d+)条记录", text)
    if mt:
        total = int(mt.group(1))
    max_page = 1
    mp = re.findall(r'searchJob_?(\d*)\.do\?type=0&fbsj=0[^"]*">末页', text)
    if not mp:
        mp = re.findall(r'href="searchJob_(\d+)\.do', text)
    if mp:
        max_page = max(int(x) for x in mp if x)
    return items, total, max_page


# ---------------- 详情页 ----------------
def clean_html(fragment):
    """清洗正文: 去 script/style, 图片转绝对地址"""
    fragment = re.sub(r"(?is)<script.*?</script>", "", fragment)
    fragment = re.sub(r"(?is)<style.*?</style>", "", fragment)
    fragment = re.sub(r"(?is)<!--.*?-->", "", fragment)
    # 图片 src 绝对化
    def _img(m):
        tag = m.group(0)
        src = re.search(r'src="([^"]+)"', tag)
        if src:
            new = urllib.parse.urljoin(BASE, src.group(1))
            tag = tag.replace(src.group(1), new)
        if "onerror" not in tag:
            tag = tag.replace("<img", '<img loading="lazy" onerror="this.style.display=\'none\'"', 1)
        return tag
    fragment = re.sub(r"(?is)<img[^>]*>", _img, fragment)
    # 链接绝对化
    def _a(m):
        tag = m.group(1)
        href = re.search(r'href="([^"]+)"', tag)
        if href and not href.group(1).startswith(("http", "#", "mailto", "javascript")):
            tag = tag.replace(href.group(1), urllib.parse.urljoin(BASE, href.group(1)))
        return "<a" + tag + ">" if not tag.endswith("/") else "<a" + tag + "/>"
    fragment = re.sub(r"(?is)<a(\s[^>]*)>", _a, fragment)
    return fragment.strip()


def extract_body(text):
    """提取详情页正文 HTML 与元信息"""
    # 元信息表
    meta = {}
    for m in re.finditer(
        r"<(?:td|th|span|div)[^>]*>\s*([^<>]{2,12})\s*[:：]\s*</(?:td|th|span|div)>\s*"
        r"<(?:td|span|div)[^>]*>(.*?)</(?:td|span|div)>", text, re.S):
        k = re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", m.group(1))))
        v = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        if k and v and len(k) <= 12 and k not in meta:
            meta[k] = v[:200]

    body = ""
    # 优先 arc-con / content / txt 容器
    for pat in [
        r'(?is)<div class="arc-con[^"]*">(.*?)<div class="clear"',
        r'(?is)<div class="arc-con[^"]*">(.*)',
        r'(?is)<div class="content">(.*?)<div class="clear"',
        r'(?is)<div class="txt">(.*)',
    ]:
        m = re.search(pat, text)
        if m and len(m.group(1)) > 200:
            body = m.group(1)
            break
    if not body:
        m = re.search(r"(?is)<body[^>]*>(.*)</body>", text)
        body = m.group(1) if m else text

    # 截断尾部无关块
    cut_markers = ['<div class="footer', '<div class="contact"', 'footer clearfix']
    low = body
    for cm in cut_markers:
        idx = low.find(cm)
        if idx > 500:
            body = body[:idx]
            break
    body = re.sub(r"(?is)</?(div|ul|li|table|tbody|tr)\s*>\s*(?=</?(div|ul|li|table|tbody|tr)\s*>)", "", body)
    return clean_html(body), meta


def main():
    print("== 抓取列表页 ==")
    first = fetch(START)
    items, total, max_page = parse_list(first)
    if not items:
        raise SystemExit("列表解析失败，请检查页面结构")
    print(f"第1页: {len(items)} 条 | 总记录 {total} | 总页数 {max_page}")

    page_urls = [START] + [f"{BASE}/searchJob_{p}.do?type=0&fbsj=0" for p in range(2, max_page + 1)]

    def get_page(u):
        t = fetch(u)
        return parse_list(t)[0] if t else []

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(get_page, u): i + 1 for i, u in enumerate(page_urls[1:], start=2)}
        for f in as_completed(futs):
            p = futs[f]
            got = f.result()
            print(f"第{p}页: {len(got)} 条")
            items.extend(got)

    # 按页码顺序重建（保证顺序）
    seen, ordered = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        ordered.append(it)
    items = ordered
    print(f"列表合计: {len(items)} 条 (去重后)")

    print("\n== 抓取详情页 ==")
    def get_detail(args):
        idx, it = args
        t = fetch(it["url"])
        if not t:
            return idx, None
        fn = re.sub(r"[^\w\-.]", "_", it["url"].split("job.hust.edu.cn/")[-1])[:80] + ".html"
        with open(os.path.join(RAW_DIR, fn), "w", encoding="utf-8") as fp:
            fp.write(t)
        body, meta = extract_body(t)
        return idx, {"body": body, "meta": meta, "raw": "raw/" + fn}

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(get_detail, (i, it)) for i, it in enumerate(items)]
        done = 0
        for f in as_completed(futs):
            idx, res = f.result()
            if res:
                items[idx].update(res)
            done += 1
            if done % 20 == 0 or done == len(items):
                print(f"  进度 {done}/{len(items)}")

    ok = sum(1 for it in items if it.get("body"))
    print(f"详情抓取成功: {ok}/{len(items)}")

    with open(os.path.join(DATA_DIR, "jobs.json"), "w", encoding="utf-8") as fp:
        json.dump({"source": START, "total": total, "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "count": len(items), "items": items}, fp, ensure_ascii=False, indent=1)
    print("\n数据已保存: data/jobs.json")


if __name__ == "__main__":
    import urllib.parse  # noqa
    main()
