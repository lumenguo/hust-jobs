# -*- coding: utf-8 -*-
"""
抓取微信公众号「华中科技大学就业指导与服务中心」发布的招聘类文章。

路径：搜狗微信搜索（文章接口）→ 过滤来源公众号 → 解析 /link 跳转拿真实文章URL
     → 抓取 mp.weixin.qq.com 正文 → 提取时间/地点信息 → data/wechat_articles.json

反爬对策：cookie 会话、随机延时、antispider 检测退避、断点续抓（已有 URL 不重复抓）。
用法：
  python crawl_wechat.py search   # 第一步：搜索并解析所有真实URL
  python crawl_wechat.py fetch    # 第二步：抓取文章正文
  python crawl_wechat.py all      # 全流程
"""
import json
import os
import random
import re
import ssl
import sys
import time
import html as HTML
import http.cookiejar
import urllib.parse
import urllib.request

ssl._create_default_https_context = ssl._create_unverified_context

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(ROOT, "raw", "wechat")
DATA = os.path.join(ROOT, "data", "wechat_articles.json")
TARGET_ACCOUNT = "华中科技大学就业指导与服务中心"

QUERIES = [
    "华中科技大学 宣讲会",
    "华中科技大学 双选会",
    "华中科技大学 招聘会",
    "华中大 宣讲会",
    "华中科技大学就业 招聘",
    "华中科技大学 2027届",
    "华中科技大学 空中宣讲",
    "华中科技大学 校园招聘",
]
PAGES = 5          # 每个查询最多翻页数（搜狗共10页）
SLEEP = (10.0, 18.0)  # 随机延时区间（秒）
ANTISPIDER_WAIT = 200  # 命中反爬后的退避秒数
ANTISPIDER_RETRY = 2   # 同页重试次数

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class Sogou:
    """带 cookie 会话的搜狗访问器"""

    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.op.addheaders = [("User-Agent", UA)]

    def get(self, url, referer=None, timeout=25):
        headers = {"Accept-Language": "zh-CN,zh;q=0.9"}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        data = self.op.open(req, timeout=timeout).read()
        return data.decode("utf-8", "ignore")


def sleep_r():
    time.sleep(random.uniform(*SLEEP))


def parse_results(t):
    """解析搜狗文章搜索结果：[(title, account, ts, link_url)]"""
    out = []
    for m in re.finditer(r'(?is)<li id="sogou_vr_[^"]*box_\d+"[^>]*>(.*?)</li>', t):
        seg = m.group(1)
        ti = re.search(r'(?is)id="sogou_vr_[^"]*title_\d+"[^>]*>(.*?)</a>', seg)
        if not ti:
            continue
        title = re.sub(r"(?is)<!--.*?-->|<[^>]+>", "", ti.group(1)).strip()
        title = HTML.unescape(title)
        src = re.search(r'(?is)<span class="all-time-y2">\s*([^<]*?)\s*</span>', seg)
        account = HTML.unescape(src.group(1).strip()) if src else ""
        ts = re.search(r"timeConvert\('(\d+)'\)", seg)
        lk = re.search(r'href="(/link\?url=[^"]+)"', seg)
        if not lk:
            continue
        link = HTML.unescape(lk.group(1)).replace(" ", "%20")
        out.append({"title": title, "account": account,
                    "ts": int(ts.group(1)) if ts else 0, "link": link})
    return out


def resolve_link(sg, link):
    """解析搜狗 /link 跳转页，返回真实 mp.weixin.qq.com URL"""
    t = sg.get("https://weixin.sogou.com" + link,
               referer="https://weixin.sogou.com/weixin?type=2")
    if "antispider" in t:
        return None
    frags = re.findall(r"url \+= '([^']*)'", t)
    if not frags:
        return None
    return "".join(frags)


