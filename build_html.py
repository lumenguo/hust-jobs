# -*- coding: utf-8 -*-
"""根据 data/jobs.json 生成自包含 HTML 报告 index.html"""
import os
import re
import json
import html
import time
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "jobs.json")

with open(DATA, encoding="utf-8") as f:
    D = json.load(f)

items = D["items"]

# ---------- 公众号核对修订数据 ----------
REV_FILE = os.path.join(ROOT, "data", "revisions.json")
WX_FILE = os.path.join(ROOT, "data", "wechat_articles.json")
revisions, wx_arts = [], []
WX_ACCOUNT, WX_CRAWLED, REV_AT = "", "", ""
if os.path.exists(REV_FILE):
    try:
        with open(REV_FILE, encoding="utf-8") as f:
            RD = json.load(f)
        revisions = RD.get("revisions", [])
        REV_AT = RD.get("revised_at", "")
        WX_ACCOUNT = RD.get("source_account", "")
    except Exception:
        pass
if os.path.exists(WX_FILE):
    try:
        with open(WX_FILE, encoding="utf-8") as f:
            WD = json.load(f)
        wx_arts = WD.get("articles", [])
        WX_ACCOUNT = WX_ACCOUNT or WD.get("account", "")
        WX_CRAWLED = WD.get("crawled_at", "")
    except Exception:
        pass

# 数据更新时间（每条信息标注用）
UPD = D.get("last_update") or D.get("last_check") or D.get("crawled_at", "")
ND_UPD = ""

ACT_LABEL = {"supplement": "公众号补充", "correct": "公众号修正",
             "refine": "时刻补全", "confirm": "公众号核对一致"}
ACT_CLS = {"supplement": "rv-add", "correct": "rv-fix",
           "refine": "rv-ref", "confirm": "rv-ok"}

# ---------- 「未注明宣讲时间」专栏数据（招聘信息栏目公告，单独存放） ----------
NOTIME_FILE = os.path.join(ROOT, "data", "jobs_notime.json")
notime_items = []
if os.path.exists(NOTIME_FILE):
    try:
        with open(NOTIME_FILE, encoding="utf-8") as f:
            ND = json.load(f)
        main_titles = {i.get("title", "") for i in items}
        main_urls = {i.get("url", "") for i in items}
        # 去重：主表已收录（带宣讲时间）的同名/同链接条目不再进专栏
        notime_items = [i for i in ND.get("items", [])
                        if i.get("title") not in main_titles and i.get("url") not in main_urls]
        ND_COUNT = len(ND.get("items", []))
        ND_CRAWLED = ND.get("crawled_at", "")
        ND_UPD = ND.get("last_update") or ND.get("last_check") or ND.get("crawled_at", "")
    except Exception:
        notime_items = []
else:
    ND_COUNT, ND_CRAWLED, ND_UPD = 0, "", ""

# ---------- 简历投递截止时间（公告原文提取 + 联网核对） ----------
DL_FILE = os.path.join(ROOT, "data", "deadlines.json")
deadlines = {}
if os.path.exists(DL_FILE):
    try:
        with open(DL_FILE, encoding="utf-8") as f:
            deadlines = json.load(f)
    except Exception:
        deadlines = {}


def dl_html(url):
    """按条目 url 生成截止时间标签 + 依据框（无数据返回空）"""
    d = deadlines.get(url or "")
    if not d:
        return "", "", ""
    ongoing = (d.get("type") == "ongoing") or (not d.get("date") and d.get("note"))
    if ongoing:
        note = (d.get("note") or "招满即止").strip()
        tag = (f'<span class="tag tag-dl tag-dl-og" title="官方未设固定截止日｜'
               f'{html.escape(note)}｜联网核对">招满即止</span>')
        rows_ = [f'<div><span>投递方式</span><b class="new">{html.escape(note)}</b></div>']
        su = esc(d.get("source_url", ""))
        if su:
            rows_.append(f'<div><span>来源</span><b>{html.escape(d.get("label", "") or "公开渠道")}'
                         f' <a href="{su}" target="_blank" rel="noopener">来源链接 ↗</a></b></div>')
        rows_.append('<div><span>获取方式</span><b>联网核对（企业官方渠道表述）</b></div>')
        box = (f'<div class="dlbox dl-og">'
               f'<div class="dlhead">未设固定截止日：{html.escape(note)}'
               f'<span class="dlsrc">联网核对</span></div>'
               f'<div class="dlbody">{"".join(rows_)}</div></div>')
        return tag, box, "ONGOING"
    ds = d["date"]
    extra = (d.get("time") or "").strip()
    # 只在与日期不同的情形下补时刻（如 24:00 / 18:00）
    hm = ""
    m = re.search(r"(\d{1,2}[:：]\d{2})", extra)
    if m and m.group(1) not in ds:
        hm = " " + m.group(1)
    web = d.get("source") == "web"
    cls = "tag tag-dl dl-web" if web else "tag tag-dl"
    tag = (f'<span class="{cls}" title="简历投递截止 {html.escape(ds + hm)}｜'
           f'{"联网核对：" + html.escape(d.get("label", "") or "公开渠道") if web else "公告原文提取"}">'
           f'投递截止 {html.escape(ds[5:])}{html.escape(hm)}</span>')
    rows_ = [f'<div><span>截止时间</span><b class="new">{html.escape(ds)}{html.escape(hm)}</b></div>']
    if d.get("evidence"):
        rows_.append(f'<div><span>公告原句</span><b>{html.escape(d["evidence"])}</b></div>')
    su = esc(d.get("source_url", ""))
    if su:
        rows_.append(f'<div><span>来源</span><b>{html.escape(d.get("label", "") or "公开渠道")}'
                     f' <a href="{su}" target="_blank" rel="noopener">来源链接 ↗</a></b></div>')
    rows_.append(f'<div><span>获取方式</span><b>'
                 f'{"联网核对（企业官网/公开平台）" if web else "就业网公告原文自动提取"}</b></div>')
    box = (f'<div class="dlbox {"dl-web" if web else ""}">'
           f'<div class="dlhead">简历投递截止：{html.escape(ds)}{html.escape(hm)}'
           f'<span class="dlsrc">{"联网核对" if web else "公告原文"}</span></div>'
           f'<div class="dlbody">{"".join(rows_)}</div></div>')
    return tag, box, ds


