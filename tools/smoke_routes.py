# -*- coding: utf-8 -*-
"""对本机运行中的 Flask 逐路由冒烟：GET 一遍所有页面，报告状态码/异常。
用法：python tools/smoke_routes.py http://127.0.0.1:5099
"""
import sys
import urllib.request
import urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5099"
PATHS = [
    "/",
    "/project/new",
    "/project/1", "/project/2", "/project/3",
    "/project/1/edit",
    "/project/1/critical-path.json",
    "/project/1/node/1/edit",        # JSON: 节点编辑器
    "/project/1/alerts",
    "/std-nodes",
    "/std-node/1/edit",
    "/std-node/60/rules",            # 参数化分支节点
    "/std-node/61/rules",
    "/alert-rules",
    "/alert-rule/new",
    "/alerts",
    "/static/style.css",
    "/project/999",                  # 期望 404
    "/no-such-page",                 # 期望 404
]

bad = 0
for p in PATHS:
    url = BASE + p
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "smoke"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            code = r.status
        flag = ""
        if code >= 500:
            flag = "  <<< 服务器错误"; bad += 1
        print(f"  {code}  {p:<34} {len(body)}B{flag}")
    except urllib.error.HTTPError as e:
        code = e.code
        note = "（预期 404）" if code == 404 else "  <<< HTTP 错误"
        if code != 404:
            bad += 1
        print(f"  {code}  {p:<34} {note}")
    except Exception as e:
        bad += 1
        print(f"  ERR {p:<34} {type(e).__name__}: {e}")

print(f"\n异常路由数（非 404 的错误）：{bad}")
