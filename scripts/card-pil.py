#!/usr/bin/env python3
"""card-pil.py —— 用纯 Python + Pillow 渲染「旧货鉴定」报告卡片。

不依赖浏览器、不调用任何外部命令做渲染、不联网。只要有 Python + Pillow 就能跑。

用法:
    card-pil.py <报告.md> [--out 输出.png] [--width 780] [--scale 3]
    cat 报告.md | card-pil.py - --out out.png

选项:
    --width N        逻辑画布宽（默认 780，手机上正好）
    --scale N        像素密度倍数（默认 3×，780→2340px）
    --head-font P    覆盖标题字体（A/B 对照用；路径不存在时故意用 Pillow 内置默认字体，不静默回退）
    --emoji-mode M   auto | color | draw  —— draw 强制用手绘图形（验证兜底路径）
    --dump-layout    把各块的 y 区间以 JSON 打到 stderr（做像素对照用）

视觉规格（与浏览器版 report-card.py 对齐）:
    纯黑底 #000000、0 圆角 0 阴影，层级只靠边框粗细；色值一律取 Cyber-Lab Dark 设计令牌
    （--fg #ededed / --fg-2 #a1a1a1 / --fg-3 #6e6e6e / --hair-2 #3d3d3d），不自己发明颜色
    顶标：--fg 底 + 黑字小方块，内容取标题里「·」前的部分（没有就写「旧货鉴定」）
    主标题：WDXL 34px；分数块：5px --fg 框 + 🍅/💀 + 60px 大号数字 + 陈旧率 + 鲜/烂徽标
    正文段：左侧 3px --fg 竖线 + 16px 缩进；**加粗** 换同色加粗
    杂音行：--fg-3 #6e6e6e、小一号、上方 3px --fg 线
    省流块：整块反白（--fg 底 + 黑字）+ 5px 同色边

多方区分（人一多，光靠排版认不出谁是谁）:
    段落开头写 [名字] 或 【名字】，这一段就归他：左侧色条换成他的方色 + 段首上方多一行
    「色块 + 名字」小签。条宽/缩进/正文列都不变（仍是 3px + 16px）。
    方色只用 Cyber-Lab Dark 的设计令牌，按出场顺序往下走深浅：
      --fg-2 #a1a1a1 → --dot-done #8f8f8f → --fg-3 #6e6e6e → --hair-2 #3d3d3d
    无归属的段落仍是 --fg #ededed（最亮）。这套系统是单色的，区分靠「深浅 + 文字签」，
    不引入色相；方数超过 4 档时色阶回卷，并在输出里提示。

实现要点:
    · 排版全部在设备像素（逻辑尺寸 × scale）里量，断行才准；画布高度由内容累加得出
    · CSS 盒模型半行距规则：baseline = box_top + (box_h - (asc+desc)) / 2 + asc
    · 中文逐字断行、英文数字按词断；标点粘在前一个字符上 → 永不出现在行首
    · 图绝不裁切：高度 = 内容高度 + 底部内边距（默认 36 逻辑像素）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import re
import sys

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    sys.exit("需要 Pillow：pip install pillow   （python -c 'import PIL' 必须先通过）")

# ─────────────────────────── 颜色 ───────────────────────────
# 一律取「Cyber-Lab Dark」的设计令牌，不自己发明色值。
# 令牌出处：oh-my-life/scripts/oh-my-life.py 的 _PAGE_CSS
BG = (0x00, 0x00, 0x00)        # --bg
FG = (0xED, 0xED, 0xED)        # --fg        正文 / 边框 / 反白块底
FG2 = (0xA1, 0xA1, 0xA1)       # --fg-2      次级（code 等）
FG3 = (0x6E, 0x6E, 0x6E)       # --fg-3      杂音行
HAIR = (0x24, 0x24, 0x24)      # --hair
HAIR2 = (0x3D, 0x3D, 0x3D)     # --hair-2
DOT_DONE = (0x8F, 0x8F, 0x8F)  # --dot-done
# 「烂/鲜」是这张卡自己的语义色（浏览器版 --rot/--fresh），设计系统里没有红绿，保留
ROT = (0xFF, 0x00, 0x00)       # 烂
FRESH = (0x00, 0x80, 0x00)     # 鲜
CODE_C = FG2

# ─────────────────── 排版常量（逻辑像素） ───────────────────
PAD_X, PAD_T, PAD_B = 44, 40, 36

BODY_FS, BODY_LH = 15.5, 1.76
BODY_COLOR = FG               # 正文 = --fg #ededed
P_MT, P_MB = 15, 15
MK_BORDER, MK_PL = 3, 16

# ── 多方区分 ──
# 颜色一律取「Cyber-Lab Dark」的设计令牌（纯黑底 / 单色阶 / 深浅即身份），
# 不自己发明色相 —— 这套系统里没有彩色，区分靠「深浅 + 文字签」。
# 令牌出处：oh-my-life/scripts/oh-my-life.py 的 _PAGE_CSS
#   --fg #ededed / --fg-2 #a1a1a1 / --fg-3 #6e6e6e / --hair-2 #3d3d3d
#   --dot-live #ededed / --dot-idea #a1a1a1 / --dot-done #8f8f8f / --dot-letgo #6e6e6e
PARTY_CHIP_FS, PARTY_CHIP_LH, PARTY_CHIP_LS = 11, 1.76, 0.12
PARTY_SQ, PARTY_SQ_GAP, PARTY_CHIP_GAP = 8, 6, 7
# 无归属段落用 --fg #ededed（最亮）；有归属的按色阶往下走，最深一档到 #3d3d3d
PARTY_COLORS = [
    FG2,          # --fg-2 / --dot-idea
    DOT_DONE,     # --dot-done
    FG3,          # --fg-3 / --dot-letgo
    HAIR2,        # --hair-2
]

KICKER_FS, KICKER_LH, KICKER_LS = 12, 1.76, 2.0
KICKER_PX, KICKER_PY, KICKER_MB = 11, 5, 16

H1_FS, H1_LH = 34, 1.08
H2_FS, H2_LH = 24, 1.76
H2_BORDER, H2_PL, H2_MT, H2_MB = 5, 14, 24, 10

SCORE_BORDER = 5
SCORE_PX, SCORE_PY, SCORE_GAP = 18, 16, 16
SCORE_MT, SCORE_MB = 20, 10
EMO_FS = 44
NUM_FS, NUM_LH, PCT_FS, PCT_ML = 60, 0.86, 24, 2
LAB_FS, LAB_LS, LAB_PB, LAB_LH = 11, 0.16, 7, 1.76
BADGE_FS, BADGE_LS, BADGE_LH = 12, 0.16, 1.76
STAMP_FS, STAMP_LS, STAMP_LH, STAMP_GAP = 26, 0.06, 1.5, 10   # 盖章语（品牌固定语）
BADGE_PX, BADGE_PY, BADGE_MB = 10, 4, 6

NOTE_MT, NOTE_BORDER, NOTE_PT = 22, 3, 14
NOTE_FS, NOTE_LH = 13.5, 1.7

TLDR_MT, TLDR_BORDER, TLDR_PX, TLDR_PY = 26, 5, 18, 16
TLDR_K_FS, TLDR_K_LH, TLDR_K_LS = 12, 1.76, 2
TLDR_V_FS, TLDR_V_LH, TLDR_V_MT = 16.5, 1.6, 8

HR_BORDER, HR_MY = 3, 22

EMO_CHAR = {"烂": "\U0001F480", "鲜": "\U0001F345", "NEW": "\U0001F480"}   # 💀 / 🍅

# ─────────────────────────── 断行规则 ───────────────────────────
# 不能出现在行首的收尾标点（遇到就粘到前一个字符上）
NO_START = set("，。、；：？！）〕］｝〉》」』】…‥·ー～%％″℃”’,.;:?!)]}>")
# 不能出现在行尾的起头标点（遇到就把下一个字符粘过来）
NO_END = set("（〔［｛〈《「『【“‘([{")
EMOJI_RANGES = (
    (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF),
    (0x1F1E6, 0x1F1FF), (0xFE00, 0xFE0F), (0x200D, 0x200D),
)
EMOJI_SKIP = {0xFE0F, 0xFE0E, 0x200D}          # 变体选择符/零宽连接符：不占宽
WORDCH = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
             "%.$€¥£#@&'’_+=~^-\\/µ")


def is_emoji(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in EMOJI_RANGES) and o not in {0xFE00, 0xFE01, 0xFE0F}


# ─────────────────────────── 字体发现 ───────────────────────────
PKG_ROOT = pathlib.Path(__file__).resolve().parent.parent
HEAD_FILES = [
    PKG_ROOT / "assets/fonts/WDXLLubrifontSC-Regular.ttf",     # 主选（随包走）
    PKG_ROOT / "assets/fonts/ZCOOLQingKeHuangYou-Regular.ttf",  # 次选
]

BODY_FAMILY = "Noto Sans CJK SC"
BODY_PATTERNS = [
    # 包内自带的静态 Regular（+ 同目录 Bold 供 _detect_bold 找）—— 随仓库走，任何机器开箱即用
    str(PKG_ROOT / "assets/fonts/NotoSansCJKsc-Regular.otf"),
    str(PKG_ROOT / "assets/fonts/NotoSansCJKsc-Bold.otf"),
    "/run/current-system/sw/share/fonts/**/*CJK*",
    "/usr/share/fonts/**/*CJK*",
    "/usr/local/share/fonts/**/*CJK*",
    "/nix/store/*noto-fonts-cjk*/share/fonts/opentype/noto-cjk/NotoSansCJK*.ttc",
    "/nix/store/*noto-fonts-cjk*/share/fonts/opentype/noto-cjk/NotoSansCJK*.otf",
    "~/.local/share/fonts/**/*CJK*",
    "~/.fonts/**/*CJK*",
    "/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
MONO_FAMILY = "Noto Sans Mono CJK SC"
MONO_PATTERNS = [
    "/run/current-system/sw/share/fonts/**/*MonoCJK*",
    "/usr/share/fonts/**/*MonoCJK*",
    "/nix/store/*noto-fonts-cjk*/share/fonts/opentype/noto-cjk/NotoSansMonoCJK*.ttc",
    "/System/Library/Fonts/Menlo.ttc",
]
EMOJI_FAMILY = "Noto Color Emoji"
EMOJI_PATTERNS = [
    # macOS 的鲜/烂章靠它：钉死首选，不是顺带命中（Linux 退 Noto Color Emoji）
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/run/current-system/sw/share/fonts/**/NotoColorEmoji.ttf",
    "/usr/share/fonts/**/NotoColorEmoji.ttf",
    "/nix/store/*noto-fonts-color-emoji*/share/fonts/noto/NotoColorEmoji.ttf",
    "~/.local/share/fonts/**/NotoColorEmoji.ttf",
]
EMOJI_SIZES = (109, 136, 137, 128, 101, 64, 32)   # CBDT 位图字体只认特定位图尺寸


def _fc_list(family: str) -> list[str]:
    """fc-list 只用来「找路径」，不参与渲染；失败/不存在就静默跳过。"""
    if not family:
        return []
    try:
        import subprocess
        r = subprocess.run(["fc-list", family, "file"], capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        p = line.strip().lstrip(": ").split(":")[0].strip()
        if p and os.path.exists(p) and p not in out:
            out.append(p)
    return out


def _candidates(family: str, patterns: list[str]) -> list[str]:
    hits = _fc_list(family)
    for pat in patterns:
        for p in sorted(glob.glob(os.path.expanduser(pat), recursive=True)):
            if p not in hits:
                hits.append(p)
    return hits


def _probe_index(path: str, family_hint: str) -> int:
    """TTC 里挑出中文（SC）那一份；非集合字体返回 0。"""
    fallback = 0
    for idx in range(8):
        try:
            f = ImageFont.truetype(path, 24, index=idx)
        except Exception:
            break
        try:
            fam = f.getname()[0]
        except Exception:
            fam = ""
        if family_hint and family_hint.lower() in fam.lower():
            return idx
        if fam and "SC" in fam:
            fallback = idx
    return fallback


class FontBook:
    """按需加载 + 缓存；缺字体时逐级回退，并把回退事实记进 self.notes。"""

    def __init__(self, scale: float, head_override: str | None = None, emoji_mode: str = "auto"):
        self.scale = scale
        self.emoji_mode = emoji_mode
        self.notes: list[str] = []
        self._cache: dict = {}
        self._emoji_cache: dict = {}
        self._emoji_base_cache: dict = {}
        self._emoji_strike: int | None = None
        self._emoji_failed = False

        # 标题字体
        self.head_path = None
        self.head_missing = False
        if head_override:
            p = pathlib.Path(os.path.expanduser(head_override))
            if p.exists():
                self.head_path = p
            else:
                # 故意不静默回退到包内字体 —— 否则「字体没生效」这类 bug
                # 会被回退掩盖，A/B 对照两份图字节完全相同而看不出来。
                self.head_missing = True
                self.notes.append(
                    f"标题字体 {head_override} 不存在 → 用 Pillow 内置默认字体（A/B 对照用，故意不静默回退）"
                )
        if self.head_path is None and not self.head_missing:
            for p in HEAD_FILES:
                if p.exists():
                    self.head_path = p
                    break
        if self.head_path is None and not self.head_missing:
            self.notes.append("包内标题字体缺失 → 用正文字体当标题")

        self.body_path, self.body_idx = self._pick(BODY_FAMILY, BODY_PATTERNS, "中文正文字体")
        if self.body_path is None:
            found = [f for f in ("DejaVuSans.ttf",) ]
            sys.exit("找不到中文正文字体（Noto Sans CJK SC）；没法排版，直接失败而不是画出豆腐块。"
                     f"（可放一份到 {PKG_ROOT}/assets/fonts/）")
        mp, mi = self._pick(MONO_FAMILY, MONO_PATTERNS, "等宽小字字体")
        if mp is not None and not self._covers_cjk(mp, mi):
            self.notes.append("等宽字体不含中文字形 → 中文小字回退正文字体")
            mp, mi = None, 0
        self.mono_path, self.mono_idx = (mp, mi) if mp else (self.body_path, self.body_idx)
        ep = self._pick_path(EMOJI_FAMILY, EMOJI_PATTERNS)
        self.emoji_path = ep
        if ep is None:
            self.notes.append("没有彩色 emoji 字体 → 🍅/💀 用手绘图形")
        self.bold_mode, self.bold_name, self.bold_path = self._detect_bold()

    # ---- 发现 ----
    def _pick_path(self, family, patterns):
        for path in _candidates(family, patterns):
            for size in (24, 64, 109, 128, 136):
                try:
                    ImageFont.truetype(path, size)
                    return path
                except Exception:
                    continue
        return None

    def _pick(self, family, patterns, label):
        cands = _candidates(family, patterns)
        # 静态字重文件（Bold/Light…）不是正文本体：Regular 优先，字重交给 _detect_bold 找
        # （同一目录里 "Bold" 按字典序永远排在 "Regular" 前面，不排会整篇用粗体渲染）
        cands.sort(key=lambda p: (
            bool(re.search(r"(Bold|Black|Heavy|Medium|DemiLight|Light)", pathlib.Path(p).name)), p))
        for path in cands:
            try:
                idx = _probe_index(path, family)
                ImageFont.truetype(path, 24, index=idx)
                return path, idx
            except Exception:
                continue
        self.notes.append(f"找不到{label} → 回退")
        return None, 0

    def _covers_cjk(self, path, idx) -> bool:
        """能画出「陈旧率」且不是 .notdef 豆腐块（Menlo 这类纯西文字体在此被拒）。"""
        try:
            f = ImageFont.truetype(path, 24, index=idx)
            real = f.getmask("陈旧率").getbbox()
            notdef = f.getmask("\U000F0000\U000F0001\U000F0002").getbbox()
            return bool(real) and real != notdef
        except Exception:
            return False

    def _detect_bold(self):
        """优先用可变字重的 Bold 实例；否则找独立 Bold 文件；再不然双描 1px 模拟。"""
        try:
            f = ImageFont.truetype(self.body_path, 24, index=self.body_idx)
            names = []
            for n in f.get_variation_names():
                names.append(n.decode() if isinstance(n, (bytes, bytearray)) else str(n))
            for want in ("Bold", "Medium", "DemiLight"):
                if want in names:
                    return "vf", want, None
        except Exception:
            pass
        p = pathlib.Path(self.body_path)
        for pat in (p.name.replace("Regular", "Bold"), p.name.replace("-Regular", "") + ".bold"):
            cand = p.parent / pat
            if cand.exists():
                return "file", None, str(cand)
        for cand in sorted(glob.glob(str(p.parent / "*Bold*.otf*")) + glob.glob(str(p.parent / "*Bold*.tt[cf]"))):
            return "file", None, cand
        return "sim", None, None

    # ---- 取用 ----
    def font(self, role: str, size_logical: float, bold: bool = False):
        dev = max(1, int(round(size_logical * self.scale)))
        key = (role, dev, bold)
        if key in self._cache:
            return self._cache[key]
        if role == "head":
            if self.head_missing:
                try:
                    f = ImageFont.load_default(size=dev)
                except TypeError:  # Pillow < 10.1
                    f = ImageFont.load_default()
                self._cache[key] = f
                return f
            path, idx = ((str(self.head_path), 0) if self.head_path else (self.body_path, self.body_idx))
        elif role == "mono":
            path, idx = self.mono_path, self.mono_idx
        else:
            path, idx = self.body_path, self.body_idx
        f = ImageFont.truetype(path, dev, index=idx)
        if bold and self.bold_mode == "file" and self.bold_path:
            f = ImageFont.truetype(self.bold_path, dev)
        self._set_weight(f, self.bold_name if (bold and self.bold_mode == "vf") else "Regular")
        self._cache[key] = f
        return f

    @staticmethod
    def _set_weight(f, want: str | None):
        """显式指定字重实例。

        NotoSansCJK-VF 这类可变字体的**默认实例是 Thin**（不是 Regular），
        不显式 set_variation_by_name 的话整篇正文都会发虚 —— 实测同一句话
        Thin 只有 1793 点墨迹，Regular 有 3252 点，差近一半。
        """
        if not want:
            return
        try:
            names = [n.decode() if isinstance(n, (bytes, bytearray)) else str(n)
                     for n in f.get_variation_names()]
        except Exception:
            return                      # 静态字体没有字重轴，直接放过
        for cand in (want, "Regular"):
            if cand in names:
                try:
                    f.set_variation_by_name(cand)
                except Exception:
                    pass
                return

    @property
    def bold_sim(self) -> bool:
        return self.bold_mode == "sim"

    def has_font_for(self, ch: str) -> bool:
        try:
            return self.font("body", BODY_FS).getmask(ch).getbbox() is not None
        except Exception:
            return True

    # ---- emoji ----
    def _emoji_base(self, ch: str):
        """把 emoji 画在足够大的 RGBA 上，按 alpha 裁掉空白，得到紧贴的原始位图。"""
        if self._emoji_failed or self.emoji_mode == "draw" or not self.emoji_path:
            return None
        if ch in self._emoji_base_cache:
            return self._emoji_base_cache[ch]
        if self._emoji_strike is None:
            for s in EMOJI_SIZES:
                try:
                    ImageFont.truetype(self.emoji_path, s)
                    self._emoji_strike = s
                    break
                except Exception:
                    continue
            if self._emoji_strike is None:
                self._emoji_failed = True
                self.notes.append("emoji 字体打不开 → 手绘")
        if self._emoji_failed:
            return None
        strike = self._emoji_strike
        try:
            f = ImageFont.truetype(self.emoji_path, strike)
            pad = strike
            canvas = Image.new("RGBA", (strike * 2 + pad, strike * 2 + pad), (0, 0, 0, 0))
            d = ImageDraw.Draw(canvas)
            d.text((pad // 2, pad // 2), ch, font=f, embedded_color=True, anchor="lt")
            box = canvas.getbbox()          # 只看不透明区域 → 多余的透明/白框都被裁掉
            if box is None:
                self._emoji_failed = True
                self.notes.append(f"emoji {ch!r} 画不出墨迹 → 手绘")
                return None
            img = canvas.crop(box)
        except Exception as e:  # noqa: BLE001
            self._emoji_failed = True
            self.notes.append(f"emoji 渲染异常({type(e).__name__}) → 手绘")
            return None
        self._emoji_base_cache[ch] = img
        return img

    def emoji_image(self, ch: str, size_dev: int):
        key = (ch, size_dev)
        if key in self._emoji_cache:
            return self._emoji_cache[key]
        img = None
        base = self._emoji_base(ch)
        if base is not None:
            w, h = base.size
            scale = min(size_dev / w, size_dev / h)
            img = base.resize((max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                              Image.LANCZOS)
        if img is None and ch in (EMO_CHAR["鲜"], EMO_CHAR["烂"]):
            img = draw_tomato(size_dev) if ch == EMO_CHAR["鲜"] else draw_skull(size_dev)
        self._emoji_cache[key] = img
        return img


# ───────────────── 手绘兜底：红色番茄 / 白色骷髅 ─────────────────
def draw_tomato(size: int) -> Image.Image:
    s = max(8, int(size))
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy, r = s / 2, s * 0.565, s * 0.455
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(219, 22, 32, 255))
    d.ellipse([cx - r * 0.66, cy - r * 0.60, cx - r * 0.14, cy - r * 0.16],
              fill=(255, 108, 96, 150))
    ly = cy - r
    lw = s * 0.30
    d.polygon([(cx, ly - s * 0.01), (cx - lw, ly - s * 0.15), (cx - lw * 0.35, ly - s * 0.04)],
              fill=(46, 152, 62, 255))
    d.polygon([(cx, ly - s * 0.01), (cx + lw, ly - s * 0.15), (cx + lw * 0.35, ly - s * 0.04)],
              fill=(46, 152, 62, 255))
    self.rect(d, [cx - s * 0.035, ly - s * 0.23, cx + s * 0.035, ly - s * 0.02],
                fill=(38, 104, 46, 255))
    return im


def draw_bolt(size: int, color=(0, 0, 0)) -> Image.Image:
    """⚡ 是「默认文字呈现」的字符，正版浏览器也把它画成单色 —— 手绘一个更贴。"""
    s = max(8, int(size))
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = tuple(color) + (255,)
    d.polygon([(s * 0.58, s * 0.04), (s * 0.20, s * 0.56), (s * 0.44, s * 0.56),
               (s * 0.36, s * 0.96), (s * 0.80, s * 0.42), (s * 0.54, s * 0.42)],
              fill=col)
    return im


def draw_skull(size: int) -> Image.Image:
    s = max(8, int(size))
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = s / 2
    w, h, top = s * 0.74, s * 0.60, s * 0.09
    d.rounded_rectangle([cx - w / 2, top, cx + w / 2, top + h], radius=w * 0.36,
                        fill=(255, 255, 255, 255))
    jw, jh = w * 0.46, s * 0.21
    d.rounded_rectangle([cx - jw / 2, top + h * 0.80, cx + jw / 2, top + h * 0.80 + jh],
                        radius=s * 0.05, fill=(255, 255, 255, 255))
    ew, eh = w * 0.28, h * 0.34
    ey = top + h * 0.30
    for dx in (-w * 0.25, w * 0.25):
        d.ellipse([cx + dx - ew / 2, ey, cx + dx + ew / 2, ey + eh], fill=(0, 0, 0, 255))
    d.polygon([(cx, top + h * 0.60), (cx - w * 0.085, top + h * 0.84),
               (cx + w * 0.085, top + h * 0.84)], fill=(0, 0, 0, 255))
    lw = max(1, int(round(s * 0.032)))
    for i in (-1, 0, 1):
        x = cx + i * jw * 0.30
        d.line([(x, top + h * 0.80), (x, top + h * 0.80 + jh * 0.82)], fill=(0, 0, 0, 255), width=lw)
    return im


# ─────────────────────────── Markdown 解析 ───────────────────────────
def _strip_italic(s: str) -> str:
    return re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)


# 段落归属标记：[名字] 或 【名字】，写在段落最前面
PARTY_RE = re.compile(r"^\s*(?:\[([^\[\]]{1,16})\]|【([^【】]{1,16})】)\s*")


def parse_md(md: str) -> list[dict]:
    blocks: list[dict] = []
    para: list[str] = []

    def flush():
        if para:
            text = " ".join(para)
            m = PARTY_RE.match(text)
            party = None
            if m:
                party = (m.group(1) or m.group(2)).strip()
                text = text[m.end():].lstrip()
            blocks.append({"t": "p", "text": text, "party": party})
            para.clear()

    for raw in md.splitlines():
        s = raw.strip()
        if not s:
            flush()
            continue
        if s in ("---", "***", "___"):
            flush()
            blocks.append({"t": "hr"})
            continue
        if s.startswith("# "):
            flush()
            title = s[2:].strip()
            kicker = "旧货鉴定"
            if "·" in title:
                k, t = title.split("·", 1)
                if k.strip():
                    kicker = k.strip()
                title = t.strip()
            blocks.append({"t": "head", "kicker": kicker, "title": _strip_italic(title)})
            continue
        if s.startswith("## "):
            flush()
            blocks.append({"t": "h2", "text": _strip_italic(s[3:].strip())})
            continue
        if "新鲜度" in s and re.search(r"\d+\s*%", s):
            flush()
            blocks.append(_parse_score(s))
            continue
        if s.startswith("**省流") or s.startswith("省流"):
            flush()
            body = re.sub(r"^\**\s*省流[：:]\s*", "", s).strip().strip("*").strip()
            blocks.append({"t": "tldr", "text": body})
            continue
        if s.startswith("**先说清楚") or s.startswith("先说清楚"):
            flush()
            body = re.sub(r"^\**\s*先说清楚[：:]\s*", "", s).strip().strip("*").strip()
            body = body.replace("**", "")   # 引言块统一细体，不吃段内加粗
            blocks.append({"t": "clarify", "text": body})
            continue
        if s.startswith("*") and s.endswith("*") and not s.startswith("**"):
            flush()
            blocks.append({"t": "note", "text": s.strip("*").strip()})
            continue
        para.append(s)
    flush()
    return blocks


def _parse_score(line: str) -> dict:
    m_stamp = re.search(r"【([^】]+)】", line)
    stamp = m_stamp.group(1).strip() if m_stamp else ""
    if re.search(r"not\s*even\s*wrong", line, re.I):     # 底舱：连错的资格都没有
        return {"t": "score", "num": "0", "old": "", "tag": "NEW",
                "stamp": stamp or "Not even wrong —— 连错的资格都没有"}
    m_num = re.search(r"新鲜度[：:＊*\s]*\**\s*(\d+)\s*%", line)
    m_old = re.search(r"陈旧率\s*(\d+)\s*%", line)
    n = int(m_num.group(1)) if m_num else None
    m_tag = re.search(r"([烂鲜])\s*(?:【|\*\*)", line)   # 判定字后面不是盖章语就是收粗体
    if m_tag:
        tag = m_tag.group(1)
    elif n is not None:                                  # 否则按门槛：>=60 鲜，<60 烂
        tag = "鲜" if n >= 60 else "烂"
    else:
        tag = "烂" if "烂" in line else "鲜"
    return {"t": "score", "num": str(n) if n is not None else "—",
            "old": m_old.group(1) if m_old else "", "tag": tag, "stamp": stamp}


# ─────────────────────────── 卡片渲染 ───────────────────────────
class Card:
    def __init__(self, md: str, width: int = 780, scale: float = 3.0,
                 head_override: str | None = None, emoji_mode: str = "auto"):
        self.md = md
        self.s = float(scale)
        self.fb = FontBook(self.s, head_override, emoji_mode)
        self.dev_w = int(round(width * self.s))
        self.x0 = int(round(PAD_X * self.s))
        self.x1 = self.dev_w - int(round(PAD_X * self.s))
        self.cw = self.x1 - self.x0
        self.y = float(round(PAD_T * self.s))
        self.ops: list = []
        self.landmarks: list = []
        self.pending_margin = 0.0
        self.im: Image.Image | None = None
        self._party_map: dict[str, tuple[int, int, int]] = {}
        self.notes: list[str] = []

    # ---- 多方配色 ----
    def party_color(self, label: str) -> tuple[int, int, int]:
        """按出场顺序取 Cyber-Lab Dark 的深浅阶梯；超过阶梯长度就回卷。"""
        if label in self._party_map:
            return self._party_map[label]
        i = len(self._party_map)
        if i >= len(PARTY_COLORS):
            warn = (f"第 {i + 1} 方起色阶开始回卷（设计令牌只有 "
                    f"{len(PARTY_COLORS)} 档深浅），靠段首名字签区分")
            if warn not in self.notes:
                self.notes.append(warn)
        c = PARTY_COLORS[i % len(PARTY_COLORS)]
        self._party_map[label] = c
        return c

    # ---- 小工具 ----
    def px(self, v: float) -> float:
        return v * self.s

    def ls_width(self, text: str, font, ls: float) -> float:
        return sum(font.getlength(c) for c in text) + ls * len(text)

    def draw_ls(self, d: ImageDraw.ImageDraw, x: float, base: float, text: str,
                font, color, ls: float) -> float:
        cx = x
        for ch in text:
            d.text((cx, base), ch, font=font, fill=color, anchor="ls")
            cx += font.getlength(ch) + ls
        return cx - x

    def line_metrics(self, line, primary) -> tuple[int, int]:
        asc, desc = primary.getmetrics()
        for _t, f, _w, k in line:
            if k == "emoji" or f is None:
                continue
            a, b = f.getmetrics()
            asc, desc = max(asc, a), max(desc, b)
        return asc, desc

    def baseline_of(self, box_top: float, box_h: float, asc: int, desc: int) -> float:
        """CSS 半行距：文字在行盒里垂直居中。"""
        return box_top + (box_h - (asc + desc)) / 2.0 + asc

    @staticmethod
    def rect(d, xy, **kw):
        """矩形坐标取整 —— 3× 出图时边框/分隔线才不会糊。"""
        d.rectangle([round(v) for v in xy], **kw)

    def draw_line(self, d: ImageDraw.ImageDraw, x: float, base: float, line, color) -> float:
        cx = x
        for text, font, w, kind in line:
            if kind == "emoji":
                img = self.fb.emoji_image(text, int(round(w)))
                if img is not None:
                    self.im.paste(img, (int(round(cx)), int(round(base - img.height))), img)
                elif font is not None:
                    d.text((cx, base), text, font=font, fill=color, anchor="ls")
                cx += w
                continue
            off = self.px(1.0) if (kind == "b" and self.fb.bold_sim) else 0.0
            col = CODE_C if kind == "c" else color
            d.text((cx, base), text, font=font, fill=col, anchor="ls")
            if off:
                d.text((cx + off, base), text, font=font, fill=col, anchor="ls")
            cx += w
        return cx - x

    # ---- 断行 ----
    def tokenize(self, runs):
        toks = []
        for text, font, kind, size_dev in runs:
            i = 0
            while i < len(text):
                ch = text[i]
                if ch in (" ", "\t", "\u3000"):
                    toks.append((" ", font, font.getlength(" "), "sp"))
                    i += 1
                    continue
                if is_emoji(ch):
                    if ord(ch) in EMOJI_SKIP:
                        i += 1
                        continue
                    toks.append((ch, font, float(size_dev), "emoji"))
                    i += 1
                    continue
                if ch in WORDCH:
                    j = i
                    while j < len(text) and text[j] in WORDCH:
                        j += 1
                    tok = text[i:j]
                    toks.append((tok, font, font.getlength(tok), kind))
                    i = j
                    continue
                toks.append((ch, font, font.getlength(ch), kind))
                i += 1
        # 收尾标点粘到前一个字符（永不落在行首）
        glued = []
        for t in toks:
            if (glued and t[3] in ("t", "b", "c") and glued[-1][3] in ("t", "b", "c")
                    and t[0] in NO_START):
                p = glued[-1]
                merged = p[0] + t[0]
                glued[-1] = (merged, p[1], p[1].getlength(merged), p[3])
                continue
            glued.append(t)
        # 起头标点粘住下一个字符（不落在行尾）
        final = []
        for t in glued:
            if (final and t[3] in ("t", "b", "c", "emoji") and final[-1][3] in ("t", "b", "c")
                    and final[-1][0] and final[-1][0][-1] in NO_END):
                p = final[-1]
                merged = p[0] + t[0]
                final[-1] = (merged, p[1], p[1].getlength(merged), p[3])
                continue
            final.append(t)
        return final

    def wrap_runs(self, runs, maxw: float):
        toks = self.tokenize(runs)
        lines, cur, cw = [], [], 0.0
        pending_space = False
        for text, font, w, kind in toks:
            if kind == "sp":
                pending_space = bool(cur)
                continue
            sp_w = font.getlength(" ") if (pending_space and cur) else 0.0
            if cur and cw + sp_w + w > maxw:
                lines.append(cur)
                cur, cw = [], 0.0
                sp_w = 0.0
            if not cur and w > maxw:                    # 单个超长 token：按字符强拆
                buf, buf_w = "", 0.0
                for ch in text:
                    chw = font.getlength(ch) if font else w / max(1, len(text))
                    if buf and buf_w + chw > maxw:
                        lines.append([(buf, font, buf_w, kind)])
                        buf, buf_w = "", 0.0
                    buf += ch
                    buf_w += chw
                if buf:
                    cur, cw = [(buf, font, buf_w, kind)], buf_w
                pending_space = False
                continue
            if sp_w:                                    # 空格要真的排进去（占宽 + 画出来）
                cur.append((" ", font, sp_w, "sp"))
                cw += sp_w
            cur.append((text, font, w, kind))
            cw += w
            pending_space = False
        if cur:
            lines.append(cur)
        return lines or [[]]

    # ---- 块 ----
    def add_gap(self, mt: float):
        self.y += max(self.pending_margin, self.px(mt))
        self.pending_margin = 0.0
        return self.y

    def end_block(self, mb: float):
        self.pending_margin = self.px(mb)

    def blk_head(self, kicker: str, title: str):
        s = self.s
        fk = self.fb.font("head", KICKER_FS)
        ktext = kicker.upper()
        ls = self.px(KICKER_LS)
        bw = self.ls_width(ktext, fk, ls) + 2 * self.px(KICKER_PX)
        line_h = self.px(KICKER_FS * KICKER_LH)
        box_h = line_h + 2 * self.px(KICKER_PY)
        y0 = self.add_gap(0)
        x0 = self.x0
        self.ops.append(lambda d, x0=x0, y0=y0, bw=bw, box_h=box_h: self.rect(d, 
            [x0, y0, x0 + bw, y0 + box_h], fill=FG))
        asc, desc = fk.getmetrics()
        base = self.baseline_of(y0 + self.px(KICKER_PY), line_h, asc, desc)
        tx = x0 + self.px(KICKER_PX)
        self.ops.append(lambda d, tx=tx, base=base, ktext=ktext, fk=fk, ls=ls:
                        self.draw_ls(d, tx, base, ktext, fk, BG, ls))
        self.y = y0 + box_h
        self.landmarks.append(["kicker", round(y0), round(self.y)])
        self.end_block(KICKER_MB)

        # 主标题
        fh = self.fb.font("head", H1_FS)
        lines = self.wrap_runs([(title, fh, "t", self.px(H1_FS))], self.cw)
        line_h = self.px(H1_FS * H1_LH)
        y0 = self.add_gap(0)
        asc, desc = fh.getmetrics()
        for i, line in enumerate(lines):
            base = self.baseline_of(y0 + i * line_h, line_h, asc, desc)
            self.ops.append(lambda d, line=line, base=base: self.draw_line(d, self.x0, base, line, FG))
        self.y = y0 + line_h * len(lines)
        self.landmarks.append(["h1", round(y0), round(self.y)])

    def blk_h2(self, text: str):
        s = self.s
        self.add_gap(H2_MT)
        f = self.fb.font("head", H2_FS)
        pl = self.px(H2_PL)
        lines = self.wrap_runs([(text, f, "t", self.px(H2_FS))], self.cw - self.px(H2_BORDER) - pl)
        line_h = self.px(H2_FS * H2_LH)
        y0 = self.y
        h = line_h * len(lines)
        self.ops.append(lambda d, y0=y0, h=h: self.rect(d, 
            [self.x0, y0, self.x0 + self.px(H2_BORDER), y0 + h], fill=FG))
        asc, desc = f.getmetrics()
        for i, line in enumerate(lines):
            base = self.baseline_of(y0 + i * line_h, line_h, asc, desc)
            self.ops.append(lambda d, line=line, base=base, pl=pl:
                            self.draw_line(d, self.x0 + self.px(H2_BORDER) + pl, base, line, FG))
        self.y = y0 + h
        self.landmarks.append(["h2", round(y0), round(self.y)])
        self.end_block(H2_MB)

    def blk_p(self, text: str, marker: bool = True, party: str | None = None):
        s = self.s
        self.add_gap(P_MT)
        shade = self.party_color(party) if party else BODY_COLOR
        if party:
            self.party_chip(party, shade)      # 只有色条和小签带方色
        runs = self.inline_runs(text, BODY_FS)
        bar = self.px(MK_BORDER)
        pad = self.px(MK_PL)
        pl = (bar + pad) if marker else 0.0
        lines = self.wrap_runs(runs, self.cw - pl)
        line_h = self.px(BODY_FS * BODY_LH)
        y0 = self.y
        h = line_h * len(lines)
        if marker:
            self.ops.append(lambda d, y0=y0, h=h, bar=bar, shade=shade: self.rect(
                d, [self.x0, y0, self.x0 + bar, y0 + h], fill=shade))
        primary = self.fb.font("body", BODY_FS)
        asc, desc = self.line_metrics(lines[0], primary) if lines else primary.getmetrics()
        for i, line in enumerate(lines):
            base = self.baseline_of(y0 + i * line_h, line_h, asc, desc)
            self.ops.append(lambda d, line=line, base=base, pl=pl:
                            self.draw_line(d, self.x0 + pl, base, line, BODY_COLOR))
        self.y = y0 + h
        self.landmarks.append(["p", round(y0), round(self.y)])
        self.end_block(P_MB)

    def party_chip(self, label: str, color):
        """段首小签：一个色块 + 名字，用的就是这个人的方色。"""
        s = self.s
        f = self.fb.font("mono", PARTY_CHIP_FS)
        ls = self.px(PARTY_CHIP_LS * PARTY_CHIP_FS)
        line_h = self.px(PARTY_CHIP_FS * PARTY_CHIP_LH)
        y0 = self.y
        sq = self.px(PARTY_SQ)
        asc, desc = f.getmetrics()
        base = self.baseline_of(y0, line_h, asc, desc)
        sq_top = base - asc * 0.60
        self.ops.append(lambda d, sq_top=sq_top, sq=sq, color=color:
                        self.rect(d, [self.x0, sq_top, self.x0 + sq, sq_top + sq], fill=color))
        tx = self.x0 + sq + self.px(PARTY_SQ_GAP)
        self.ops.append(lambda d, tx=tx, base=base, label=label, f=f, ls=ls, color=color:
                        self.draw_ls(d, tx, base, label, f, color, ls))
        self.y = y0 + line_h + self.px(PARTY_CHIP_GAP)
        self.landmarks.append(["party", label, round(y0), round(self.y)])

    def blk_note(self, text: str):
        s = self.s
        y_line = self.add_gap(NOTE_MT)
        self.ops.append(lambda d, y_line=y_line: self.rect(d, 
            [self.x0, y_line, self.x1, y_line + self.px(NOTE_BORDER)], fill=FG))
        y0 = y_line + self.px(NOTE_BORDER) + self.px(NOTE_PT)
        f = self.fb.font("body", NOTE_FS)
        runs = self.inline_runs(text, NOTE_FS, body_color=FG3)
        lines = self.wrap_runs(runs, self.cw)
        line_h = self.px(NOTE_FS * NOTE_LH)
        asc, desc = f.getmetrics()
        for i, line in enumerate(lines):
            base = self.baseline_of(y0 + i * line_h, line_h, asc, desc)
            self.ops.append(lambda d, line=line, base=base:
                            self.draw_line(d, self.x0, base, line, FG3))
        self.y = y0 + line_h * len(lines)
        self.landmarks.append(["note", round(y0), round(self.y)])
        self.pending_margin = 0.0

    def blk_clarify(self, text: str):
        """「先说清楚」行：暗色细体引言，整体套「」，不占正文段、不带左条。"""
        s = self.s
        self.add_gap(NOTE_MT)
        f = self.fb.font("body", NOTE_FS)
        runs = self.inline_runs(f"「{text}」", NOTE_FS, body_color=FG3)
        lines = self.wrap_runs(runs, self.cw)
        line_h = self.px(NOTE_FS * NOTE_LH)
        y0 = self.y
        asc, desc = f.getmetrics()
        for i, line in enumerate(lines):
            base = self.baseline_of(y0 + i * line_h, line_h, asc, desc)
            self.ops.append(lambda d, line=line, base=base:
                            self.draw_line(d, self.x0, base, line, FG3))
        self.y = y0 + line_h * len(lines)
        self.landmarks.append(["clarify", round(y0), round(self.y)])

    def blk_tldr(self, text: str):
        s = self.s
        self.add_gap(TLDR_MT)
        border = self.px(TLDR_BORDER)
        top = self.y
        fk = self.fb.font("mono", TLDR_K_FS)
        kls = self.px(TLDR_K_LS)
        kline = self.px(TLDR_K_FS * TLDR_K_LH)
        fv = self.fb.font("body", TLDR_V_FS, bold=True)
        vlines = self.wrap_runs(self.inline_runs(text, TLDR_V_FS, bold_all=True),
                                self.cw - 2 * (border + self.px(TLDR_PX)))
        vline = self.px(TLDR_V_FS * TLDR_V_LH)
        box_h = 2 * border + 2 * self.px(TLDR_PY) + kline + self.px(TLDR_V_MT) + vline * len(vlines)
        self.ops.append(lambda d, top=top, box_h=box_h: self.rect(d, 
            [self.x0, top, self.x1, top + box_h], fill=FG, outline=FG, width=int(round(border))))
        cx = self.x0 + border + self.px(TLDR_PX)
        cy = top + border + self.px(TLDR_PY)
        kasc, kdesc = fk.getmetrics()
        kbase = self.baseline_of(cy, kline, kasc, kdesc)
        ktext = "\u26a1 省流"
        kimg = draw_bolt(int(round(self.px(TLDR_K_FS))), BG)
        xk = cx
        if kimg is not None:
            self.ops.append(lambda d, xk=xk, kbase=kbase, kimg=kimg:
                            self.im.paste(kimg, (int(round(xk)), int(round(kbase - kimg.height))), kimg))
            xk += kimg.width + fk.getlength(" ")
            ktext = "省流"
        self.ops.append(lambda d, xk=xk, kbase=kbase, ktext=ktext, fk=fk, kls=kls:
                        self.draw_ls(d, xk, kbase, ktext, fk, BG, kls))
        vy = cy + kline + self.px(TLDR_V_MT)
        vasc, vdesc = fv.getmetrics()
        for i, line in enumerate(vlines):
            base = self.baseline_of(vy + i * vline, vline, vasc, vdesc)
            self.ops.append(lambda d, line=line, base=base, cx=cx:
                            self.draw_line(d, cx, base, line, BG))
        self.y = top + box_h
        self.landmarks.append(["tldr", round(top), round(self.y)])
        self.pending_margin = 0.0

    def blk_hr(self):
        self.add_gap(HR_MY)
        y = self.y
        self.ops.append(lambda d, y=y: self.rect(d, 
            [self.x0, y, self.x1, y + self.px(HR_BORDER)], fill=FG))
        self.y = y + self.px(HR_BORDER)
        self.landmarks.append(["hr", round(y), round(self.y)])
        self.end_block(HR_MY)

    # ---- 分数块 ----
    def blk_score(self, num: str, old: str, tag: str, stamp: str = ""):
        s = self.s
        self.add_gap(SCORE_MT)
        border = self.px(SCORE_BORDER)
        padx, pady, gap = self.px(SCORE_PX), self.px(SCORE_PY), self.px(SCORE_GAP)
        top = self.y
        fnum = self.fb.font("head", NUM_FS)
        fpct = self.fb.font("head", PCT_FS)
        flab = self.fb.font("mono", LAB_FS)
        fbadge = self.fb.font("mono", BADGE_FS)
        emo_size = self.px(EMO_FS)

        num_w = fnum.getlength(num) + self.px(PCT_ML) + fpct.getlength("%")
        num_boxh = self.px(NUM_FS * NUM_LH)
        lab_txt = f"陈旧率 {old}%" if old else ""
        lab_ls = self.px(LAB_LS * LAB_FS)
        lab_w = self.ls_width(lab_txt, flab, lab_ls) if lab_txt else 0.0
        lab_lineh = self.px(LAB_FS * LAB_LH)
        lab_boxh = lab_lineh + self.px(LAB_PB)
        badge_ls = self.px(BADGE_LS * BADGE_FS)
        badge_w = self.ls_width(tag, fbadge, badge_ls) + 2 * self.px(BADGE_PX) + 2 * self.px(1)
        badge_lineh = self.px(BADGE_FS * BADGE_LH)
        badge_boxh = badge_lineh + 2 * self.px(BADGE_PY) + 2 * self.px(1)
        badge_mb = self.px(BADGE_MB)
        fstamp = self.fb.font("body", STAMP_FS, bold=True)
        stamp_txt = f"【{stamp}】" if stamp else ""
        stamp_ls = self.px(STAMP_LS * STAMP_FS)
        stamp_lineh = self.px(STAMP_FS * STAMP_LH)
        stamp_h = self.px(STAMP_GAP) + stamp_lineh if stamp_txt else 0
        content_h = max(emo_size, num_boxh, lab_boxh, badge_boxh + badge_mb)
        box_h = 2 * border + 2 * pady + content_h + stamp_h

        self.ops.append(lambda d, top=top, box_h=box_h: self.rect(d, 
            [self.x0, top, self.x1, top + box_h], outline=FG, width=int(round(border))))
        bottom = top + border + pady + content_h
        x = self.x0 + border + padx

        # emoji
        ch = EMO_CHAR.get(tag, EMO_CHAR["鲜"])
        self.ops.append(lambda d, x=x, bottom=bottom, ch=ch, emo_size=emo_size:
                        self.paste_emoji(ch, x, bottom - emo_size, emo_size))
        x += emo_size + gap

        # 大号数字
        ntop = bottom - num_boxh
        nasc, ndesc = fnum.getmetrics()
        nbase = self.baseline_of(ntop, num_boxh, nasc, ndesc)
        self.ops.append(lambda d, x=x, nbase=nbase, num=num, fnum=fnum:
                        d.text((x, nbase), num, font=fnum, fill=FG, anchor="ls"))
        pct_x = x + fnum.getlength(num) + self.px(PCT_ML)
        self.ops.append(lambda d, pct_x=pct_x, nbase=nbase, fpct=fpct:
                        d.text((pct_x, nbase), "%", font=fpct, fill=FG, anchor="ls"))
        x += num_w + gap

        # 陈旧率小字
        if lab_txt:
            ltop = bottom - lab_boxh
            lasc, ldesc = flab.getmetrics()
            lbase = self.baseline_of(ltop, lab_lineh, lasc, ldesc)
            self.ops.append(lambda d, x=x, lbase=lbase, lab_txt=lab_txt, flab=flab, lab_ls=lab_ls:
                            self.draw_ls(d, x, lbase, lab_txt, flab, FG3, lab_ls))
            x += lab_w + gap

        # 鲜/烂 徽标
        color = ROT if tag in ("烂", "NEW") else FRESH
        btop = bottom - badge_mb - badge_boxh
        self.ops.append(lambda d, x=x, btop=btop, badge_w=badge_w, badge_boxh=badge_boxh, color=color:
                        self.rect(d, [x, btop, x + badge_w, btop + badge_boxh],
                                    fill=BG, outline=color, width=max(1, int(round(self.px(1))))))
        basc, bdesc = fbadge.getmetrics()
        blineh = badge_lineh
        bbase = self.baseline_of(btop + self.px(1) + self.px(BADGE_PY), blineh, basc, bdesc)
        self.ops.append(lambda d, x=x, bbase=bbase, tag=tag, fbadge=fbadge, badge_ls=badge_ls, color=color:
                        self.draw_ls(d, x + self.px(1) + self.px(BADGE_PX), bbase, tag, fbadge, color, badge_ls))

        # 盖章语：分数行下方一行，加粗，品牌固定语
        if stamp_txt:
            sx = self.x0 + border + padx
            sasc, sdesc = fstamp.getmetrics()
            sbase = self.baseline_of(bottom + self.px(STAMP_GAP), stamp_lineh, sasc, sdesc)
            self.ops.append(lambda d, sx=sx, sbase=sbase, stamp_txt=stamp_txt, fstamp=fstamp, stamp_ls=stamp_ls:
                            self.draw_ls(d, sx, sbase, stamp_txt, fstamp, FG, stamp_ls))

        self.y = top + box_h
        self.landmarks.append(["score", round(top), round(self.y)])
        self.end_block(SCORE_MB)

    def paste_emoji(self, ch: str, x: float, top: float, size: float):
        img = self.fb.emoji_image(ch, int(round(size)))
        if img is None:
            f = self.fb.font("body", EMO_FS)
            d = ImageDraw.Draw(self.im)
            d.text((x, top + size), ch, font=f, fill=FG, anchor="ls")
            return
        self.im.paste(img, (int(round(x)), int(round(top))), img)

    # ---- 行内 markdown ----
    def inline_runs(self, text: str, fs: float, body_color=None, bold_all: bool = False):
        out = []
        pattern = re.compile(r"\*\*(.+?)\*\*|\*([^*]+)\*|`([^`]+)`", re.S)
        pos = 0

        def plain(t, kind="t"):
            if not t:
                return
            out.append((t, self.fb.font("body", fs, bold=(bold_all or kind == "b")),
                        "b" if (bold_all or kind == "b") else kind, self.px(fs)))

        for m in pattern.finditer(text):
            if m.start() > pos:
                plain(text[pos:m.start()])
            if m.group(1) is not None:
                plain(m.group(1), "b")
            elif m.group(2) is not None:
                plain(m.group(2))                      # 旧版 CSS: em{font-style:normal}
            else:
                code_fs = fs * 13 / 15.5
                out.append((m.group(3), self.fb.font("mono", code_fs), "c", self.px(fs)))
            pos = m.end()
        if pos < len(text):
            plain(text[pos:])
        return out or [(text, self.fb.font("body", fs), "t", self.px(fs))]

    # ---- 主流程 ----
    def render(self) -> Image.Image:
        blocks = parse_md(self.md)
        for b in blocks:
            t = b["t"]
            if t == "head":
                self.blk_head(b["kicker"], b["title"])
            elif t == "score":
                self.blk_score(b["num"], b["old"], b["tag"], b.get("stamp", ""))
            elif t == "p":
                self.blk_p(b["text"], party=b.get("party"))
            elif t == "note":
                self.blk_note(b["text"])
            elif t == "clarify":
                self.blk_clarify(b["text"])
            elif t == "tldr":
                self.blk_tldr(b["text"])
            elif t == "h2":
                self.blk_h2(b["text"])
            elif t == "hr":
                self.blk_hr()
        height = int(round(self.y + self.px(PAD_B)))
        self.im = Image.new("RGB", (self.dev_w, height), BG)
        d = ImageDraw.Draw(self.im)
        for op in self.ops:
            op(d)
        return self.im


# ─────────────────────────── 溢出/边界检查 ───────────────────────────
def content_bounds(im: Image.Image) -> tuple[int, int, int, int] | None:
    """返回非背景内容的 (x0, y0, x1, y1)；全黑返回 None。"""
    diff = ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, BG)).convert("L")
    diff = diff.point(lambda v: 255 if v > 12 else 0)
    return diff.getbbox()


# ─────────────────────────── CLI ───────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="把鉴定报告渲染成卡片图（纯 Pillow）")
    ap.add_argument("src", help="报告 .md 路径，或 - 表示从 stdin 读")
    ap.add_argument("--out", default=None)
    ap.add_argument("--width", type=int, default=780, help="逻辑宽（默认 780）")
    ap.add_argument("--scale", type=float, default=3.0, help="像素密度倍数（默认 3×）")
    ap.add_argument("--head-font", default=None, help="覆盖标题字体路径（A/B 对照用）")
    ap.add_argument("--emoji-mode", choices=["auto", "color", "draw"], default="auto")
    ap.add_argument("--dump-layout", action="store_true", help="把块级 y 区间以 JSON 打到 stderr")
    a = ap.parse_args()

    text = sys.stdin.read() if a.src == "-" else pathlib.Path(a.src).read_text(encoding="utf-8")
    out = pathlib.Path(a.out or (pathlib.Path(a.src).with_suffix(".png") if a.src != "-" else "out.png"))

    card = Card(text, width=a.width, scale=a.scale, head_override=a.head_font, emoji_mode=a.emoji_mode)
    im = card.render()
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "PNG", optimize=True)

    bbox = content_bounds(im)
    w, h = im.size
    if bbox:
        bx0, by0, bx1, by1 = bbox
        edge = f"内容边界 x[{bx0},{bx1}) y[{by0},{by1})  留白 L={bx0} T={by0} R={w - bx1} B={h - by1}"
    else:
        edge = "内容边界 空（全黑）"
    nbytes = out.stat().st_size
    print(f"✓ {out.resolve()}  {w}×{h} px（逻辑宽 {a.width}，{a.scale:g}× 像素，{nbytes} 字节）")
    print(f"  {edge}")
    print(f"  字体：标题={card.fb.head_path}  正文={card.fb.body_path}#{card.fb.body_idx}"
          f"  等宽={card.fb.mono_path}#{card.fb.mono_idx}  emoji={card.fb.emoji_path}"
          f"  加粗={card.fb.bold_mode}{'/' + str(card.fb.bold_name) if card.fb.bold_name else ''}")
    for n in card.fb.notes:
        print(f"  · {n}")
    for n in card.notes:
        print(f"  · {n}")
    if a.dump_layout:
        print(json.dumps({"width": w, "height": h, "landmarks": card.landmarks}, ensure_ascii=False),
              file=sys.stderr)


if __name__ == "__main__":
    main()
