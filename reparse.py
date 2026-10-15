# -*- coding: utf-8 -*-
"""从 raw/ 原始页重新解析（不重复请求网络）：精准提取正文 + 元信息 + 清洗瘦身"""
import os
import re
import json
import html
import urllib.parse

BASE = "https://job.hust.edu.cn"
ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(ROOT, "raw")
IMG_DIR = os.path.join(ROOT, "images")
os.makedirs(IMG_DIR, exist_ok=True)


def extract_div_by_id(t, tag_id):
    """按 id 精确提取 div 内容（div 配平，避免抓到页面底部 UI 区）"""
    m = re.search(r'(?is)<div[^>]*id="%s"[^>]*>' % re.escape(tag_id), t)
    if not m:
        return ""
    start, depth = m.end(), 1
    for mm in re.finditer(r"(?is)</?div\b[^>]*>", t[start:]):
        depth += -1 if mm.group(0).startswith("</") else 1
        if depth == 0:
            return t[start:start + mm.start()]
    return t[start:start + 200000]


def download_img(url, name):
    """下载远程图片到本地，返回本地相对路径；失败返回原 URL。已存在则复用，不重复下载。"""
    for e in (".gif", ".png", ".jpg", ".jpeg"):
        p = os.path.join(IMG_DIR, name + e)
        if os.path.exists(p) and os.path.getsize(p) > 500:
            return "images/" + name + e
    try:
        import ssl
        import urllib.request
        ssl._create_default_https_context = ssl._create_unverified_context
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            "Referer": "https://mp.weixin.qq.com/",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            ct = r.headers.get("Content-Type", "")
        # 以真实文件头判定扩展名（微信 wx_fmt 参数与实际返回格式常不一致）
        if data[:3] == b"GIF":
            ext = ".gif"
        elif data[:4] == b"\x89PNG":
            ext = ".png"
        elif data[:2] == b"\xff\xd8":
            ext = ".jpg"
        else:
            ext = (".gif" if "gif" in ct or "wx_fmt=gif" in url else
                   ".png" if ("png" in ct or "wx_fmt=png" in url) else ".jpg")
        if len(data) < 500:
            return url
        with open(os.path.join(IMG_DIR, name + ext), "wb") as f:
            f.write(data)
        return "images/" + name + ext
    except Exception as e:
        print("    [img fail]", url[:70], e)
        return url


def localize_wechat_images(body, prefix):
    """微信图片有防盗链，外链在本地打开会 403，需下载到本地"""
    n = 0

    def _repl(m):
        nonlocal n
        tag, src = m.group(0), html.unescape(m.group(1))
        n += 1
        local = download_img(src, "%s_%02d" % (prefix, n))
        tag = tag.replace(m.group(1), local)
        tag = re.sub(r'(?is)\sdata-(?:crop[a-z]*|s|backw|backh|imgfileid|ratio|type|w|h)="[^"]*"', "", tag)
        return re.sub(r"(?i)\sdata-src=", " src=", tag)

    body = re.sub(r'(?is)<img[^>]*?data-src="([^"]+)"[^>]*>', _repl, body)
    return body, n

DATA_FILE = os.path.join(ROOT, "data", "jobs.json")


def load():
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def save(data):
    """原子写入，避免更新过程中断导致数据损坏"""
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA_FILE)


D = load()


def strip_noise(t):
    t = re.sub(r"(?is)<!--.*?-->", "", t)
    t = re.sub(r"(?is)<script.*?</script>", "", t)
    t = re.sub(r"(?is)<style.*?</style>", "", t)
    t = re.sub(r"(?is)<(meta|link|noscript)\b[^>]*>", "", t)
    return t


