"""
測試資料庫的預設位置：一般執行放在專案的 data/，打包成 exe 時放在家目錄。
"""

import os
import sys

import db


def test_一般執行時放在專案的data資料夾():
    project_dir = os.path.dirname(os.path.abspath(db.__file__))
    assert db.default_db_path() == os.path.join(project_dir, "data", "finance.db")


def test_打包成exe時放在家目錄(monkeypatch):
    # PyInstaller 打包的程式會有 sys.frozen = True，這裡假裝一下
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    expected = os.path.join(os.path.expanduser("~"), "FinanceApp", "finance.db")
    assert db.default_db_path() == expected
