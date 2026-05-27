import json
import logging
import os
import subprocess

import config

logger = logging.getLogger(__name__)


def _get_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", path],
        capture_output=True, text=True, timeout=30,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _write_textfile(temp_dir: str, name: str, text: str) -> str:
    path = os.path.join(temp_dir, f"drawtext_{name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _escape_fontfile(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _scene_offsets(scenes: list[dict]) -> list[float]:
    """screenplay の scene.duration の累積で offset を計算 (= 想定値ベース)。

    slow_mo 延長や lipsync 後処理で実 scene_<S>.mp4 の尺がここから乖離する
    場合があるため、可能な限り _scene_offsets_from_videos を使うこと。
    """
    offsets = [0.0]
    for scene in scenes[:-1]:
        offsets.append(offsets[-1] + float(scene["duration"]))
    return offsets


def _scene_offsets_from_videos(scene_videos: list[str]) -> list[float]:
    """各 scene_<S>.mp4 の素の実尺累積で offset を計算 (= 実測値ベース)。

    注意: _merge_scenes は各 scene を scene.duration まで tpad 拡張して concat
    するため、merged.mp4 内の実位置とこの素の実尺累積は tail buffer 分だけ
    乖離する。字幕 offset には _scene_offsets_merged を使うこと。本関数は素の
    実尺が必要な箇所専用に残す。
    """
    offsets = [0.0]
    for v in scene_videos[:-1]:
        offsets.append(offsets[-1] + _get_duration(v))
    return offsets


def _merged_scene_length(vid_dur: float, target_dur: float) -> float:
    """_merge_scenes が tpad 後に各 scene へ割り当てる実長 (= concat 後の占有秒)。

    target_dur > vid_dur なら tpad で target_dur まで伸ばし、そうでなければ
    vid_dur のまま。字幕 offset と merge を同じ長さ基準に揃える SSOT。
    閾値 0.05 は _merge_scenes の tpad 条件と一致させる。
    """
    return target_dur if target_dur > vid_dur + 0.05 else vid_dur


def _scene_offsets_merged(
    scene_videos: list[str], scene_durations: list[float],
) -> list[float]:
    """merged.mp4 内の各 scene 開始位置 (= tpad 後の実累積) を返す。

    _merge_scenes が各 scene を _merged_scene_length まで tpad 拡張して concat
    するため、字幕の絶対秒もこの累積で計算する。scene_<S>.mp4 の素の実尺
    (= TTS 音声長) 累積を使うと、duration との差 (= SCENE_TTS_TAIL_BUFFER 由来の
    tpad 無音) が scene ごとに累積し、字幕が発話より先行してしまう。
    """
    offsets = [0.0]
    for v, target in zip(scene_videos[:-1], scene_durations[:-1]):
        offsets.append(
            offsets[-1] + _merged_scene_length(_get_duration(v), float(target)))
    return offsets


def _merge_scenes(scene_videos: list[str], scene_durations: list[float],
                  temp_dir: str) -> str:
    n = len(scene_videos)
    if n == 1:
        return scene_videos[0]

    filter_parts = []
    for i in range(n):
        target_dur = scene_durations[i]
        vid_dur = _get_duration(scene_videos[i])
        pad = ""
        if target_dur > vid_dur + 0.05:
            pad = f",tpad=stop=-1:stop_mode=clone:stop_duration={target_dur - vid_dur:.3f}"
        elif vid_dur > target_dur + 0.1:
            # screenplay の duration 編集忘れ / slow_mo 後の整合性ズレで
            # 動画が想定より長いケース。concat 自体は走るが、字幕 timing は
            # screenplay 想定値ベースで計算されるため、後半の字幕が動画後ろに
            # 余って見えなくなる可能性がある。warning で気付けるようにする。
            logger.warning(
                "シーン%d: 実動画 %.2fs が想定 %.2fs より %.2fs 長い — "
                "字幕タイミングがズレる可能性。screenplay の scene.duration を "
                "更新するか scene を再生成してください",
                i + 1, vid_dur, target_dur, vid_dur - target_dur,
            )
        filter_parts.append(
            f"[{i}:v]scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
            f"setsar=1,fps={config.FPS}{pad}[v{i}]"
        )

    concat_inputs = "".join(f"[v{i}][{i}:a]" for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[mv][ma]")
    filter_complex = ";\n".join(filter_parts)
    merged_path = os.path.join(temp_dir, "merged.mp4")

    cmd = ["ffmpeg", "-y"]
    for v in scene_videos:
        cmd.extend(["-i", v])
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[mv]", "-map", "[ma]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        merged_path,
    ])

    logger.info("シーン結合中")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        logger.error("Merge error: %s", r.stderr[-1500:])
        raise RuntimeError("Scene merge failed")
    return merged_path


