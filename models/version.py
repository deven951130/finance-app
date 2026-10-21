"""
版本號比較（純函式），和 Onei Hub 用同樣的規則。

只比數字：1.0.10 比 1.0.9 新（字串比較會弄錯）。開頭的 v、後面的 -beta 忽略；位數不同時補 0。
"""


def parse_version(v: str) -> list[int]:
    """'v1.2.3-beta' → [1, 2, 3]"""
    parts = []
    for part in str(v).strip().lstrip("vV").split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return parts


def is_older(current: str, required: str) -> bool:
    """current 比 required 舊時回傳 True。"""
    a, b = parse_version(current), parse_version(required)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return a < b  # list 的比較是逐位比較，和比版本號的規則一樣（像 C++ 的 std::lexicographical_compare）


def update_status(catalog: dict, app_id: str, current: str) -> dict | None:
    """從 Onei Hub 的 catalog 判斷這個程式要不要強制更新。

    回傳 {"required": 是否一定要更新, "latest": 最新版本, "min": 最低可用版本}；
    catalog 裡找不到這個程式時回傳 None（當作不用更新）。
    """
    for app in catalog.get("apps", []):
        if app.get("id") != app_id:
            continue
        minimum = app.get("min_version") or ""
        latest = (app.get("release") or {}).get("version") or ""
        return {
            "required": bool(minimum) and is_older(current, minimum),
            "latest": latest,
            "min": minimum,
        }
    return None
