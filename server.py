# -*- coding: utf-8 -*-
"""
本地服务：托管招聘信息报告，并提供同源更新接口。

浏览器禁止 file:// 页面跨域请求就业网、也无权写本地文件，
因此由本服务代为抓取源站（同源，无跨域问题）并更新本地数据。

  python server.py            # 启动（默认端口 8765，占用则顺延）并打开浏览器
  python server.py 9000       # 指定端口
  python server.py --no-open  # 不自动打开浏览器
"""
import os
import sys
import json
import time
import socket
import threading
import webbrowser
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import update as upd  # noqa: E402
from reparse import load  # noqa: E402

_lock = threading.Lock()  # 保证同一时刻只有一个更新任务


def _json(handler, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        # 页面与数据一律不缓存，保证每次打开都是最新
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        msg = fmt % args
        if "/api/" in (self.path or "") or "404" in msg:
            sys.stderr.write("  %s - %s\n" % (self.date_time_string(), msg))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/favicon.ico":  # 避免浏览器自动请求触发 404 报错
            self.send_response(204)
            self.end_headers()
            return

        if path == "/api/status":
            try:
                d = load()
            except Exception as e:
                return _json(self, {"ok": False, "error": str(e)}, 500)
            return _json(self, {
                "ok": True,
                "count": len(d.get("items", [])),
                "site_total": d.get("total"),
                "crawled_at": d.get("crawled_at"),
                "last_update": d.get("last_update"),
                "last_check": d.get("last_check"),
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })

        if path == "/api/check":
            try:
                return _json(self, upd.check())
            except Exception as e:
                return _json(self, {"ok": False, "error": str(e)}, 500)

        if path == "/api/favs":
            return _json(self, {"ok": True, "keys": load_favs()})

        if path == "/api/refresh":
            if not _lock.acquire(blocking=False):
                return _json(self, {"ok": False, "error": "已有更新任务在进行中", "busy": True})
            try:
                full = "full" in urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query)
                return _json(self, upd.apply(full=full))
            except Exception as e:
                return _json(self, {"ok": False, "error": str(e)}, 500)
            finally:
                _lock.release()

        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/favs":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                keys = [k for k in (payload.get("keys") or []) if isinstance(k, str)][:2000]
                save_favs(keys)
                return _json(self, {"ok": True, "count": len(keys)})
            except Exception as e:
                return _json(self, {"ok": False, "error": str(e)}, 400)
        return _json(self, {"ok": False, "error": "not found"}, 404)


FAVS_FILE = os.path.join(ROOT, "data", "favs.json")


def load_favs():
    if os.path.exists(FAVS_FILE):
        try:
            return json.load(open(FAVS_FILE, encoding="utf-8")).get("keys", [])
        except Exception:
            pass
    return []


def save_favs(keys):
    os.makedirs(os.path.dirname(FAVS_FILE), exist_ok=True)
    with open(FAVS_FILE, "w", encoding="utf-8") as f:
        json.dump({"keys": keys, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False)


def free_port(start=8765, tries=20):
    for p in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def startup_update():
    """启动后在后台静默增量更新一次"""
    if not _lock.acquire(blocking=False):
        return
    try:
        print("  启动检查：正在比对源站…", flush=True)
        r = upd.apply()
        if r.get("ok"):
            if r.get("added"):
                print(f"  启动检查：新增 {r['added']} 条，报告已更新", flush=True)
            else:
                print("  启动检查：已是最新，无需更新", flush=True)
        else:
            print("  启动检查：失败 -", r.get("error"), flush=True)
    except Exception as e:
        print("  启动检查异常:", e, flush=True)
    finally:
        _lock.release()


def main():
    args = [a for a in sys.argv[1:]]
    no_open = "--no-open" in args
    port = None
    for a in args:
        if a.isdigit():
            port = int(a)
    if port is None:
        port = free_port()

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/index.html"
    print("=" * 56)
    print("  华中科技大学招聘信息 · 本地服务已启动")
    print(f"  访问地址: {url}")
    print("  更新接口: /api/check（检查）  /api/refresh（更新）")
    print("  关闭服务: 在本窗口按 Ctrl+C")
    print("=" * 56)

    if not no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    threading.Thread(target=startup_update, daemon=True).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务")
        srv.shutdown()


if __name__ == "__main__":
    main()