def _line_window(line: dict, next_line: dict | None,
                 scene_duration: float,
                 scene_real_duration: float | None = None) -> tuple[float, float]:
    """シーン内 line の表示開始/終了 (秒) を返す。

    scene_real_duration が指定された場合、line.start / line.end を
    scene_real / scene_sp の比率で線形リスケールする。
    シーン内で slow_mo 延長が一様にかかっている前提で、内部 line タイミングが
    動画 timeline と整合するようにする。
    """
    ratio = 1.0
    if scene_real_duration and scene_duration > 0:
        ratio = scene_real_duration / scene_duration

    start = float(line["start"]) * ratio
    if "end" in line:
        end = float(line["end"]) * ratio
    elif next_line is not None:
        end = float(next_line["start"]) * ratio
    else:
        end = scene_real_duration if scene_real_duration else scene_duration
    return start, end


# 字幕 chunk 分割で「ここで切ると自然」と判定する文字集合。
# 優先度: STRONG (= 文末記号) > SPACE > DOT > PARTICLES > TERMINAL の順で
# 探索し、最初に見つかったものを境界に採用する (= _find_natural_split_pos)。

# 句読点 / 感嘆符 (= 文末・文節末。ASCII , . は念のため両対応、TTS では事前除去済)
_BREAK_STRONG = "、。！？!?,."
# 全角・半角空白 (= 既に視覚的な区切りなのでそこで切る)
_BREAK_SPACE = "　 "
# 中黒 (= 並列項目の区切り。例: "AI・機械学習")
_BREAK_DOT = "・"
# 主要助詞 (1文字、これらの「直後」で切る)
_BREAK_PARTICLES_1CHAR = set("はがをにでとやもへ")
# 終助詞 (これらの「直前」で切る) — 文末が明確なものに限定。
# 「な/か/よ」は会話表現で「かな」「なあ」のように続くことが多いため除外
# (代わりに _FORBIDDEN_BIGRAMS で結合を保護する)。
_BREAK_TERMINAL = set("ねさ")

# 「絶対に切ってはいけない」2 文字パターン。
# 助動詞 / 補助動詞 / 活用形 / 慣用結合 の中央で分断するのを防ぐ。
# left=text[i-1], right=text[i] の bigram を _FORBIDDEN_BIGRAMS と照合する。
_FORBIDDEN_BIGRAMS: frozenset[str] = frozenset({
    # 助動詞 (です / ます 系)
    "です", "でし", "でし", "でき",
    "ます", "まし", "ませ",
    "した", "して", "しま", "しょ",
    "せん", "せる", "され", "した",
    # 完了 / 過去
    "った", "って", "っち", "っぱ", "っと", "っく", "っき", "っぽ", "っす", "っ！", "っ？",
    "だっ", "なっ", "あっ", "いっ", "うっ", "とっ", "やっ", "もっ", "知っ",
    # 否定
    "ない", "なく", "なか", "なし",
    # 受身 / 可能 / 使役
    "れる", "られ", "れた", "せる", "させ",
    # 願望 / 意思
    "たい", "たく", "たか", "よう", "ろう",
    # 進行形 / 結果
    "てる", "てい", "でる", "でい",
    # 縮約形
    "じゃ", "ちゃ", "ちょ", "きゃ",
    # 接続
    "だが", "だけ", "だし", "けど", "ので", "のに",
    "から", "まで", "より", "とか", "って",
    # 形容詞活用末尾
    "くな", "かっ", "かろ",
    # 終助詞・感嘆 (会話表現の最後)
    "かな", "かね", "かよ", "なあ", "なぁ", "なー", "な〜",
    "だな", "だね", "だよ", "だぁ", "だー", "わよ", "わね", "わな",
    "んだ", "んね", "るん", "んな", "んよ",
    "ねぇ", "ねー", "よね", "よな", "よぉ", "よう", "けど",
    # 数字 + 単位
    "1ヶ", "2ヶ", "3ヶ", "4ヶ", "5ヶ", "6ヶ", "7ヶ", "8ヶ", "9ヶ", "0ヶ",
    "1万", "1億", "1千", "1百",
})


