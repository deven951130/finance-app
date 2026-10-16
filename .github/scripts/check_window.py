"""CI 用：連進視窗裡的網頁引擎（Chrome DevTools Protocol），確認理財系統的畫面真的有顯示。

用法：python check_window.py 9222
做的事：重新載入頁面，最多等 40 秒，看頁面標題會不會變成「個人理財」。
同時把網頁的錯誤訊息（console、JavaScript 例外）印出來，畫面空白時可以知道原因。
"""

import json
import sys
import time
import urllib.request

import websocket  # pip install websocket-client

debug_port = int(sys.argv[1])
pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json"))
page = next(p for p in pages if p.get("type") == "page")
print("page:", page["url"], "title:", page["title"])

ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=5)
next_id = 0


def send(method, params=None):
    global next_id
    next_id += 1
    ws.send(json.dumps({"id": next_id, "method": method, "params": params or {}}))
    return next_id


for domain in ("Runtime.enable", "Log.enable", "Network.enable"):
    send(domain)
send("Page.reload", {"ignoreCache": True})

ok = False
deadline = time.time() + 40
last_check = 0
while time.time() < deadline:
    try:
        msg = json.loads(ws.recv())
    except websocket.WebSocketTimeoutException:
        msg = {}
    method = msg.get("method", "")
    params = msg.get("params", {})
    if method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "warning"):
        print("console:", [a.get("value", a.get("description")) for a in params.get("args", [])])
    elif method == "Runtime.exceptionThrown":
        details = params.get("exceptionDetails", {})
        print("exception:", details.get("exception", {}).get("description") or details.get("text"))
    elif method == "Log.entryAdded":
        entry = params.get("entry", {})
        print("log:", entry.get("level"), entry.get("text"), entry.get("url", ""))
    elif method == "Network.loadingFailed":
        print("network failed:", params.get("errorText"), params.get("blockedReason", ""))
    elif method == "Network.responseReceived":
        r = params.get("response", {})
        if r.get("status", 200) >= 400:
            print("http", r.get("status"), r.get("url"))
    if time.time() - last_check > 2:
        last_check = time.time()
        check_id = send("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
    if msg.get("id") == next_id and "result" in msg and "result" in msg["result"]:
        title = msg["result"]["result"].get("value", "")
        if isinstance(title, str) and "理財" in title:
            ok = True
            break

print("rendered:", ok)
sys.exit(0 if ok else 1)
