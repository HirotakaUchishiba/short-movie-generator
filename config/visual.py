"""動画の基本表示設定 (= 解像度 / FPS / 言語)。

config/__init__.py から段階分割 (= §3.1.4-b)。FONT_* / TITLE_* / SUBTITLE_*
等の字幕系は別 sub-module (= 将来 PR) で扱う。
"""

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 60

LANGUAGE = "ja"
