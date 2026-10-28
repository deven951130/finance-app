"""
這個程式的版本號。

發布新版時要改這裡（和 git 標籤 vX.Y.Z、Onei Hub catalog 的 release.version 一致）。
啟動時會拿它和 Onei Hub 伺服器上的「最低可用版本」比較，太舊就要求更新（見 update_check.py）。
"""

APP_VERSION = "1.1.5"