def norm_date(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return m.group(0) if m else ""


def esc(s):
    """转义，但先还原已存在的 HTML 实体（避免 &amp;amp; 双重转义）"""
    return html.escape(html.unescape(s or ""))


def norm_time(s):
    m = re.search(r"(\d{1,2}:\d{2})", s or "")
    return m.group(1) if m else ""


places = Counter()
for it in items:
    p = (it.get("place") or "").strip()
    if p:
        places[p] += 1

dates = sorted({norm_date(it.get("time")) for it in items if norm_date(it.get("time"))})
kinds = Counter("宣讲会(/zjob)" if "/zjob/" in it["url"] else "外部招聘(/extxjh)" for it in items)

rows = []
for i, it in enumerate(items):
    title = html.escape(it.get("title", ""))
    tm = html.escape(it.get("time", ""))
    place = html.escape(it.get("place", ""))
    url = html.escape(it.get("url", ""))
    body = it.get("body") or "<p class='empty'>（该条未获取到正文内容，请点击查看原文）</p>"
    # 元信息
    meta = it.get("meta") or {}
    meta_html = ""
    if meta:
        lis = "".join(f"<li><span>{html.escape(k)}</span><b>{html.escape(v)}</b></li>"
                      for k, v in list(meta.items())[:12])
        meta_html = f"<ul class='meta'>{lis}</ul>"
    has = "1" if it.get("body") else "0"
    dl_tag, dl_box, dl_date = dl_html(it.get("url", ""))
    if it.get("body"):
        body_html = it["body"]
    else:
        body_html = ("<p class='empty'>该条目在源站详情页中未提供正文内容"
                     "（校外宣讲会常见，仅登记了时间地点）。请点击「查看原文」访问发布页。</p>")
    # 公众号核对/修订标注
    rv = it.get("revision") or {}
    rv_tag = ""
    rv_box = ""
    # 数据来源与更新时间（每条必注）
    it_host = re.sub(r"^https?://", "", it.get("url", "")).split("/")[0] or "就业信息网"
    src_line = (f'<div class="src">来源：{esc(it_host)}'
                f'（{html.escape(D.get("source",""))}）'
                f' ｜ 数据更新：{html.escape(UPD)}'
                + (f' ｜ 公众号核对：{html.escape(REV_AT)}' if rv else '')
                + f'</div>')
    if rv:
        act = rv.get("action", "")
        if act in ACT_LABEL:
            st = rv.get("source_title", "")
            sp = rv.get("source_publish", "")
            su = esc(rv.get("source_url", ""))
            rv_tag = (f'<span class="tag rv {ACT_CLS[act]}" title="依据：《{html.escape(st)}》">'
                      f'{ACT_LABEL[act]}</span>')
            orig = it.get("time_original") or ""
            link = (f'<a href="{su}" target="_blank" rel="noopener">原文 ↗</a>'
                    if su else "")
            rv_box = (f'<div class="rvbox {ACT_CLS[act]}">'
                      f'<div class="rvhead">公众号核对：{ACT_LABEL[act]}'
                      f'<span class="rvtime">依据发布 {html.escape(sp)}</span></div>'
                      f'<div class="rvbody">'
                      + (f'<div><span>原记录</span><b>{html.escape(orig or tm)}</b></div>'
                         if act in ("correct", "refine") else "")
                      + (f'<div><span>修订为</span><b class="new">{html.escape(tm)}</b></div>'
                         if act in ("correct", "refine") else
                         f'<div><span>核对结果</span><b>{html.escape(tm)} 与公众号一致</b></div>')
                      + f'<div><span>来源</span><b>《{html.escape(st)}》{link}</b></div>'
                      + (f'<div><span>取自</span><b>{html.escape(rv.get("extract_from",""))}</b></div>'
                         if rv.get("extract_from") else "")
                      + f'</div></div>')
    rows.append(f"""
<article class="card{' rvcard' if rv else ''}" data-i="{i}" data-has="{has}" data-date="{norm_date(it.get('time'))}" data-dl="{dl_date}" data-title="{html.escape(it.get('title','').lower())}" data-place="{html.escape((it.get('place') or '').lower())}" data-key="{url}">
  <div class="chead" onclick="toggle({i})">
    <div class="cidx">{i+1:03d}</div>
    <div class="cmain">
      <h3 class="ctitle">{title}</h3>
      <div class="cinfo">
        <span class="tag tag-t">{tm or '时间待定'}</span>
        <span class="tag tag-p">{place or '地点待定'}</span>
        <span class="tag tag-k">{'校内宣讲' if '/zjob/' in it['url'] else ('外部链接' if it.get('external') else '外部招聘')}</span>
        {dl_tag}
        {'' if has == '1' else '<span class="tag tag-w">无正文</span>'}
        {rv_tag}
      </div>
    </div>
    <div class="star" title="加入/移出 我的关注" onclick="favToggle(event, this)">☆</div>
    <div class="carrow">▾</div>
  </div>
  <div class="cbody" id="b{i}">
    {meta_html}
    {rv_box}
    {dl_box}
    <div class="content">{body_html}</div>
    <div class="cfoot"><a href="{url}" target="_blank" rel="noopener">查看原文 ↗</a>{src_line}</div>
  </div>
</article>""")

place_opts = "".join(f'<option value="{html.escape(p)}">{html.escape(p)} ({c})</option>'
                     for p, c in places.most_common())
date_opts = "".join(f'<option value="{d}">{d}</option>' for d in dates)
NT_COUNT = len(notime_items)
if NT_COUNT:
    date_opts += f'<option value="NOTIME">未注明时间（{NT_COUNT}）</option>'

# ---------- 专栏二：未注明宣讲时间 ----------
def plain_text(b, limit=420):
    """正文转纯文本并截断（公告全文较长，报告内只放摘要，全文点「查看原文」）"""
    t = re.sub(r"(?is)<(script|style).*?</\1>", "", b or "")
    t = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    if len(t) > limit:
        t = t[:limit].rstrip() + " …"
    return html.escape(t)


def extract_place(body):
    """从公告正文（纯文本）轻量提取工作地点；提取不到返回空"""
    txt = re.sub(r"(?is)<(script|style).*?</\1>", "", body or "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    CITIES = ("北京", "上海", "天津", "重庆", "武汉", "深圳", "广州", "杭州", "南京", "苏州",
              "成都", "西安", "长沙", "郑州", "合肥", "福州", "厦门", "济南", "青岛", "宁波",
              "无锡", "东莞", "佛山", "珠海", "大连", "沈阳", "哈尔滨", "长春", "石家庄",
              "南昌", "贵阳", "昆明", "南宁", "海口", "太原", "兰州", "乌鲁木齐", "呼和浩特")
    m = re.search(r"(?:工作地点|工作地|Base|base|base地|地点)\s*[:：]?\s*([一-龥]{2,12})", txt)
    if m:
        v = m.group(1).strip()
        if any(w in v for w in ("另行", "通知", "专业", "详见", "如下", "以下", "官网", "附件",
                                "岗位", "页面", "华中", "各地", "全国", "覆盖", "需求", "研发")):
            return ""
        if (v.endswith(("市", "省", "区", "县", "州", "地区")) or v in CITIES) and 2 <= len(v) <= 12:
            return v
    return ""


rows2 = []
for j, it in enumerate(notime_items):
    title = html.escape(it.get("title", ""))
    pub = html.escape(it.get("date", ""))
    url = html.escape(it.get("url", ""))
    place = extract_place(it.get("body") or "")
    has = "1" if it.get("body") else "0"
    dl_tag, dl_box, dl_date = dl_html(it.get("url", ""))
    preview = plain_text(it.get("body") or "") if it.get("body") else ""
    if not preview:
        preview = ("该公告发布在校外渠道（微信公众号 / 政府人事网等），正文未随页面存档，"
                   "请点击「查看原文」访问发布页。")
    # 公众号补充的宣讲时间（原公告未注明，经公众号核对后补入）
    rv = it.get("revision") or {}
    tt = (it.get("talk_time") or "").strip()
    if tt:
        time_tag = f'<span class="tag rv rv-add">宣讲时间 {html.escape(tt)}</span>'
        nt_cls = " nt-filled"
    else:
        time_tag = '<span class="tag tag-w">宣讲时间：待确认</span>'
        nt_cls = ""
    place_tag = (f'<span class="tag tag-p">{html.escape(place)}</span>' if place
                 else '<span class="tag tag-p">地点未注明</span>')
    rv_box = ""
    # 数据来源与更新时间（每条必注）
    it_host2 = re.sub(r"^https?://", "", it.get("url", "")).split("/")[0] or "就业信息网"
    src_line2 = (f'<div class="src">来源：{esc(it_host2)}'
                 f'（{html.escape(D.get("source",""))}）'
                 f' ｜ 数据更新：{html.escape(ND_UPD or UPD)}'
                 + (f' ｜ 公众号核对：{html.escape(REV_AT)}' if rv else '')
                 + f'</div>')
    if tt and rv:
        st = rv.get("source_title", "")
        su = esc(rv.get("source_url", ""))
        sp = rv.get("source_publish", "")
        link = (f'<a href="{su}" target="_blank" rel="noopener">原文 ↗</a>'
                if su else "")
        rv_box = (f'<div class="rvbox rv-add"><div class="rvhead">公众号补充宣讲时间'
                  f'<span class="rvtime">依据发布 {html.escape(sp)}</span></div>'
                  f'<div class="rvbody">'
                  f'<div><span>原公告</span><b>未注明宣讲时间</b></div>'
                  f'<div><span>补充为</span><b class="new">{html.escape(tt)}</b></div>'
                  + (f'<div><span>报名截止</span><b>{html.escape(it.get("deadline",""))}</b></div>'
                     if it.get("deadline") else "")
                  + (f'<div><span>地点</span><b>{html.escape(it.get("place_extracted",""))}</b></div>'
                     if it.get("place_extracted") else "")
                  + f'<div><span>来源</span><b>《{html.escape(st)}》{link}</b></div>'
                  + (f'<div><span>取自</span><b>{html.escape(rv.get("extract_from",""))}</b></div>'
                     if rv.get("extract_from") else "")
                  + f'</div></div>')
    rows2.append(f"""
<article class="card c2{nt_cls}" data-i="{j}" data-has="{has}" data-date="{pub}" data-dl="{dl_date}" data-title="{html.escape(it.get('title','').lower())}" data-place="" data-key="{url}">
  <div class="chead" onclick="toggle2({j})">
    <div class="cidx">N{j+1:03d}</div>
    <div class="cmain">
      <h3 class="ctitle">{title}</h3>
      <div class="cinfo">
        {time_tag}
        <span class="tag tag-t">发布 {pub or '日期待查'}</span>
        {place_tag}
        {dl_tag}
        <span class="tag tag-k">{'站外公告' if it.get('external') else '站内公告'}</span>
        {'' if has == '1' else '<span class="tag tag-w">无正文存档</span>'}
      </div>
    </div>
    <div class="star" title="加入/移出 我的关注" onclick="favToggle(event, this)">☆</div>
    <div class="carrow">▾</div>
  </div>
  <div class="cbody" id="c{j}">
    {rv_box}
    {dl_box}
    <div class="content nt">{preview}</div>
    <div class="cfoot"><a href="{url}" target="_blank" rel="noopener">查看原文 ↗（全文）</a>{src_line2}</div>
  </div>
</article>""")

ndate_opts = "".join(f'<option value="{d}">{d}</option>'
                     for d in sorted({i.get("date", "") for i in notime_items if i.get("date")}, reverse=True))

# ---------- 区块三：公众号核对与修订记录 ----------
REV_BY_ACTION = Counter(r.get("action", "") for r in revisions)
rev_items_html = ""
for r in revisions:
    act = r.get("action", "")
    cls = ACT_CLS.get(act, "rv-ok")
    label = ACT_LABEL.get(act, act)
    st = html.escape(r.get("source_title", ""))
    su = esc(r.get("source_url", ""))
    sp = html.escape(r.get("source_publish", ""))
    old = html.escape(str(r.get("old", "")))
    new = html.escape(str(r.get("new", "")))
    diff = html.escape(str(r.get("diff", "")))
    it_title = html.escape(r.get("item_title", ""))
    it_url = esc(r.get("url", ""))
    link = f'<a href="{su}" target="_blank" rel="noopener">原文 ↗</a>' if su else ""
    tgt = f'<a href="{it_url}" target="_blank" rel="noopener">{it_title}</a>' if it_url else it_title
    chg = (f'<div><span class="k">原记录</span><del>{old}</del></div>'
           f'<div><span class="k">修订为</span><ins>{new}</ins></div>') if new != old else \
          f'<div><span class="k">结果</span>{new}</div>'
    rev_items_html += (
        f'<div class="rvitem"><div class="rt"><span class="badge {cls}">{label}</span>{tgt}</div>'
        f'<div class="rc">{chg}'
        + (f'<div><span class="k">差异说明</span>{diff}</div>' if diff else "")
        + f'<div><span class="k">依据</span>《{st}》· 发布于 {sp} {link}</div>'
        f'<div><span class="k">修订时间</span>{html.escape(r.get("revised_at",""))}</div>'
        f'</div></div>')

wx_links = "".join(
    f'<a href="{esc(a.get("url",""))}" target="_blank" rel="noopener" '
    f'title="{html.escape(a.get("title",""))}">'
    f'{html.escape((a.get("title") or a.get("url",""))[:34])}</a>'
    for a in wx_arts if a.get("url"))

if revisions or wx_arts:
    stat_badges = " · ".join(
        f"{ACT_LABEL.get(a, a)} {c}" for a, c in REV_BY_ACTION.most_common()) or "暂无修订"
    rev_sec = f"""
<section id="sec3">
  <div class="s2head">
    <h2>公众号核对与修订</h2>
    <p class="s2desc">以微信公众号「<b>{html.escape(WX_ACCOUNT)}</b>」发布内容为补充信息源，
    对上方招聘信息进行交叉核对：补全缺失的宣讲时间，修正不一致的时间，并标注每处修订的依据。
    冲突时以公众号最新发布内容为准。核对时间：{html.escape(REV_AT or '—')} ｜ {html.escape(stat_badges)}</p>
  </div>
  <div class="rvlist">
  {rev_items_html or '<div class="rvitem"><div class="rt">暂无修订记录</div><div class="rc">已抓取的公众号文章中未发现与现有条目冲突或需补充的时间信息。</div></div>'}
  </div>
  <div class="wxsrc">
    <div style="width:100%;color:var(--tx3);font-size:12px;margin-bottom:2px">
      已核对的公众号文章（{len(wx_arts)} 篇，采集于 {html.escape(WX_CRAWLED or '—')}）：</div>
    {wx_links or '<span style="color:var(--tx3);font-size:12px">暂无</span>'}
  </div>
</section>"""
else:
    rev_sec = ""

# 日期分布
by_date = Counter(norm_date(it.get("time")) for it in items)
dmax = max(by_date.values()) if by_date else 1
dist = ('<div class="dist" id="distTalk"><div class="dh">宣讲会日期分布'
        ' <span class="dhint">（点击柱子按日期筛选；末列「未注明」收录未注明宣讲时间的公告，'
        '与具体日期互斥，同一时间只生效其中一种筛选）</span></div><div class="dbars">')
for d in dates:
    c = by_date[d]
    h = max(4, int(c / dmax * 92))
    dist += (f'<div class="dbar" data-d="{d}" title="{d} · {c}场" onclick="pickDate(\'{d}\')">'
             f'<div class="dcol" style="height:{h}px"></div><div class="dlb">{d[5:]}</div>'
             f'<div class="dnum">{c}</div></div>')
if NT_COUNT:
    # 「未注明时间」独立分类项：点击后只展示专栏二，与具体日期筛选互斥
    h = min(92, max(4, int(NT_COUNT / dmax * 92)))
    dist += (f'<div class="dbar dbar-nt" data-d="NOTIME" '
             f'title="未注明宣讲时间 · {NT_COUNT}条（点击只查看该类，不含具体日期的宣讲会）" '
             f'onclick="pickDate(\'NOTIME\')">'
             f'<div class="dcol" style="height:{h}px"></div><div class="dlb">未注明</div>'
             f'<div class="dnum">{NT_COUNT}</div></div>')
dist += "</div></div>"

# ---------- 简历投递截止日期分布 ----------
_vis_urls = {i.get("url") for i in items} | {i.get("url") for i in notime_items}
_dl_known = {k: v for k, v in deadlines.items()
             if k in _vis_urls and (v.get("date") or v.get("type") == "ongoing" or v.get("note"))}
VIS_TOTAL = len(items) + len(notime_items)
DL_NONE = max(0, VIS_TOTAL - len(_dl_known))
dl_dates = sorted(_dl_known.values(), key=lambda v: v["date"])
by_dl = Counter(v["date"] for v in dl_dates if v.get("date"))
DL_ONG = sum(1 for v in _dl_known.values() if not v.get("date"))
dmax2 = max(by_dl.values()) if by_dl else 1
dmax2 = max([dmax2, DL_ONG, DL_NONE, 1])
TODAY = __import__("datetime").date.today().isoformat()
dist2 = ('<div class="dist dist2" id="distDl"><div class="dh">简历投递截止日期分布'
         '<span class="dhint">（点击柱子按截止日期筛选；末列「未注明」收录未注明截止时间的公告，'
         '与具体日期互斥，同一时间只生效其中一种筛选；灰色为已过截止日，'
         '「招满即止」为官方未设固定截止日）</span></div><div class="dbars">')
for d in sorted(by_dl):
    c = by_dl[d]
    h = max(4, int(c / dmax2 * 92))
    past = " dl-past" if d < TODAY else ""
    dist2 += (f'<div class="dbar dbar-dl{past}" data-d="{d}" title="{d} · {c}家'
              f'{"（已过截止）" if d < TODAY else ""}；点击筛选" onclick="pickDl(\'{d}\')">'
              f'<div class="dcol" style="height:{h}px"></div><div class="dlb">{d[5:]}</div>'
              f'<div class="dnum">{c}</div></div>')
if DL_ONG:
    h = max(4, int(DL_ONG / dmax2 * 92))
    dist2 += (f'<div class="dbar dbar-dl dbar-ong" data-d="ONGOING" '
              f'title="招满即止/尽快投递（官方未设固定截止日）· {DL_ONG}家；点击筛选" '
              f'onclick="pickDl(\'ONGOING\')">'
              f'<div class="dcol" style="height:{h}px"></div><div class="dlb">招满即止</div>'
              f'<div class="dnum">{DL_ONG}</div></div>')
h = max(4, int(DL_NONE / dmax2 * 92))
dist2 += (f'<div class="dbar dbar-dl dbar-none" data-d="NONE" '
          f'title="未注明投递截止时间 · {DL_NONE}家（点击只查看该类，不含任何具体截止日期）" '
          f'onclick="pickDl(\'NONE\')">'
          f'<div class="dcol" style="height:{h}px"></div><div class="dlb">未注明</div>'
          f'<div class="dnum">{DL_NONE}</div></div>')
dist2 += "</div></div>"

dl_opts = "".join(f'<option value="{d}">{d}（{by_dl[d]}）</option>' for d in sorted(by_dl, reverse=True))
dl_opts = '<option value="">全部截止日期</option>' + dl_opts + \
          (f'<option value="ONGOING">招满即止/尽快投递（{DL_ONG}）</option>' if DL_ONG else '') + \
          f'<option value="NONE">未注明截止时间（{DL_NONE}）</option>'

# ---------- 区块四：简历投递截止时间核对明细 ----------
_title_by_url = {}
for it in items:
    _title_by_url[it.get("url")] = it.get("title", "")
for it in notime_items:
    _title_by_url.setdefault(it.get("url"), it.get("title", ""))

DL_LOC = sum(1 for v in _dl_known.values() if v.get("source") == "local")
DL_WEB = sum(1 for v in _dl_known.values() if v.get("source") == "web")
_dl_rows = []
for k, v in sorted(_dl_known.items(), key=lambda kv: (kv[1].get("date") or "9999", kv[0])):
    ds = v.get("date") or ""
    ongoing = not ds
    web = v.get("source") == "web"
    past = " past" if (ds and ds < TODAY) else ""
    nm = html.escape(_title_by_url.get(k) or k)
    su = esc(v.get("source_url", ""))
    if ongoing:
        note = html.escape(v.get("note") or "招满即止")
        srk = ('<span class="dlk dlk-og">招满即止</span>'
               '<span class="dlq">' + note + '</span>'
               + (f'<a href="{su}" target="_blank" rel="noopener">'
                  f'{html.escape(v.get("label", "") or "来源")} ↗</a>' if su else
                  html.escape(v.get("label", "") or "公开渠道")))
        dcell = '<b>招满即止</b>'
    else:
        if web:
            srk = ('<span class="dlk dlk-web">联网核对</span>'
                   + (f'<a href="{su}" target="_blank" rel="noopener">'
                      f'{html.escape(v.get("label", "") or "来源")} ↗</a>' if su else
                      html.escape(v.get("label", "") or "公开渠道")))
        else:
            srk = '<span class="dlk dlk-local">公告原文</span>'
            if v.get("evidence"):
                srk += '<span class="dlq">' + html.escape(v["evidence"]) + '</span>'
        dcell = html.escape(ds) + ('<span>已截止</span>' if past else '')
    _dl_rows.append(
        '<div class="dlrow' + past + '">'
        '<div class="dlr-d">' + dcell + '</div>'
        '<div class="dlr-m"><a href="' + esc(k) + '" target="_blank" rel="noopener">' + nm + '</a>'
        '<div class="dlr-s">' + srk + '</div></div></div>')

dl_sec = (
    '<section id="sec4">'
    '<div class="s2head"><h2>简历投递截止时间核对</h2>'
    '<p class="s2desc">对页面内全部 ' + str(VIS_TOTAL) + ' 条招聘信息逐条核对投递截止时间：'
    '优先从就业网公告原文中自动提取（<b>' + str(DL_LOC) + '</b> 条，附原句依据），'
    '原文未写明的再联网核对企业招聘官网 / 公开招聘平台（<b>' + str(DL_WEB) + '</b> 条，附来源链接，'
    '其中 ' + str(DL_ONG) + ' 条官方明确「招满即止 / 尽快投递 / 长期有效」等无固定截止日的表述）。'
    '同一单位以最新公告为准；查不到任何明确表述的，'
    '一律计入「未注明」（' + str(DL_NONE) + ' 条），不做推测。截止时间核对日期：'
    + html.escape(time.strftime("%Y-%m-%d")) + '</p></div>'
    '<div class="dltable">' + (''.join(_dl_rows) or '<div class="dlrow"><div class="dlr-m">暂无</div></div>') + '</div>'
    '</section>')

stat = f"""
<section class="stats">
  <div class="sbox"><div class="snum">{len(items)}</div><div class="slab">招聘信息总数</div></div>
  <div class="sbox"><div class="snum">{sum(1 for i in items if i.get('body'))}</div><div class="slab">含详情正文</div></div>
  <div class="sbox"><div class="snum">{len(dates)}</div><div class="slab">覆盖日期（天）</div></div>
  <div class="sbox"><div class="snum">{len(places)}</div><div class="slab">举办地点（个）</div></div>
  <div class="sbox"><div class="snum">{kinds.get('宣讲会(/zjob)',0)} / {kinds.get('外部招聘(/extxjh)',0)}</div><div class="slab">校内宣讲 / 外部招聘</div></div>
  <div class="sbox"><div class="snum"><span style="font-size:16px">{dates[0] if dates else '-'} → {dates[-1] if dates else '-'}</span></div><div class="slab">时间跨度</div></div>
  <div class="sbox"><div class="snum">{len(notime_items)}</div><div class="slab">未注明宣讲时间</div></div>
  <div class="sbox"><div class="snum">{len(_dl_known)} <span style="font-size:15px">({round(100*len(_dl_known)/VIS_TOTAL) if VIS_TOTAL else 0}%)</span></div><div class="slab">已注明投递截止</div></div>
  <div class="sbox"><div class="snum">{sum(1 for v in _dl_known.values() if v.get("date"))}</div><div class="slab">含具体截止日期</div></div>
  <div class="sbox"><div class="snum">{DL_ONG}</div><div class="slab">招满即止/尽快投递</div></div>
  <div class="sbox"><div class="snum">{len(by_dl)}</div><div class="slab">截止日期（天）</div></div>
  <div class="sbox"><div class="snum">{len(revisions)}</div><div class="slab">公众号核对修订</div></div>
</section>"""

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>华中科技大学就业信息网 · 招聘信息汇总（{len(items)}条）</title>
<style>
:root{{
  --bg:#0f1115; --panel:#171a21; --panel2:#1d2029; --line:#2a2f3a;
  --tx:#e6e8ee; --tx2:#a7adbb; --tx3:#767d8d;
  --acc:#4d8dff; --acc2:#7c5cff; --warn:#ff8f4d; --ok:#3ecf8e;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
 line-height:1.7;-webkit-font-smoothing:antialiased}}
a{{color:var(--acc);text-decoration:none}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 22px 80px}}
header.top{{padding:52px 0 26px;border-bottom:1px solid var(--line);margin-bottom:26px}}
.kicker{{color:var(--acc);font-size:13px;letter-spacing:.18em;text-transform:uppercase;font-weight:600}}
h1{{font-size:34px;margin:12px 0 8px;letter-spacing:-.5px}}
.sub{{color:var(--tx2);font-size:14px}}
.sub code{{background:var(--panel2);padding:2px 7px;border-radius:5px;color:var(--tx)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:26px 0 30px}}
.sbox{{background:linear-gradient(160deg,var(--panel),var(--panel2));border:1px solid var(--line);
 border-radius:12px;padding:16px 18px}}
