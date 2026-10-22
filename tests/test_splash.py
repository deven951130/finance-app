"""
啟動頁的 Oneiroverse 開啟畫面（run_app.py 的 loading_html）。

為什麼要測：開啟畫面是把 oneiroverse/splash.js 整段塞進 HTML，
只要裡面有「</script>」就會提早結束、把程式碼當成文字印在畫面上（實際發生過）；
少了圖檔或沒打包進安裝檔時，也要能正常啟動。
"""

import os

import run_app

from tests.test_packaging import load_build_runtime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = ["oneiroverse/splash.js"] + [f"oneiroverse/{n}.png" for n in run_app.SPLASH_LAYERS]


def test_開啟畫面的程式和圖都在():
    for rel in KIT:
        assert os.path.exists(os.path.join(ROOT, rel)), rel


def test_開啟畫面整段放進同一個_script():
    html = run_app.loading_html()
    # 只有兩段 <script>：splash.js 本身、呼叫 play() 的那一行；splash.js 裡的 </ 都改寫過了
    assert html.count("</script>") == 2
    assert "OneiroverseSplash.play" in html
    assert "data:image/png;base64," in html


def test_少了檔案時只顯示文字並直接放行(monkeypatch, tmp_path):
    monkeypatch.setattr(run_app, "resource_path", lambda rel: str(tmp_path / rel))
    html = run_app.loading_html()
    assert "window.ovDone = true" in html
    assert "OneiroverseSplash" not in html


def test_開啟畫面有打包進安裝檔():
    assert set(KIT) <= set(load_build_runtime().APP_FILES)
