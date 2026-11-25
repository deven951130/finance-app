"""
測試版本比較與「要不要強制更新」的判斷（models/version.py），以及連不上時一律放行（update_check.py）。
"""

import re

import update_check
from models.version import is_older, parse_version, update_status
from version import APP_VERSION


def test_版本號用數字比_不是字串比():
    assert is_older("1.0.9", "1.0.10")
    assert not is_older("1.0.10", "1.0.9")
    assert is_older("1.0.0", "1.1.0")
    assert not is_older("1.1.0", "1.1.0")  # 一樣不算舊


def test_版本號的v_後綴_位數():
    assert parse_version("v1.2.3-beta") == [1, 2, 3]
    assert not is_older("1.2", "1.2.0")
    assert is_older("0.9", "1")


CATALOG = {"apps": [
    {"id": "dream-frontline", "min_version": "9.9.9", "release": {"version": "9.9.9"}},
    {"id": "finance-app", "min_version": "1.1.0", "release": {"version": "1.2.0"}},
]}


def test_比最低版本舊_要強制更新():
    assert update_status(CATALOG, "finance-app", "1.0.0") == {"required": True, "latest": "1.2.0", "min": "1.1.0"}


def test_達到最低版本_不用更新():
    assert update_status(CATALOG, "finance-app", "1.1.0")["required"] is False


def test_沒有設定最低版本_不擋():
    catalog = {"apps": [{"id": "finance-app", "release": {"version": "2.0.0"}}]}
    assert update_status(catalog, "finance-app", "1.0.0")["required"] is False


def test_清單裡沒有這個程式_當作不用更新():
    assert update_status({"apps": []}, "finance-app", "1.0.0") is None


def test_連不上伺服器時放行(monkeypatch):
    def offline(*args, **kwargs):
        raise OSError("沒有網路")
    monkeypatch.setattr(update_check.urllib.request, "urlopen", offline)
    assert update_check.check() is None


def test_版本號格式正確():
    # 兩種寫法都可以：1.2.3，或 0.1t1（2026-11-25 起使用者指定的寫法，跟夢境前線的 0.4t9 一樣）
    assert re.fullmatch(r"\d+\.\d+(\.\d+|t\d+)", APP_VERSION)


def test_t_版本號只比前面的數字():
    assert parse_version("0.1t1") == [0, 1]
    assert not is_older("0.1t1", "0.1t1")   # catalog 的 min_version 也是 0.1t1 時不會擋住自己
    assert not is_older("1.1.5", "0.1t1")   # 已安裝 1.1.5 的人不會被強制擋住（Hub 仍會顯示有新版本）