.snum{{font-size:26px;font-weight:700;letter-spacing:-.5px;background:linear-gradient(90deg,var(--acc),var(--acc2));
 -webkit-background-clip:text;background-clip:text;color:transparent}}
.slab{{font-size:12px;color:var(--tx3);margin-top:2px}}
.bar{{position:sticky;top:0;z-index:20;background:rgba(15,17,21,.92);backdrop-filter:blur(10px);
 border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:18px;
 display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
.bar input,.bar select{{background:var(--panel2);border:1px solid var(--line);color:var(--tx);
 border-radius:8px;padding:8px 11px;font-size:13px;font-family:inherit;outline:none}}
.bar input{{flex:1;min-width:200px}}
.bar input:focus,.bar select:focus{{border-color:var(--acc)}}
.btn{{background:var(--panel2);border:1px solid var(--line);color:var(--tx2);border-radius:8px;
 padding:8px 13px;font-size:13px;cursor:pointer;font-family:inherit;white-space:nowrap}}
.btn:hover{{border-color:var(--acc);color:var(--tx)}}
.btn.on{{background:var(--acc);border-color:var(--acc);color:#fff}}
.cnt{{color:var(--tx3);font-size:12px;margin-left:auto}}
.upd{{font-size:12px;padding:4px 11px;border-radius:20px;border:1px solid var(--line);
 background:var(--panel2);color:var(--tx3);white-space:nowrap;cursor:pointer;user-select:none}}
.upd.loading{{color:var(--acc);border-color:#2c3f5e}}
.upd.ok{{color:var(--ok);border-color:#264a3a}}
.upd.new{{color:var(--warn);border-color:#4a3a2a;background:#2a2015}}
.upd.warn{{color:#ffb020;border-color:#4a3c1e}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:10px;
 overflow:hidden;transition:border-color .15s}}
.card:hover{{border-color:#3a4250}}
.card.hide{{display:none}}
.chead{{display:flex;gap:14px;align-items:flex-start;padding:15px 18px;cursor:pointer;user-select:none}}
.cidx{{font-size:12px;color:var(--tx3);font-variant-numeric:tabular-nums;padding-top:5px;min-width:32px}}
.cmain{{flex:1;min-width:0}}
.ctitle{{margin:0 0 8px;font-size:16px;font-weight:600;line-height:1.45;word-break:break-word}}
.cinfo{{display:flex;gap:8px;flex-wrap:wrap}}
.tag{{font-size:12px;padding:2px 9px;border-radius:20px;border:1px solid var(--line);color:var(--tx2);
 background:var(--panel2);white-space:nowrap}}
.tag-t{{color:var(--warn);border-color:#4a3a2a}}
.tag-p{{color:var(--ok);border-color:#264a3a}}
.tag-k{{color:var(--tx3)}}
.tag-w{{color:#ffb020;border-color:#4a3c1e}}
/* 公众号核对 / 修订标注 */
.tag.rv{{cursor:help}}
.tag.rv-add{{color:#4ade80;border-color:#264a3a}}
.tag.rv-fix{{color:#ff8a5c;border-color:#5a3324}}
.tag.rv-ref{{color:#7dd3fc;border-color:#28455a}}
.tag.rv-ok{{color:var(--tx2);border-color:var(--line)}}
.card.rvcard{{border-color:#3a5a46}}
.card.nt-filled{{border-color:#3a5a46}}
.rvbox{{border:1px solid var(--line);border-left:3px solid var(--tx3);border-radius:8px;
  padding:10px 12px;margin:10px 0 12px;background:var(--panel2);font-size:13px}}
.rvbox.rv-add{{border-left-color:#4ade80}}
.rvbox.rv-fix{{border-left-color:#ff8a5c}}
.rvbox.rv-ref{{border-left-color:#7dd3fc}}
.rvbox.rv-ok{{border-left-color:var(--tx3)}}
.rvhead{{font-weight:600;color:var(--tx1);display:flex;justify-content:space-between;
  align-items:baseline;gap:10px;margin-bottom:6px}}
.rvtime{{font-weight:400;font-size:11px;color:var(--tx3)}}
.rvbody div{{display:flex;gap:10px;padding:2px 0}}
.rvbody span{{color:var(--tx3);min-width:56px;flex:none}}
.rvbody b{{font-weight:500;color:var(--tx1);word-break:break-all}}
.rvbody b.new{{color:#4ade80}}
.rvbody a{{color:var(--acc)}}
/* 修订记录总览 */
.rvlist{{display:flex;flex-direction:column;gap:8px;margin-top:10px}}
.rvitem{{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--panel2)}}
.rvitem .rt{{font-weight:600;color:var(--tx1);font-size:13px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}}
.rvitem .rt .badge{{font-size:11px;padding:1px 7px;border-radius:20px;border:1px solid var(--line);
  color:var(--tx3);font-weight:400}}
.rvitem .rc{{font-size:12px;color:var(--tx2);margin-top:5px;line-height:1.7;word-break:break-all}}
.rvitem .rc .k{{color:var(--tx3);margin-right:6px}}
.rvitem .rc del{{color:var(--tx3)}}
.rvitem .rc ins{{color:#4ade80;text-decoration:none}}
.wxsrc{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}
.wxsrc a{{font-size:12px;color:var(--acc);border:1px solid var(--line);border-radius:6px;
  padding:3px 9px;background:var(--panel2)}}
/* 每条信息的来源与更新时间 */
.src{{margin-top:6px;font-size:12px;color:var(--tx3);line-height:1.6}}
.dist{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:18px}}
.dh{{font-size:13px;color:var(--tx3);margin-bottom:12px}}
.dbars{{display:flex;gap:3px;align-items:flex-end;height:130px;overflow-x:auto;padding-bottom:4px}}
.dbar{{flex:1;min-width:22px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
 cursor:pointer;height:100%}}
.dcol{{width:70%;max-width:24px;background:linear-gradient(180deg,var(--acc),var(--acc2));
 border-radius:4px 4px 0 0;min-height:3px;transition:opacity .15s}}
.dbar:hover .dcol{{opacity:.65}}
.dlb{{font-size:10px;color:var(--tx3);margin-top:5px;white-space:nowrap}}
.dnum{{font-size:10px;color:var(--tx2);font-variant-numeric:tabular-nums}}
.dbar.on .dcol{{box-shadow:0 0 0 2px var(--tx)}}
.dbar.on .dlb{{color:var(--tx);font-weight:600}}
.dbar-nt{{margin-left:9px;padding-left:9px;border-left:1px dashed var(--line)}}
.dbar-nt .dcol{{background:linear-gradient(180deg,#ffb020,#ff7a45)}}
.dbar-nt .dlb{{color:#ffb020;min-width:32px}}
.dbar-nt.on .dcol{{box-shadow:0 0 0 2px #ffd24d}}
.dbar-nt.on .dlb{{color:#ffd24d;font-weight:600}}
.dhint{{color:var(--tx3);font-weight:400}}
/* 简历投递截止日期分布 */
.dist2 .dcol{{background:linear-gradient(180deg,#3ecf8e,#2f9e6b)}}
.dbar-dl.dl-past .dcol{{background:linear-gradient(180deg,#4a5163,#343a49)}}
.dbar-dl.dl-past .dlb,.dbar-dl.dl-past .dnum{{color:#5c6478}}
.dbar-dl.sel .dcol{{box-shadow:0 0 0 2px var(--ok)}}
.dbar-dl.sel .dlb{{color:var(--ok);font-weight:700}}
.dbar-none{{margin-left:9px;padding-left:9px;border-left:1px dashed var(--line)}}
.dbar-ong{{margin-left:9px;padding-left:9px;border-left:1px dashed var(--line)}}
.dbar-ong .dcol{{background:linear-gradient(180deg,#ffd24d,#e8a80c)}}
.dbar-ong .dlb{{color:#ffd24d;min-width:32px}}
.dbar-ong.sel .dcol{{box-shadow:0 0 0 2px #ffd24d}}
.dbar-ong.sel .dlb{{color:#fff;font-weight:700}}
.dbar-none .dcol{{background:linear-gradient(180deg,#ffb020,#ff7a45)}}
.dbar-none .dlb{{color:#ffb020;min-width:32px}}
.dbar-none.sel .dcol{{box-shadow:0 0 0 2px #ffd24d}}
.dbar-none.sel .dlb{{color:#ffd24d;font-weight:700}}
/* 截止时间标签与依据框 */
.tag-dl{{color:#7dd3fc;border-color:#28455a;cursor:help}}
.tag-dl.dl-web{{color:#c4b5fd;border-color:#3c3260}}
.tag-dl-og{{color:#ffd24d;border-color:#5a4a1e}}
.dlbox{{border:1px solid var(--line);border-left:3px solid #7dd3fc;border-radius:8px;
 padding:10px 12px;margin:12px 0;background:var(--panel2);font-size:13px}}
.dlbox.dl-web{{border-left-color:#c4b5fd}}
.dlbox.dl-og{{border-left-color:#ffd24d}}
.dlbox.dl-og .dlhead{{color:#ffd24d}}
.dlhead{{font-size:13px;font-weight:600;color:#7dd3fc;display:flex;gap:10px;align-items:baseline}}
.dlbox.dl-web .dlhead{{color:#c4b5fd}}
.dlsrc{{font-size:11px;font-weight:400;color:var(--tx3)}}
.dlbody{{margin-top:6px;display:grid;gap:4px}}
.dlbody>div{{display:flex;gap:8px}}
.dlbody span{{color:var(--tx3);min-width:66px;flex:none}}
.dlbody b{{font-weight:500;color:var(--tx2);word-break:break-word}}
.dlbody b.new{{color:var(--ok);font-weight:600}}
/* 区块四：截止时间核对明细 */
.dltable{{max-height:620px;overflow-y:auto;border:1px solid var(--line);border-radius:10px;
 background:var(--panel)}}
.dlrow{{display:flex;gap:12px;padding:9px 14px;border-bottom:1px solid var(--line)}}
.dlrow:last-child{{border-bottom:none}}
.dlrow.past{{opacity:.62}}
.dlr-d{{flex:none;width:96px;font-size:12px;color:var(--tx3)}}
.dlr-d b{{display:block;color:var(--tx2);font-size:13px;font-variant-numeric:tabular-nums}}
.dlrow.past .dlr-d b{{text-decoration:line-through}}
.dlr-d span{{font-size:11px;color:#ff8f4d}}
.dlr-m{{min-width:0}}
.dlr-m>a{{color:var(--tx);font-size:13px}}
.dlr-s{{font-size:12px;color:var(--tx3);margin-top:3px;display:flex;gap:8px;
 align-items:baseline;flex-wrap:wrap}}
.dlk{{font-size:11px;padding:1px 7px;border-radius:20px;border:1px solid var(--line);flex:none}}
.dlk-local{{color:#7dd3fc;border-color:#28455a}}
.dlk-web{{color:#c4b5fd;border-color:#3c3260}}
.dlk-og{{color:#ffd24d;border-color:#5a4a1e}}
.dlq{{color:var(--tx3);opacity:.85;word-break:break-word}}
.bar .keepnt{{display:block!important}}
.ntnote{{display:none;background:#2a2015;border:1px solid #4a3a2a;color:#ffcf7a;
 border-radius:10px;padding:10px 14px;font-size:13px;margin-bottom:14px;line-height:1.7}}
.ntnote b{{color:#ffe9b0}}
/* 未注明时间模式下，仅适用于主表的控件隐藏，避免误操作 */
.bar.notime #q,.bar.notime #p,.bar.notime #onlyBtn,.bar.notime #sortBtn,
.bar.notime #expBtn,.bar.notime #colBtn{{display:none}}
.carrow{{color:var(--tx3);font-size:14px;transition:transform .2s;padding-top:4px}}
.card.open .carrow{{transform:rotate(180deg);color:var(--acc)}}
.star{{color:var(--tx3);font-size:20px;line-height:1;padding:5px 6px;margin:-2px -2px 0 0;
 cursor:pointer;border-radius:8px;flex-shrink:0;user-select:none;transition:color .15s,background .15s}}
.star:hover{{color:#ffd24d;background:var(--panel2)}}
.card.fav .star{{color:#ffd24d}}
.card.fav .star:hover{{color:#ffea9e}}
.card.fav{{border-color:#4a4326}}
.card.fav .ctitle{{color:#ffe9b0}}
.cbody{{display:none;border-top:1px solid var(--line);padding:16px 18px 18px;background:#12141a}}
.card.open .cbody{{display:block}}
.meta{{list-style:none;padding:0;margin:0 0 14px;display:grid;
 grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:6px 18px;
 border-bottom:1px dashed var(--line);padding-bottom:12px}}
.meta li{{font-size:13px;color:var(--tx2);display:flex;gap:8px}}
.meta span{{color:var(--tx3);min-width:62px;flex-shrink:0}}
.meta b{{font-weight:500;color:var(--tx);word-break:break-all}}
.content{{font-size:14.5px;color:#d3d7e0;overflow-wrap:break-word}}
.content img{{max-width:100%;height:auto;border-radius:8px;margin:8px 0;display:block}}
.content p{{margin:8px 0}}
.content table{{width:100%!important;border-collapse:collapse;margin:10px 0;font-size:13.5px}}
.content td,.content th{{border:1px solid var(--line);padding:6px 9px}}
.content a{{word-break:break-all}}
.content .empty{{color:var(--tx3);font-size:13px}}
.content.nt{{white-space:pre-wrap;color:#c6cbd6;font-size:13.5px;line-height:1.8;
 max-height:340px;overflow-y:auto;background:var(--panel2);border:1px solid var(--line);
 border-radius:8px;padding:12px 14px}}
.cfoot{{margin-top:14px;padding-top:12px;border-top:1px solid var(--line);font-size:13px}}
.s2head{{margin:44px 0 18px;padding:22px 24px;background:linear-gradient(160deg,var(--panel),var(--panel2));
 border:1px solid var(--line);border-radius:12px}}
.s2head h2{{margin:0 0 8px;font-size:22px;letter-spacing:-.3px}}
.s2head h2::before{{content:"🕐 ";}}
.s2desc{{margin:0;font-size:13.5px;color:var(--tx2);line-height:1.75}}
.bar2{{position:static;background:var(--panel)}}
.fav-empty{{display:none;text-align:center;padding:56px 20px;color:var(--tx3)}}
.fav-empty .fe-star{{font-size:44px;margin-bottom:10px;color:#5a5340}}
.fav-empty .fe-t{{font-size:17px;color:var(--tx2);margin-bottom:6px}}
.fav-empty .fe-s{{font-size:13px}}
.favonly-note{{display:none;font-size:12.5px;color:#ffd24d;background:#2a2415;border:1px solid #4a4326;
 border-radius:10px;padding:10px 14px;margin-bottom:12px}}
.favonly-note b{{color:#ffe9b0}}
footer{{margin-top:44px;padding-top:22px;border-top:1px solid var(--line);color:var(--tx3);font-size:12.5px}}
@media(max-width:640px){{h1{{font-size:25px}}.wrap{{padding:0 14px 60px}}}}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div class="kicker">HUST Career · 数据快照</div>
  <h1>华中科技大学就业信息网 · 招聘信息汇总</h1>
  <div class="sub">数据源：<code>{html.escape(D['source'])}</code>
    {f'＋ 公众号「{html.escape(WX_ACCOUNT)}」（核对修订 {len(revisions)} 处，{html.escape(REV_AT or '')}）' if WX_ACCOUNT else ''}
    ｜ 初始抓取：{D['crawled_at']} ｜ 最近更新：{D.get('last_update') or D.get('last_check') or '—'}
    ｜ 宣讲会 {len(items)} 条 ｜ 未注明宣讲时间 {len(notime_items)} 条
    ｜ 投递截止已注明 {len(_dl_known)} 条（公告原文 {DL_LOC} · 联网核对 {DL_WEB}）</div>
</header>

{stat}
{dist}
{dist2}

<div class="bar">
  <input id="q" placeholder="搜索公司 / 岗位关键词…" oninput="filter()">
  <select id="d" onchange="filter()"><option value="">全部日期</option>{date_opts}</select>
  <select id="p" onchange="filter()"><option value="">全部地点</option>{place_opts}</select>
  <select id="dl" class="keepnt" onchange="setDl(this.value)">{dl_opts}</select>
  <button class="btn" id="onlyBtn" onclick="onlyHas()">仅看有正文</button>
  <button class="btn" id="favBtn" onclick="favOnly()" title="只显示加入关注的宣讲会">★ 我的关注 <span id="favN"></span></button>
  <button class="btn" id="sortBtn" onclick="sortByTime()">时间 ↓</button>
  <button class="btn" id="expBtn" onclick="toggleAll(true)">展开全部</button>
  <button class="btn" id="colBtn" onclick="toggleAll(false)">收起全部</button>
  <button class="btn" id="updBtn" onclick="checkUpdate(false)">检查更新</button>
  <span class="upd" id="upd" title="点击检查源站是否有新发布的招聘信息">检测中…</span>
  <span class="cnt" id="cnt"></span>
</div>

<div class="ntnote" id="notimeNote">当前筛选：<b>未注明宣讲时间</b> · 共 {NT_COUNT} 条，已定位至下方专栏；上方主表宣讲会（均带具体日期）已隐藏。在日期分布中选择具体日期或「全部日期」可返回主表。</div>

<div id="list">
{''.join(rows)}
</div>

<section id="sec2">
  <div class="s2head">
    <h2>未注明宣讲时间</h2>
    <p class="s2desc">收录华中科技大学就业信息网「招聘信息」栏目发布的公告（网申 / 简章 / 启事类）。
    此类公告通常不注明具体宣讲时间，集中收录于此；后续确认时间后可补充并移入上方主表。
    字段与主表一致：单位名称、宣讲时间（待确认）、发布日期、信息来源。</p>
  </div>
  <div class="bar bar2">
    <input id="q2" placeholder="搜索单位 / 岗位关键词…" oninput="filter2()">
    <select id="d2" onchange="filter2()"><option value="">全部发布日期</option>{ndate_opts}</select>
    <select id="dl2" onchange="setDl(this.value)">{dl_opts}</select>
    <button class="btn" id="sort2Btn" onclick="sort2ByDate()">发布 ↓</button>
    <button class="btn" onclick="toggleAll2(true)">展开全部</button>
    <button class="btn" onclick="toggleAll2(false)">收起全部</button>
    <span class="cnt" id="cnt2"></span>
  </div>
  <div id="list2">
  {''.join(rows2)}
  </div>
</section>
{rev_sec}
{dl_sec}
<div id="favEmpty" class="fav-empty" style="display:none">
  <div class="fe-star">☆</div>
  <div class="fe-t">「我的关注」还是空的</div>
  <div class="fe-s">点击任意宣讲会右侧的星标即可加入；再点一次移出。</div>
</div>

<footer>
  本页面由自动化脚本从华中科技大学就业信息网公开页面抓取生成，仅供个人求职参考。<br>
  原始详情页保存于同目录 <code>raw/</code>，结构化数据保存于 <code>data/jobs.json</code>。
</footer>
</div>

<script>
var asc = false, onlyHasOn = false, favOnlyOn = false;
var NT_TOTAL = {NT_COUNT};
/* 简历投递截止日期筛选：'' | 'YYYY-MM-DD' | 'NONE'(未注明)，三者互斥，同一时刻只生效一种 */
var dlCur = '';
/* ---------- 我的关注（收藏专栏） ---------- */
var FAVKEY = 'hustFavs';
var favs = [];
try {{ favs = JSON.parse(localStorage.getItem(FAVKEY) || '[]'); }} catch(e) {{ favs = []; }}
if (!Array.isArray(favs)) favs = [];
function favSave(){{
  localStorage.setItem(FAVKEY, JSON.stringify(favs));
  /* 有本地服务时同步到服务端（data/favs.json），换浏览器/清缓存也不丢 */
  try {{
    fetch('api/favs', {{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{keys:favs}})}}).catch(function(){{}});
  }} catch(e) {{}}
}}
function favToggle(ev, el){{
  if (ev) {{ ev.stopPropagation(); }}
  var card = el.closest('.card');
  var k = card.dataset.key;
  var i = favs.indexOf(k);
  if (i > -1) {{ favs.splice(i,1); }} else {{ favs.push(k); }}
  favSave();
  favRender();
}}
function favOnly(){{
  favOnlyOn = !favOnlyOn;
  document.getElementById('favBtn').classList.toggle('on', favOnlyOn);
  filter(); filter2();
}}
function favRender(){{
  document.querySelectorAll('.card').forEach(function(c){{
    c.classList.toggle('fav', favs.indexOf(c.dataset.key) > -1);
  }});
  document.getElementById('favN').textContent = favs.length ? '(' + favs.length + ')' : '';
  if (favOnlyOn) {{ filter(); filter2(); }}
}}
function favLoadRemote(){{
  /* 服务端保存的收藏优先（file:// 与 http:// 打开表现一致） */
  fetch('api/favs', {{cache:'no-store'}}).then(function(r){{ return r.json(); }}).then(function(j){{
    if (j.ok && Array.isArray(j.keys) && j.keys.length >= favs.length) {{
      favs = j.keys; favSave(); favRender();
    }} else if (j.ok && Array.isArray(j.keys)) {{
      /* 本地更多时以本地为准并回写服务端 */
      favSave();
    }}
  }}).catch(function(){{}});
}}
function toggle(i){{
  document.getElementById('b'+i).parentElement.classList.toggle('open');
}}
function toggleAll(open){{
  document.querySelectorAll('.card').forEach(function(c){{
    if(c.classList.contains('hide')) return;
    if(open) c.classList.add('open'); else c.classList.remove('open');
  }});
}}
function pickDate(d){{
  document.getElementById('d').value = d; filter();
  /* 未注明时间：定位到下方专栏；具体日期：定位到主表工具栏 */
  var t = (d === 'NOTIME') ? document.getElementById('sec2') : document.querySelector('.bar');
  t.scrollIntoView({{behavior:'smooth',block:'start'}});
}}
/* ---------- 简历投递截止日期筛选 ---------- */
function setDl(v){{
  dlCur = v || '';
  var a = document.getElementById('dl'), b = document.getElementById('dl2');
  if (a) a.value = dlCur;
  if (b) b.value = dlCur;
  filter(); filter2();
}}
function pickDl(d){{
  /* 再次点击同一根柱子 = 取消该筛选（回到全部截止日期） */
  dlCur = (dlCur === d) ? '' : d;
  var ntMode = (document.getElementById('d').value === 'NOTIME');
  setDl(dlCur);
  var t = ntMode ? document.getElementById('sec2') : document.querySelector('.bar');
  t.scrollIntoView({{behavior:'smooth',block:'start'}});
}}
function dlLabel(){{ return dlCur === 'NONE' ? '未注明' : (dlCur === 'ONGOING' ? '招满即止' : dlCur); }}
function onlyHas(){{
  onlyHasOn = !onlyHasOn;
  document.getElementById('onlyBtn').classList.toggle('on', onlyHasOn);
  filter();
}}
function filter(){{
  var q=document.getElementById('q').value.trim().toLowerCase();
  var d=document.getElementById('d').value;
  var p=document.getElementById('p').value;
  var ntMode = (d === 'NOTIME');   /* 未注明时间：与具体日期互斥的独立筛选态 */
  var dlNone = (dlCur === 'NONE');  /* 未注明投递截止：与具体截止日期互斥 */
  var n=0;
  document.querySelectorAll('#list .card').forEach(function(c){{
    var ok=(!q||c.dataset.title.indexOf(q)>-1||c.dataset.place.indexOf(q)>-1)
        && (!d||ntMode||c.dataset.date===d) && (!p||c.dataset.place===p)
        && (!onlyHasOn||c.dataset.has==='1')
        && (!favOnlyOn||c.classList.contains('fav'))
        && (dlNone ? !c.dataset.dl : (!dlCur||c.dataset.dl===dlCur));
    c.classList.toggle('hide',!ok); if(ok)n++;
  }});
  /* 未注明时间模式：主表整体隐藏，仅展示下方专栏 */
  document.getElementById('list').style.display = ntMode ? 'none' : '';
  document.getElementById('notimeNote').style.display = ntMode ? 'block' : 'none';
  document.querySelector('.bar').classList.toggle('notime', ntMode);
  /* 选中具体日期时结果不得包含未注明时间的招聘信息：隐藏专栏二；全部日期时恢复 */
  document.getElementById('sec2').style.display = (d && !ntMode) ? 'none' : '';
  /* 日期分布图选中态与当前筛选保持一致 */
  document.querySelectorAll('#distTalk .dbar').forEach(function(b){{
    b.classList.toggle('on', b.dataset.d === d);
  }});
  /* 投递截止日期分布图选中态 */
  document.querySelectorAll('.dbar-dl').forEach(function(b){{
    b.classList.toggle('sel', b.dataset.d === dlCur);
  }});
  document.getElementById('cnt').textContent = ntMode
    ? '未注明宣讲时间 ' + NT_TOTAL + ' 条 · 见下方专栏'
    : '显示 '+n+' 条' + (dlCur ? ' · 投递截止 ' + dlLabel() : '');
  MAIN_N = ntMode ? 0 : n;
  document.getElementById('favEmpty').style.display = (favOnlyOn && MAIN_N===0 && SEC2_N===0) ? 'block' : 'none';
}}
function sortByTime(){{
  asc=!asc;
  var list=document.getElementById('list');
  var arr=Array.prototype.slice.call(list.children);
  arr.sort(function(a,b){{
    var x=a.dataset.date+' '+a.querySelector('.tag-t').textContent;
    var y=b.dataset.date+' '+b.querySelector('.tag-t').textContent;
    return asc? x.localeCompare(y) : y.localeCompare(x);
  }});
  arr.forEach(function(c){{list.appendChild(c)}});
  document.getElementById('sortBtn').textContent=asc?'时间 ↑':'时间 ↓';
  document.getElementById('sortBtn').classList.toggle('on',asc);
}}

/* ---------- 专栏二：未注明宣讲时间 ---------- */
var asc2 = false, SEC2_N = 0, MAIN_N = 0;
function toggle2(j){{
  document.getElementById('c'+j).parentElement.classList.toggle('open');
}}
function toggleAll2(open){{
  document.querySelectorAll('#list2 .card').forEach(function(c){{
    if(open) c.classList.add('open'); else c.classList.remove('open');
  }});
}}
function filter2(){{
  var q=document.getElementById('q2').value.trim().toLowerCase();
  var d=document.getElementById('d2').value;
  var dlNone = (dlCur === 'NONE');
  var n=0;
  document.querySelectorAll('#list2 .card').forEach(function(c){{
    var ok=(!q||c.dataset.title.indexOf(q)>-1)
        && (!d||c.dataset.date===d)
        && (!favOnlyOn||c.classList.contains('fav'))
        && (dlNone ? !c.dataset.dl : (!dlCur||c.dataset.dl===dlCur));
    c.classList.toggle('hide',!ok); if(ok)n++;
  }});
  document.getElementById('cnt2').textContent='显示 '+n+' / '
    +document.querySelectorAll('#list2 .card').length+' 条'
    +(dlCur ? ' · 投递截止 ' + dlLabel() : '');
  SEC2_N = n;
  document.getElementById('favEmpty').style.display = (favOnlyOn && MAIN_N===0 && SEC2_N===0) ? 'block' : 'none';
}}
function sort2ByDate(){{
  asc2=!asc2;
  var list=document.getElementById('list2');
  var arr=Array.prototype.slice.call(list.children);
  arr.sort(function(a,b){{
    return asc2? a.dataset.date.localeCompare(b.dataset.date) : b.dataset.date.localeCompare(a.dataset.date);
  }});
  arr.forEach(function(c){{list.appendChild(c)}});
  document.getElementById('sort2Btn').textContent=asc2?'发布 ↑':'发布 ↓';
  document.getElementById('sort2Btn').classList.toggle('on',asc2);
}}

/* ---------- 自动更新检测 ---------- */
/* 依赖本地服务（python server.py）提供的同源接口；
   直接以 file:// 打开时无法跨域访问源站，降级为静态快照提示 */
var UPD = document.getElementById('upd');
var BUSY = false;
function setStatus(txt, cls){{
  UPD.textContent = txt; UPD.className = 'upd ' + (cls || '');
}}
function api(p){{
  return fetch(p, {{cache:'no-store'}}).then(function(r){{
    if(!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }});
}}
function doRefresh(){{
  setStatus('正在拉取新信息…', 'loading');
  BUSY = true;
  api('api/refresh').then(function(j){{
    BUSY = false;
    if(!j.ok){{
      setStatus(j.busy ? '更新进行中…' : '更新失败', 'warn');
      return;
    }}
    if(j.rebuilt){{
      setStatus('已更新 ' + j.added + ' 条，正在刷新…', 'ok');
      setTimeout(function(){{ location.reload(); }}, 1200);
    }} else {{
      setStatus('已是最新 · ' + (j.updated_at || ''), 'ok');
    }}
  }}).catch(function(){{ BUSY = false; setStatus('更新服务未连接', 'warn'); }});
}}
function checkUpdate(auto){{
  if(BUSY) return;
  setStatus('检查源站…', 'loading');
  api('api/check').then(function(j){{
    if(!j.ok){{
      setStatus('源站暂时不可达 · 显示本地快照', 'warn');
      return;
    }}
    if(j.has_update){{
      setStatus('发现 ' + j.new_count + ' 条新信息', 'new');
      if(auto !== false) doRefresh();
    }} else {{
      setStatus('已是最新 · ' + (j.checked_at || '').slice(5), 'ok');
    }}
  }}).catch(function(){{
    setStatus('未连接更新服务', 'warn');
    UPD.title = '当前是静态快照。运行 start.bat 启动本地服务后，打开页面会自动检查并同步源站最新信息。';
  }});
}}
UPD.onclick = function(){{ checkUpdate(false); }};
/* 距上次自动检查超过 60 秒才发起，避免频繁刷新打源站 */
var lastChk = parseInt(sessionStorage.getItem('lastChk') || '0', 10);
if(Date.now() - lastChk > 60000) {{
  sessionStorage.setItem('lastChk', String(Date.now()));
  setTimeout(function(){{ checkUpdate(true); }}, 300);
}} else {{
  setStatus('已是最新（本次会话已检查）', 'ok');
}}
filter();
filter2();
favRender();
favLoadRemote();
</script>
</body>
</html>"""

out = os.path.join(ROOT, "index.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"已生成 {out}  ({len(HTML)/1024:.0f} KB, {len(items)} 条)")