def search(sg):
    """第一步：多查询搜索，过滤目标公众号，解析真实 URL"""
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            arts = json.load(f).get("articles", [])
    else:
        arts = []
    seen_links = {a.get("sogou_link") for a in arts}
    seen_titles = {a.get("title") for a in arts}

    n_new = 0
    for qi, q in enumerate(QUERIES):
        for page in range(1, PAGES + 1):
            u = ("https://weixin.sogou.com/weixin?type=2&query="
                 + urllib.parse.quote(q) + f"&ie=utf8&sort=1&page={page}")
            sleep_r()
            t = None
            for attempt in range(1 + ANTISPIDER_RETRY):
                try:
                    t = sg.get(u)
                except Exception as e:
                    print(f"  [查询失败] {q[:12]} p{page}: {e}")
                    time.sleep(20)
                    continue
                if "antispider" not in t:
                    break
                print(f"  [antispider] {q[:12]} p{page} 第{attempt+1}次，退避 {ANTISPIDER_WAIT}s")
                time.sleep(ANTISPIDER_WAIT)
            if t is None or "antispider" in t:
                print(f"  [放弃本查询] {q[:12]}")
                break
            items = parse_results(t)
            if not items:
                print(f"  [空] {q[:12]} p{page}")
                break
            hit = 0
            for it in items:
                if it["account"] != TARGET_ACCOUNT:
                    continue
                if it["link"] in seen_links or it["title"] in seen_titles:
                    continue
                seen_links.add(it["link"])
                seen_titles.add(it["title"])
                sleep_r()
                real = None
                for attempt in range(1 + ANTISPIDER_RETRY):
                    try:
                        real = resolve_link(sg, it["link"])
                    except Exception as e:
                        print(f"    [跳转失败] {it['title'][:24]}: {e}")
                        break
                    if real:
                        break
                    print(f"    [antispider@跳转] 第{attempt+1}次，退避 {ANTISPIDER_WAIT}s")
                    time.sleep(ANTISPIDER_WAIT)
                if not real or "mp.weixin.qq.com" not in real:
                    continue
                arts.append({
                    "title": it["title"], "account": it["account"],
                    "publish_ts": it["ts"], "url": real,
                    "sogou_link": it["link"], "fetched": False,
                })
                hit += 1
                n_new += 1
                print(f"  + [{time.strftime('%Y-%m-%d', time.localtime(it['ts'])) if it['ts'] else '?'}] "
                      f"{it['title'][:36]}")
            if not hit:
                break  # 本页没有目标公众号文章，不再翻页
            print(f"  [{q[:10]}] p{page}: 目标公众号 {hit} 篇")
        # 每个查询之间多歇一会
        time.sleep(random.uniform(4, 8))

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump({"account": TARGET_ACCOUNT, "crawled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "articles": arts}, f, ensure_ascii=False, indent=1)
    print(f"\n搜索完成：共 {len(arts)} 篇（本次新增 {n_new}）→ {DATA}")
    return arts


def extract_article(t, url):
    """从微信文章页提取结构化信息"""
    out = {"url": url}
    m = re.search(r"<title>(.*?)</title>", t, re.S)
    out["title"] = HTML.unescape(m.group(1).strip().replace("华中科技大学就业指导与服务中心", "").strip()) if m else ""
    m = re.search(r"var createTime = '([^']+)'", t) or re.search(r"publish_time[^>]*>?([^<]+)<", t)
    out["publish_time"] = m.group(1) if m else ""
    m = re.search(r'(?is)<div[^>]*id="js_content"[^>]*>(.*?)<script', t)
    if not m:
        m = re.search(r"(?is)<div[^>]*id=\"js_content\"[^>]*>(.*)</div>\s*</div>", t)
    body = m.group(1) if m else ""
    out["body_html"] = body
    txt = re.sub(r"(?is)<(script|style).*?</\1>", "", body)
    txt = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</tr>", "\n", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = HTML.unescape(txt)
    txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt).strip()
    out["body_text"] = txt
    return out


def collect_from_archives():
    """从本地已存档页面（就业网转发的微信外链）中识别并导入该公众号文章。

    就业网列表页常直接转发公众号文章，随着增量更新会持续积累，
    这是搜狗之外最稳定的来源。
    """
    import glob
    if os.path.exists(DATA):
        D = json.load(open(DATA, encoding="utf-8"))
    else:
        D = {"account": TARGET_ACCOUNT, "articles": []}
    arts = D.setdefault("articles", [])
    have = {re.sub(r"[?#].*", "", a.get("url", "")) for a in arts}

    os.makedirs(RAW_DIR, exist_ok=True)
    added = 0
    for fn in glob.glob(os.path.join(ROOT, "raw", "*.html")) + \
              glob.glob(os.path.join(ROOT, "raw", "notime", "*.html")):
        try:
            t = open(fn, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if "js_content" not in t:
            continue
        nm = re.search(r"js_name[^>]*>\s*([^<]+?)\s*<", t)
        if not nm or nm.group(1).strip() != TARGET_ACCOUNT:
            continue
        um = re.search(r'var msg_link = "([^"]+)"|url = "(https://mp\.weixin\.qq\.com/s[^"]+)"', t)
        url = (um.group(1) or um.group(2)) if um else ""
        if not url or re.sub(r"[?#].*", "", url) in have:
            continue
        info = extract_article(t, url)
        if len(info.get("body_text", "")) < 30:
            continue
        title = info.get("title") or (re.search(r"msg_title\s*=\s*\"([^\"]+)\"", t).group(1)
                                      if re.search(r"msg_title\s*=\s*\"([^\"]+)\"", t) else "")
        arts.append({
            "title": title, "account": TARGET_ACCOUNT, "publish_ts": 0,
            "publish_time": info.get("publish_time", ""), "url": url,
            "sogou_link": "", "fetched": True,
            "body_text": info["body_text"], "body_len": len(info["body_text"]),
            "from_archive": True,
        })
        have.add(re.sub(r"[?#].*", "", url))
        added += 1
        print(f"  + [存档] {title[:40]} | {info.get('publish_time','')} | 正文{len(info['body_text'])}字")
    D["crawled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(D, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"存档导入 {added} 篇，当前共 {len(arts)} 篇")
    return arts


def fetch_articles():
    """第二步：抓取所有未抓取的文章"""
    with open(DATA, encoding="utf-8") as f:
        D = json.load(f)
    os.makedirs(RAW_DIR, exist_ok=True)
    n_ok = n_fail = 0
    for a in D["articles"]:
        if a.get("fetched"):
            continue
        sleep_r()
        u = a["url"]
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA,
                                                     "Referer": "https://mp.weixin.qq.com/"})
            t = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [抓取失败] {a['title'][:26]}: {e}")
            n_fail += 1
            continue
        if "js_content" not in t and len(t) < 3000:
            print(f"  [失效] {a['title'][:26]} (len {len(t)})")
            n_fail += 1
            continue
        info = extract_article(t, u)
        a["publish_time"] = info["publish_time"]
        a["body_text"] = info["body_text"]
        a["body_len"] = len(info["body_text"])
        a["fetched"] = True
        n_ok += 1
        fn = os.path.join(RAW_DIR, re.sub(r"[^\w\-]", "_", u)[-46:] + ".html")
        with open(fn, "w", encoding="utf-8") as f2:
            f2.write(t)
        print(f"  ✓ {a['title'][:34]} | 正文{a['body_len']}字 | {a['publish_time']}")
        # 及时落盘，防中断丢失
        with open(DATA, "w", encoding="utf-8") as f3:
            json.dump(D, f3, ensure_ascii=False, indent=1)
    print(f"\n抓取完成：成功 {n_ok}，失败 {n_fail}")
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("archive", "all"):
        collect_from_archives()
    if cmd in ("search", "all"):
        sg = Sogou()
        search(sg)
    if cmd in ("fetch", "all"):
        fetch_articles()
