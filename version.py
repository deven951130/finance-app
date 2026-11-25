"""
這個程式的版本號。

發布新版時要改這裡（和 Onei Hub catalog 的 release.version 一致）。
2026-11-25 起改用 0.1t1 這種寫法（使用者指定，跟夢境前線一樣），不接續之前的 1.1.5。
比較時只看數字（0.1t1 → [0, 1]），所以 catalog 的 min_version 要一起改，不然會擋住自己。
啟動時會拿它和 Onei Hub 伺服器上的「最低可用版本」比較，太舊就要求更新（見 update_check.py）。
"""

APP_VERSION = "0.1t1"