def extract_meta(t):
    """从纯文本 '键：' + 值 的模式中提取元信息"""
    t = strip_noise(t)
    # 主内容区（去掉导航/页脚）
    m = re.search(r"(?is)<div class=\"nymain.*", t)
    seg = m.group(0) if m else t
    seg = seg[:seg.find('<div class="footer')] if '<div class="footer' in seg else seg
    txt = re.sub(r"(?is)<br\s*/?>", "\n", seg)
    txt = re.sub(r"(?is)</(p|div|tr|li|h\d|td)>", "\n", txt)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = html.unescape(txt)

    keys = ["开始时间", "结束时间", "举办时间", "举办地点", "单位性质", "单位行业", "所在地区",
            "学历要求", "招聘学院", "专业要求", "联系人", "联系电话", "联系邮箱", "电子邮箱",
            "单位地址", "单位网址", "所属行业", "企业性质", "招聘类型", "面向学历", "信息来源"]
    meta = {}
    for k in keys:
        mm = re.search(re.escape(k) + r"\s*[:：]\s*\n?\s*([^\n]{1,120})", txt)
        if mm:
            v = re.sub(r"\s+", " ", mm.group(1)).strip(" 　|｜·")
            if v and v not in ("无", "-", "—"):
                meta[k] = v
    return meta


def pick_body(t, url=""):
    """选最内层、内容最实在的正文容器"""
    # 微信公众号文章：按 id 精确取正文容器
    if "mp.weixin.qq.com" in url:
        b = extract_div_by_id(t, "js_content")
        if b and len(re.sub(r"<[^>]+>", "", b).strip()) > 20:
            return b

    cands = []
    # 最内层 div.txt
    for m in re.finditer(r'(?is)<div class="txt"[^>]*>(.*?)</div>\s*(?:</div>\s*)?</div>', t):
        cands.append(m.group(1))
    for m in re.finditer(r'(?is)<div class="arc-con[^"]*"[^>]*>(.*)', t):
        cands.append(m.group(1))
    for m in re.finditer(r'(?is)<div class="content"[^>]*>(.*)', t):
        cands.append(m.group(1))

    # 导航/页脚/JS 噪声标记
    noise = ("Recruitment Fair", "window.", "var msg_", "__moon_initcallback",
             "在校生/教职工登录", "技术支持：武汉金教")
    best, best_score = "", 0
    for c in cands:
        c = strip_noise(c)
        if '<div class="footer' in c:
            c = c[:c.find('<div class="footer')]
        plain = re.sub(r"<[^>]+>", "", c).strip()
        text_len = len(plain)
        score = text_len
        if text_len < 30:
            score = 0
        # 噪声惩罚：出现任一标记且正文不长，判为导航/模板块
        hits = sum(1 for n in noise if n in c)
        if hits:
            score = score // (4 * hits) if text_len < 4000 else score // 2
        if score > best_score:
            best, best_score = c, score

    if not best:
        m = re.search(r"(?is)<body[^>]*>(.*)</body>", t)
        best = m.group(1) if m else t
    return best


VOID = {"img", "br", "hr", "input", "meta", "link", "source", "col", "area",
        "base", "wbr", "embed", "param", "track"}


def balance_tags(b):
    """补齐未闭合标签，保证片段不会破坏外层布局"""
    stack = []
    out = []
    pos = 0
    for m in re.finditer(r"(?is)</?([a-zA-Z][\w-]*)((?:\s[^>]*?)?)(/?)>", b):
        out.append(b[pos:m.start()])
        pos = m.end()
        name = m.group(1).lower()
        raw = m.group(0)
        if raw.startswith("</"):
            if name in stack:
                while stack and stack[-1] != name:
                    out.append("</%s>" % stack.pop())
                stack.pop()
                out.append(raw)
            # 栈中无对应开放标签 -> 丢弃该孤立闭合标签
        elif m.group(3) == "/" or name in VOID:
            out.append(raw)
        else:
            stack.append(name)
            out.append(raw)
    out.append(b[pos:])
    # 丢弃尾部残留的孤立结束标签
    tail = out[-1]
    tail = re.sub(r"(?is)^\s*(?:</(?:div|span|p|table|tbody|tr|td|ul|li|font|b|i|u|em|strong|section|a)>\s*)+",
                  "", tail)
    out[-1] = tail
    while stack:
        out.append("</%s>" % stack.pop())
    return "".join(out)


