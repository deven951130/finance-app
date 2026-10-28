"""
打包清單檢查：新增的程式檔有沒有被放進安裝檔。

為什麼要測：installer/build_runtime.py 的 APP_FILES 是手寫的清單，
新增一個最上層的 .py（例如 quotes.py）卻忘了加，安裝版一打開就會「找不到模組」。
"""

import glob
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 不是程式執行時需要的檔案（開發工具），不用打包
NOT_SHIPPED = {"seed_example.py"}


def load_build_runtime():
    path = os.path.join(ROOT, "installer", "build_runtime.py")
    spec = importlib.util.spec_from_file_location("build_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # 只載入，不會執行打包（打包在 main() 裡）
    return module


def test_最上層的程式檔都有打包進安裝檔():
    shipped = set(load_build_runtime().APP_FILES)
    top_level = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.py"))} - NOT_SHIPPED
    assert top_level - shipped == set(), "這些檔案沒有加進 installer/build_runtime.py 的 APP_FILES"


def test_models_的程式檔都有打包():
    shipped = {p.replace("\\", "/") for p in load_build_runtime().APP_FILES}
    models = {f"models/{os.path.basename(p)}" for p in glob.glob(os.path.join(ROOT, "models", "*.py"))}
    assert models <= shipped