def _is_forbidden_break(left: str, right: str) -> bool:
    """この left|right 境界で切ったら不自然になるか。"""
    return (left + right) in _FORBIDDEN_BIGRAMS


def _is_katakana(ch: str) -> bool:
    return bool(ch) and ("゠" <= ch <= "ヿ" or ch == "ー")


def _is_kanji(ch: str) -> bool:
    return bool(ch) and "一" <= ch <= "鿿"


def _is_hiragana(ch: str) -> bool:
    return bool(ch) and "぀" <= ch <= "ゟ"


def _break_score_at(text: str, i: int) -> int:
    """位置 i で text を [:i] と [i:] に分けるときのスコア。
    高いほど切るのに自然、負は「絶対に切らない」を意味する。"""
    if i <= 0 or i >= len(text):
        return 0
    left = text[i - 1]
    right = text[i]

    # ★★★★ 絶対に切ってはいけない (= 助動詞 / 活用形 / 慣用結合の中)
    if _is_forbidden_break(left, right):
        return -1000

    # ★★★ 強い改行点
    if left in _BREAK_STRONG:
        return 100
    if left in _BREAK_SPACE:
        return 95
    if left == "」" or left == "』" or left == ")" or left == "）":
        return 92
    if right == "「" or right == "『" or right == "(" or right == "(":
        return 90
    if left in _BREAK_DOT:
        return 85
    # 終助詞の直前
    if right in _BREAK_TERMINAL:
        return 70

    # ★★ 主要助詞の直後 (= 助詞→次の本文)
    if left in _BREAK_PARTICLES_1CHAR:
        # right が漢字/カタカナ/数字/記号なら「真の助詞境界」 (本文への切替) → 60
        # right がひらがなの場合、left は実は助詞でなく動詞活用末尾の可能性が
        # 高い (例: 「ま+に+あう」「な+に+を」)。降格する。
        rh = _is_hiragana(right)
        if rh:
            return 5
        # ただし right が補助動詞末尾候補 (す/た/て/り/っ) なら降格
        if right in "すたてりっ":
            return 10
        return 60

    # ★ ひらがな → 漢字 境界 (= 助詞・送り仮名から本文への切替)
    lh = _is_hiragana(left)
    rh = _is_hiragana(right)
    lj = _is_kanji(left)
    rj = _is_kanji(right)
    if lh and rj:
        return 30

    # ★ カタカナ ↔ 漢字 / ひらがな (複合語境界)
    lk = _is_katakana(left)
    rk = _is_katakana(right)
    if lk != rk:
        # ただし right がひらがな 1 文字目で「っ/た/て/す/り」 (= 動詞活用形)
        # の場合は降格 (例: "テスト" + "を" は 60 で別経路)
        if rh and right in "すたてりっなく":
            return 5
        return 35

    # ☆ 漢字 → ひらがな は基本的に切らない (動詞 + 送り仮名)
    # 例: 「行」+「く」「来」+「た」を分断したくない
    if lj and rh:
        return 0

    # ☆ ひらがな ↔ ひらがな は基本切らない (= 同一語の中)
    if lh and rh:
        return 0

    return 0


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    """日本語テキストを最大 max_chars 文字の chunks に分割する (ホワイトリスト方式)。

    切ってよいのは _break_score_at が **正のスコア** を返す位置のみ:
      ★★★ 句読点 / スペース / 鉤括弧境界
      ★★  助詞直後 (right が漢字/カタカナ/数字/記号のときだけ) / 終助詞直前
      ★   カタカナ↔漢字 / ひらがな→漢字 境界
    `_FORBIDDEN_BIGRAMS` の中、漢字↔ひらがな (= 動詞+送り仮名)、ひらがな↔ひらがな
    の中ではスコア 0 か負になり、絶対に切らない。

    max_chars は「目標値」であって硬い上限ではない。自然な break point が無い
    場合は max_chars を超えてでも (rest 全体まで) 探索を続け、それでも無ければ
    1 chunk としてそのまま残す。**機械的・不自然な分断は絶対しない方針**。
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    rest = text
    safety = 0
    while len(rest) > max_chars and safety < 200:
        safety += 1
        ideal = max_chars
        best_pos: int | None = None
        best_score = 0  # ホワイトリスト: 正のスコアのみ採用 (0 は不採用)

        # Phase 1: ideal 周辺 ±9 を探索
        lo1 = max(2, max_chars - 9)
        hi1 = min(len(rest) - 1, max_chars + 4)
        for i in range(hi1, lo1 - 1, -1):
            s = _break_score_at(rest, i)
            if s <= 0:
                continue
            s_adj = s - abs(i - ideal) * 2
            if s_adj > best_score:
                best_score = s_adj
                best_pos = i

        # Phase 2: 周辺で見つからなければ全範囲をスキャン (距離ペナルティ弱)
        if best_pos is None:
            for i in range(2, len(rest)):
                s = _break_score_at(rest, i)
                if s <= 0:
                    continue
                # 全範囲なので距離ペナルティを軽く (1点)
                s_adj = s - abs(i - ideal) * 1
                if s_adj > best_score:
                    best_score = s_adj
                    best_pos = i

        if best_pos is None:
            # 自然な break point がどこにも無い → 分断せず 1 chunk として残す
            logger.warning(
                "[subtitle chunks] 自然な break point が rest 全体に見つからず "
                "1 chunk として保持: %r",
                rest,
            )
            break

        chunks.append(rest[:best_pos])
        rest = rest[best_pos:]

    if rest:
        chunks.append(rest)
    return chunks


def _wrap_subtitle_text(text: str, max_chars: int) -> str:
    """日本語字幕を max_chars 以内に折り返す (改行で連結)。
    内部実装は _split_into_chunks を流用 (= chunk を改行でつなぐだけ)。"""
    chunks = _split_into_chunks(text, max_chars)
    return "\n".join(chunks) if chunks else text


def _resolve_subtitle_timings(
    items: list[dict],
    line_start: float,
    line_end: float,
) -> list[tuple[float, float]]:
    """`subtitles[]` の手動チャンクの時刻を解決する。

    各 item は {text, start (optional), end (optional)}。両方欠落しているチャンクは
    line.start - line.end の中で「アンカー (= 固定された start/end や line 端)」
    の間を文字数比例で配分して埋める。混在 (一部だけ手動) もサポート。

    返り値は items と同じ並びの (start_abs, end_abs) リスト。
    """
    n = len(items)
    if n == 0:
        return []

    # boundaries[i] = i 番目のチャンクの開始時刻 (i=n は最後のチャンクの終了)
    # 既知の境界 (= line 端 + ユーザー指定値) で先に埋め、残った None を比例配分。
    # 隣接 anchor が逆転していると後勝ちで前を silent に上書きするため、
    # 上書き発生時は warning ログで気付けるようにする (validator が事前に reject
    # するのが望ましいが、互換 / 古い snapshot 経由で残る可能性があるため)。
    boundaries: list[float | None] = [None] * (n + 1)
    boundaries[0] = line_start
    boundaries[n] = line_end
    for i, it in enumerate(items):
        s = it.get("start")
        e = it.get("end")
        if s is not None:
            new_v = float(s)
            if boundaries[i] is not None and abs(boundaries[i] - new_v) > 1e-3:
                logger.warning(
                    "[subtitle-anchor] chunk %d: start=%.3f が既存境界 %.3f を "
                    "上書きします (隣接 anchor の順序違反の可能性)",
                    i, new_v, boundaries[i],
                )
            boundaries[i] = new_v
        if e is not None:
            new_v = float(e)
            if boundaries[i + 1] is not None and abs(boundaries[i + 1] - new_v) > 1e-3:
                logger.warning(
                    "[subtitle-anchor] chunk %d: end=%.3f が既存境界 %.3f を "
                    "上書きします (line 端 / 次 chunk start との競合の可能性)",
                    i, new_v, boundaries[i + 1],
                )
            boundaries[i + 1] = new_v

    # 連続する None セグメントを前後の確定境界の間で文字数比例で埋める
    i = 0
    while i < n:
        # boundaries[i] は確定済み (line_start もしくは前ループで埋め済み)
        j = i + 1
        while j <= n and boundaries[j] is None:
            j += 1
        # boundaries[j] が確定境界 (= 最終境界 boundaries[n]=line_end は確定なので必ず存在)
        if j > i + 1:
            seg_start = boundaries[i]
            seg_end = boundaries[j]
            seg_chunks = items[i:j]
            total_chars = sum(len((c.get("text") or "")) for c in seg_chunks)
            if total_chars <= 0 or seg_end <= seg_start:
                # フォールバック: 均等割
                step = (seg_end - seg_start) / max(1, len(seg_chunks))
                for k in range(len(seg_chunks) - 1):
                    boundaries[i + k + 1] = seg_start + step * (k + 1)
            else:
                cursor = seg_start
                for k in range(len(seg_chunks) - 1):
                    cursor += (seg_end - seg_start) * (
                        len(seg_chunks[k].get("text") or "") / total_chars
                    )
                    boundaries[i + k + 1] = cursor
        i = j

    return [(boundaries[i], boundaries[i + 1]) for i in range(n)]


def _allocate_chunk_timings(
    chunks: list[str], line_start: float, line_end: float,
) -> list[tuple[float, float]]:
    """chunks に line.start - line.end を文字数比例で配分する。

    短い chunk は短く、長い chunk は長く表示される。
    末尾は浮動小数誤差を避けるため line_end に揃える。
    """
    if not chunks:
        return []
    total_chars = sum(len(c) for c in chunks)
    if total_chars <= 0:
        # フォールバック: 均等分割
        n = len(chunks)
        step = (line_end - line_start) / max(1, n)
        return [(line_start + i * step, line_start + (i + 1) * step)
                for i in range(n)]

    duration = max(0.0, line_end - line_start)
    timings: list[tuple[float, float]] = []
    cursor = line_start
    for c in chunks:
        d = duration * (len(c) / total_chars)
        timings.append((cursor, cursor + d))
        cursor += d
    if timings:
        ls, _ = timings[-1]
        timings[-1] = (ls, line_end)
    return timings


def _allocate_chunk_timings_from_char_ts(
    chunks: list[str], line_start: float, line_end: float,
    char_start: int, pos_to_time: list,
) -> list[tuple[float, float]] | None:
    """chunks を char_ts の実発話時刻幅で line 表示窓 (line_start-line_end) に配分。

    各 chunk の文字位置に対応する char_ts (= TTS 自身の forced alignment) の時刻幅で
    重み付けする。char_ts 総長と表示窓長は snap / 実尺リスケールで一致しないため、
    char_ts の相対位置を表示窓へ比率スケールして絶対時刻に変換する。char_ts が引け
    ない chunk があれば None を返し、呼出側が文字数比例へ fallback する。
    """
    spans: list[tuple[float, float]] = []
    cursor = char_start
    n = len(pos_to_time)
    for c in chunks:
        end_char = cursor + len(c)
        c_start = c_end = None
        for i in range(cursor, min(end_char, n)):
            if pos_to_time[i]:
                c_start = pos_to_time[i]["start"]
                break
        for i in range(min(end_char, n) - 1, cursor - 1, -1):
            if pos_to_time[i]:
                c_end = pos_to_time[i]["end"]
                break
        if c_start is None or c_end is None:
            return None
        spans.append((c_start, c_end))
        cursor = end_char
    ts0, ts1 = spans[0][0], spans[-1][1]
    ts_dur = ts1 - ts0
    win_dur = line_end - line_start
    if ts_dur <= 0 or win_dur <= 0:
        return None
    scale = win_dur / ts_dur
    timings = [
        (line_start + (cs - ts0) * scale, line_start + (ce - ts0) * scale)
        for cs, ce in spans
    ]
    timings[-1] = (timings[-1][0], line_end)
    return timings


def _needs_overlay(screenplay: dict) -> bool:
    for sc in screenplay.get("scenes", []):
        for line in sc.get("lines") or []:
            if not line.get("hidden"):
                return True
    return False


def _compute_line_chunks_and_timings(
    *,
    line: dict,
    next_line: dict | None,
    offset: float,
    duration: float,
    scene_real: float | None,
    chunk_enabled: bool,
    chunk_max_chars: int,
    line_max_chars: int,
    pos_to_time: list | None = None,
    char_start: int | None = None,
) -> tuple[list[str], list[tuple[float, float]]]:
    """1 line を字幕 chunks + 各 chunk の (start, end) timing に変換する。

    manual_subs (= ``line.subtitles[]``) があれば ratio で timeline に lift し
    ``_resolve_subtitle_timings`` で隣接 chunk 間の境界を確定する。無ければ
    ``chunk_enabled`` / 文字数しきい値に応じて ``_split_into_chunks`` /
    ``_wrap_subtitle_text`` で chunk 化する。
    空 text / 全 sub が空 text なら ``([], [])`` を返す。
    """
    manual_subs = line.get("subtitles") or []
    if manual_subs:
        ratio = (scene_real / duration) if (scene_real and duration > 0) else 1.0
        rel_start, rel_end = _line_window(line, next_line, duration, scene_real)
        line_start_abs = offset + rel_start
        line_end_abs = offset + rel_end

        resolver_items: list[dict] = []
        for sub in manual_subs:
            sub_text = (sub.get("text") or "").strip()
            if not sub_text:
                continue
            item: dict = {"text": sub_text}
            if sub.get("start") is not None:
                item["start"] = offset + float(sub["start"]) * ratio
            if sub.get("end") is not None:
                item["end"] = offset + float(sub["end"]) * ratio
            resolver_items.append(item)

        if not resolver_items:
            return [], []

        # 全 chunk が start/end 未指定 (= 手動分割のみで手打ち time 無し) かつ
        # char_ts があれば char_ts 実時刻で配分する (自動分割と同じ精度)。手打ち
        # start/end が 1 つでもあれば従来の anchor 配分 (_resolve_subtitle_timings)
        # を尊重する。
        all_auto = all(
            it.get("start") is None and it.get("end") is None
            for it in resolver_items
        )
        resolved = None
        if all_auto and pos_to_time is not None and char_start is not None:
            resolved = _allocate_chunk_timings_from_char_ts(
                [it["text"] for it in resolver_items],
                line_start_abs, line_end_abs, char_start, pos_to_time)
        if resolved is None:
            resolved = _resolve_subtitle_timings(
                resolver_items, line_start_abs, line_end_abs)
        return [it["text"] for it in resolver_items], resolved

    rel_start, rel_end = _line_window(line, next_line, duration, scene_real)
    abs_start = offset + rel_start
    abs_end = offset + rel_end
    text = line["text"].strip()
    if not text:
        return [], []

    if chunk_enabled:
        chunks = _split_into_chunks(text, chunk_max_chars)
        timings = None
        if pos_to_time is not None and char_start is not None:
            timings = _allocate_chunk_timings_from_char_ts(
                chunks, abs_start, abs_end, char_start, pos_to_time)
        if timings is None:  # char_ts 不在 / gap は文字数比例へ fallback
            timings = _allocate_chunk_timings(chunks, abs_start, abs_end)
    else:
        chunks = [_wrap_subtitle_text(text, line_max_chars)]
        timings = [(abs_start, abs_end)]
    return chunks, timings


def _load_char_timing(screenplay: dict, temp_dir: str) -> dict | None:
    """単独話者の char_ts (tts_full.json) を読み、pos_to_time + 各 line の char_start を返す。

    config OFF / per-voice (複数話者) / 読込失敗は None を返し、呼出側は従来の文字数
    比例 chunk 配分に倒れる (= 後方互換)。per-voice は char_ts が speaker ごとに
    tts_full.<base>.json に分かれ line.speaker 解決が要るため Phase 2 とし、ここでは
    None (fallback) を返す。
    """
    if not getattr(config, "SUBTITLE_TIMING_FROM_CHAR_TS", True):
        return None
    from stages.text_mapping import (
        build_position_to_time_map,
        build_screenplay_text,
    )
    # 各 line の speaker base を集計 (per-voice では base ごとに char_ts が分かれる)
    speakers_by_line: dict[tuple[int, int], str | None] = {}
    bases: set[str] = set()
    for s_idx, sc in enumerate(screenplay.get("scenes") or []):
        for l_idx, ln in enumerate(sc.get("lines") or []):
            sp = ln.get("speaker")
            base = sp.split("__")[0] if isinstance(sp, str) and sp else None
            speakers_by_line[(s_idx, l_idx)] = base
            if base:
                bases.add(base)

    full_text, line_specs = build_screenplay_text(screenplay)

    def _load_pos(path: str) -> list | None:
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return build_position_to_time_map(full_text, json.load(f))
        except (OSError, ValueError):
            return None

    pos_by_base: dict[str | None, list] = {}
    if len(bases) <= 1:
        # 単独話者 (0 or 1 base): tts_full.json
        pos = _load_pos(os.path.join(temp_dir, "tts_full.json"))
        if pos is None:
            return None
        pos_by_base[next(iter(bases), None)] = pos
    else:
        # per-voice: 各 base の tts_full.<base>.json。一部でも欠ければ全体 fallback
        for b in bases:
            pos = _load_pos(os.path.join(temp_dir, f"tts_full.{b}.json"))
            if pos is None:
                return None
            pos_by_base[b] = pos

    starts = {
        (s["scene_idx"], s["line_idx"]): s["char_start"] for s in line_specs
    }
    return {
        "pos_by_base": pos_by_base,
        "char_starts": starts,
        "speakers_by_line": speakers_by_line,
    }


def _build_overlay_filter(screenplay: dict, temp_dir: str,
                            scene_videos: list[str] | None = None) -> str:
    """字幕オーバーレイ filter_complex を組み立てる。

    scene_videos が指定されたら **実 timeline ベース** で字幕の絶対時刻を
    計算する (= scene_<S>.mp4 の実尺累積で offset を決め、シーン内の
    line.start / end も scene_real / scene_sp 比でリスケール)。
    指定しない場合は scene.duration ベースで動く。
    """
    font = _escape_fontfile(config.FONT_PATH)
    H = config.VIDEO_HEIGHT
    scenes = screenplay.get("scenes", [])

    use_real_timeline = (
        scene_videos is not None and len(scene_videos) == len(scenes)
    )
    if use_real_timeline:
        # merged.mp4 は各 scene を scene.duration まで tpad して concat する。
        # 字幕 offset もその tpad 後累積に揃える (= 素の実尺累積だと
        # SCENE_TTS_TAIL_BUFFER 分だけ字幕が発話に先行し scene ごとに累積する)。
        # line.start/end は TTS char_ts 由来 (= 音声基準で slow_mo の影響を
        # 受けない) ため、ここで実尺リスケールはかけない (scene_real=None)。
        scene_durations = [float(s["duration"]) for s in scenes]
        offsets = _scene_offsets_merged(scene_videos, scene_durations)
        real_durations = [None] * len(scenes)
    else:
        offsets = _scene_offsets(scenes)
        real_durations = [None] * len(scenes)

    line_max_chars = int(getattr(config, "SUBTITLE_MAX_CHARS_PER_LINE", 17))
    chunk_enabled = bool(getattr(config, "SUBTITLE_CHUNK_ENABLED", True))
    chunk_max_chars = int(getattr(config, "SUBTITLE_CHUNK_MAX_CHARS", 8))
    char_timing = _load_char_timing(screenplay, temp_dir)

    filters: list[str] = []
    cur_in = "0:v"
    tag_idx = 0

    def next_tag() -> str:
        nonlocal tag_idx
        tag_idx += 1
        return f"ov{tag_idx}"

    sub_y_from_bottom = int(
        screenplay.get("subtitle_y_from_bottom")
        if screenplay.get("subtitle_y_from_bottom") is not None
        else config.SUBTITLE_Y_FROM_BOTTOM
    )
    sub_y = H - sub_y_from_bottom

    for s_idx, scene in enumerate(scenes):
        offset = offsets[s_idx]
        duration = float(scene["duration"])
        scene_real = real_durations[s_idx]

        scene_lines = scene.get("lines") or []
        for l_idx, line in enumerate(scene_lines):
            next_line = scene_lines[l_idx + 1] if l_idx + 1 < len(scene_lines) else None

            if line.get("hidden"):
                continue

            chunks, timings = _compute_line_chunks_and_timings(
                line=line, next_line=next_line,
                offset=offset, duration=duration, scene_real=scene_real,
                chunk_enabled=chunk_enabled, chunk_max_chars=chunk_max_chars,
                line_max_chars=line_max_chars,
                pos_to_time=(
                    char_timing["pos_by_base"].get(
                        char_timing["speakers_by_line"].get((s_idx, l_idx)))
                    if char_timing else None),
                char_start=(char_timing["char_starts"].get((s_idx, l_idx))
                            if char_timing else None),
            )
            if not chunks:
                continue

            for c_idx, (chunk_text, (c_start, c_end)) in enumerate(zip(chunks, timings)):
                tf = _write_textfile(
                    temp_dir,
                    f"sub_{s_idx:03d}_{l_idx:03d}_{c_idx:02d}",
                    chunk_text,
                )
                tf_esc = _escape_fontfile(tf)
                enable_chunk = f"between(t,{c_start:.3f},{c_end:.3f})"
                out = next_tag()
                filters.append(
                    f"[{cur_in}]drawtext=fontfile='{font}':textfile='{tf_esc}':"
                    f"fontsize={config.SUBTITLE_FONT_SIZE}:"
                    f"fontcolor={config.TIME_TEXT_COLOR}:"
                    f"bordercolor={config.TIME_BORDER_COLOR}:"
                    f"borderw={config.FONT_BORDER_WIDTH}:"
                    f"line_spacing={config.SUBTITLE_LINE_GAP}:text_align=C:"
                    f"x=(w-text_w)/2:y={sub_y}:enable='{enable_chunk}'[{out}]"
                )
                cur_in = out

    if not filters:
        return ""

    filters.append(f"[{cur_in}]null[vout]")
    return ";\n".join(filters)


def _apply_overlays(base_video: str, screenplay: dict, temp_dir: str,
                    output_path: str,
                    scene_videos: list[str] | None = None) -> None:
    """base_video に字幕を焼き込む。scene_videos が渡されたら、
    各 scene_<S>.mp4 の実尺ベースで字幕タイミングを計算する。"""
    filter_complex = _build_overlay_filter(
        screenplay, temp_dir, scene_videos=scene_videos)
    if not filter_complex:
        import shutil
        shutil.copyfile(base_video, output_path)
        return

    # ffmpeg が中断したときに output_path に partial mp4 が残るのを防ぐため、
    # 一旦 .tmp に書いて成功時のみ replace する。
    tmp_path = output_path + ".tmp"
    cmd = ["ffmpeg", "-y", "-i", base_video,
           "-filter_complex", filter_complex,
           "-map", "[vout]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k",
           # 出力が .tmp 拡張子なので muxer を明示する。ffmpeg 8.1 系は拡張子から
           # 出力フォーマットを推測できず "Unable to choose an output format" で
           # 失敗するため (= base_video の mp4 と揃える)。
           "-f", "mp4",
           tmp_path]

    logger.info("テロップ焼き込み中")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except BaseException:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as e:
                logger.warning("[overlay] tmp %s 削除失敗: %s", tmp_path, e)
        raise
    if r.returncode != 0:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as e:
                logger.warning("[overlay] tmp %s 削除失敗: %s", tmp_path, e)
        logger.error("Overlay error: %s", r.stderr[-1500:])
        raise RuntimeError("Overlay application failed")
    os.replace(tmp_path, output_path)


def compose_video(
    scene_videos: list[str],
    screenplay: dict,
    temp_dir: str,
    output_path: str,
) -> str:
    scenes = screenplay["scenes"]
    scene_durations = [float(s["duration"]) for s in scenes]

    merged_path = _merge_scenes(scene_videos, scene_durations, temp_dir)
    _apply_overlays(merged_path, screenplay, temp_dir, output_path,
                      scene_videos=scene_videos)
    return output_path