def clean_body(b):
    b = strip_noise(b)
    # 微信自定义标签（样式/音频/小程序卡片等）直接剔除
    b = re.sub(r"(?is)</?mp[a-z\-]+\b[^>]*>", "", b)
    # 图片绝对化
    def _img(m):
        tag = m.group(0)
        src = re.search(r'(?i)src="([^"]+)"', tag)
        if not src:
            return ""
        u = src.group(1).strip()
        if not u or u.startswith("data:"):
            alt = re.search(r'(?i)data-src="([^"]+)"', tag)
            if not alt:
                return ""  # 丢弃内联 base64，减小体积
            u = alt.group(1).strip()
            tag = re.sub(r'(?i)src="[^"]*"', 'src="%s"' % u, tag)
        if u.startswith(("http", "images/", "./", "//")):
            out = tag  # 已是绝对地址或已本地化的图片
        else:
            out = tag.replace(u, urllib.parse.urljoin(BASE, u))
        if "loading=" not in out:
            out = out.replace("<img", '<img loading="lazy"', 1)
        return out
    b = re.sub(r"(?is)<img[^>]*>", _img, b)
    # 链接绝对化 + 新窗口
    def _a(m):
        tag = m.group(1)
        href = re.search(r'(?i)href="([^"]+)"', tag)
        if href:
            h = href.group(1).strip()
            if h.startswith(("http", "#", "mailto:", "tel:")):
                tag = tag.replace(h, h)
            elif h.startswith("javascript"):
                return ""
            else:
                tag = tag.replace(h, urllib.parse.urljoin(BASE, h))
        if "target=" not in tag:
            tag += ' target="_blank" rel="noopener"'
        return "<a" + tag + ">"
    b = re.sub(r"(?is)<a(\s[^>]*)>", _a, b)
    # 去掉危险/无用属性，保留语义
    b = re.sub(r'(?is)\s(?:style|class|align|valign|width|height|border|bgcolor|cellspacing|cellpadding|'
               r'face|lang|id|name|title|type|data-[a-z0-9_\-]+|on[a-z]+)="[^"]*"', "", b)
    # 去掉空标签（反复几轮）
    for _ in range(4):
        nb = re.sub(r"(?is)<(span|font|b|i|u|em|strong|p|div|section|a|label)\s*>(?:\s|&nbsp;|<br\s*/?>)*</\1>", "", b)
        if nb == b:
            break
        b = nb
    # 表格结构保留但压缩
    b = re.sub(r"\n\s*\n+", "\n", b)
    b = re.sub(r"[ \t]{2,}", " ", b)
    lines = [l.rstrip() for l in b.split("\n")]
    b = "\n".join(l for l in lines if l.strip() or l == "")
    return balance_tags(b.strip())


def parse_one(raw_path, url, verbose=True):
    """从单个原始页解析出 (body, text, meta, 下载图片数)"""
    if not os.path.exists(raw_path):
        return "", "", {}, 0
    t = open(raw_path, encoding="utf-8", errors="ignore").read()
    body = pick_body(t, url)
    n_img = 0
    if "mp.weixin.qq.com" in url and body:
        slug = re.sub(r"[^\w\-]", "_", os.path.splitext(os.path.basename(raw_path))[0])[-28:]
        body, n_img = localize_wechat_images(body, slug)
        if n_img and verbose:
            print(f"  [微信图片] {os.path.basename(raw_path)[:30]} → 下载 {n_img} 张")
    body = clean_body(body)
    text = re.sub(r"<[^>]+>", "", body).strip()
    if len(text) < 20 or "Recruitment Fair" in body[:400]:
        body, text = "", ""
    return body, text, extract_meta(t), n_img


def main():
    n_empty = 0
    for it in D["items"]:
        raw_path = os.path.join(ROOT, it.get("raw", ""))
        if "job.hust.edu.cn" not in it["url"] and "weixin" in it["url"]:
            it["external"] = True
        body, text, meta, _ = parse_one(raw_path, it["url"])
        if not body:
            n_empty += 1
        it["body"] = body
        it["body_text_len"] = len(text)
        if meta:
            it["meta"] = meta

    D["reparsed"] = True
    D["empty_body"] = n_empty
    save(D)

    total = sum(len(i.get("body") or "") for i in D["items"])
    has = sum(1 for i in D["items"] if i.get("body"))
    print(f"重解析完成: 有正文 {has}/{len(D['items'])}，空正文 {n_empty}，总体积 {total//1024} KB")


if __name__ == "__main__":
    main()
