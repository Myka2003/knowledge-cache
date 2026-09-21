#!/usr/bin/env python3
"""把鉴定报告转成一张图（md 在各处显示不完美，图到哪儿都一样）。

用法:
    report-card.py <报告.md> [--out 输出.png] [--width 780] [--scale 3] [--tall 2400]
    cat 报告.md | report-card.py - --out out.png

特性：
  ① 结构化排版：分数块（大号数字 + 鲜/烂 徽标）、每段带标志符、省流独立框
  ② 高分辨率：Same 逻辑宽，按 --scale 倍像素出图（默认 3×，手机上不糊）
  ③ 两趟渲染：先量内容高度，再按实际高度高清出图 → 不留白、不浪费画布
  ④ 不依赖 emoji 字体：标志符用 CSS 画的色点/色条，任何机器都渲染得出来
"""
from __future__ import annotations

import argparse
import base64
import html
import os
import pathlib
import re
import subprocess
import sys
import tempfile

PKG = pathlib.Path(__file__).resolve().parent.parent
ENV_FONT_DIRS = [pathlib.Path(p) for p in os.environ.get("CARD_FONT_DIRS", "").split(":") if p]

FONT_FILES = {
    # 优先包内（随包走，扔给任何 agent 都能用）；退回用户字体目录
    "CardHead": next((p for p in [
        PKG / "assets/fonts/WDXLLubrifontSC-Regular.ttf",
        pathlib.Path.home() / ".local/share/fonts/WDXLLubrifontSC-Regular.ttf",
    ] if p.exists()), pathlib.Path("/nonexistent")),
    "CardHeadAlt": next((p for p in [
        PKG / "assets/fonts/ZCOOLQingKeHuangYou-Regular.ttf",
    ] if p.exists()), pathlib.Path("/nonexistent")),
}

FONT_DIRS = ENV_FONT_DIRS + [
    PKG / "assets/fonts",
    pathlib.Path.home() / ".local/share/fonts",
]
SANS_NAMES = ("Geist-Variable.woff2",)
MONO_NAMES = ("GeistMono-Variable.woff2",)

CSS = """
:root{--head:"CardHead","Archivo Black","Noto Sans CJK SC",sans-serif;
--sans:Geist,"Noto Sans CJK SC","PingFang SC","Noto Color Emoji",sans-serif;
--mono:"Space Mono",ui-monospace,"Noto Sans Mono",monospace;
--bg:#000000;--panel:#FFFFFF;--fg:#FFFFFF;--fg2:#A9A9B6;--fg3:#9A9A9A;
--hair:#FFFFFF;--accent:#FFFFFF;--rot:#FF0000;--fresh:#008000;--link:#0000FF}
*{box-sizing:border-box;margin:0;padding:0}
body{width:{W}px;background:var(--bg);color:var(--fg);font-family:var(--sans);
font-size:15.5px;line-height:1.76;letter-spacing:.004em;-webkit-font-smoothing:antialiased;
padding:40px 44px 34px}
.emo{font-size:44px;line-height:1;margin-bottom:6px;font-family:"Noto Color Emoji","Noto Emoji",var(--sans)}
.kicker{display:inline-block;background:#FFFFFF;color:#000000;padding:5px 11px;
font-family:var(--head);font-size:12px;letter-spacing:2px;text-transform:uppercase;
margin-bottom:16px}
.kicker i{display:none}
h1{font-family:var(--head);font-size:34px;font-weight:400;letter-spacing:-.01em;line-height:1.08}
.score{display:flex;align-items:flex-end;gap:16px;margin:20px 0 10px;padding:16px 18px;
border:5px solid #FFFFFF}
.num{font-family:var(--head);font-size:60px;font-weight:600;line-height:.86;letter-spacing:-.04em}
.num small{font-size:24px;font-weight:500;margin-left:2px}
.score .lab{font-family:var(--mono);font-size:11px;color:var(--fg3);letter-spacing:.16em;
text-transform:uppercase;padding-bottom:7px}
.badge{font-family:var(--mono);font-size:12px;letter-spacing:.16em;padding:4px 10px;margin-bottom:6px;border:1px solid}
.badge{font-weight:700;text-transform:uppercase}
.badge.rot{color:#FF0000;border-color:#FF0000;background:#000000}
.badge.fresh{color:#008000;border-color:#008000;background:#000000}
p{margin:15px 0;color:var(--fg2);position:relative}
p.mk{border-left:3px solid #FFFFFF;padding-left:16px}
p b,p strong{color:#fff;font-weight:600}
.note{margin-top:22px;padding-top:14px;border-top:3px solid #FFFFFF;font-size:13.5px;
color:#9A9A9A;line-height:1.7}
.tldr{margin-top:26px;padding:16px 18px;background:#FFFFFF;border:5px solid #FFFFFF}
.tldr .k{font-family:var(--mono);font-size:12px;letter-spacing:2px;color:#000000;text-transform:uppercase}
.tldr .v{margin-top:8px;font-size:16.5px;color:#000000;font-weight:600;line-height:1.6}
h2{font-family:var(--head);font-size:24px;font-weight:400;color:#fff;margin:24px 0 10px;
padding-left:14px;border-left:5px solid #FFFFFF}
hr{border:0;border-top:3px solid #FFFFFF;margin:22px 0}
code{font-family:var(--mono);font-size:13px;color:#c9b6ff}
em{font-style:normal}
"""


def esc(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def font_uri(names, dirs) -> str:
    for d in dirs:
        for n in names:
            p = d / n
            if p.exists():
                return p.as_uri()
    return ""


def render_body(md: str) -> str:
    out: list[str] = []
    para: list[str] = []
    pending_kicker = ""

    def flush():
        if para:
            out.append('<p class="mk">' + esc(" ".join(para)) + "</p>")
            para.clear()

    for raw in md.split("\n"):
        s = raw.strip()
        if not s:
            flush()
            continue
        if s in ("---", "***", "___"):
            flush()
            out.append("<hr>")
            continue

        if s.startswith("# "):
            flush()
            title = s[2:].strip()
            if "·" in title:
                k, t = title.split("·", 1)
                pending_kicker = k.strip()
                title = t.strip()
            out.append((f'<div class="kicker"><i></i>{esc(pending_kicker or "旧货鉴定")}</div>'
                        if pending_kicker or True else "") + f"<h1>{esc(title)}</h1>")
            continue

        if s.startswith("## "):
            flush()
            out.append(f"<h2>{esc(s[3:])}</h2>")
            continue

        # 分数行
        if re.search(r"新鲜度", s) and re.search(r"\d+\s*%", s):
            flush()
            num = re.search(r"新鲜度[：:＊*\s]*\**\s*(\d+)\s*%", s)
            old = re.search(r"陈旧率\s*(\d+)\s*%", s)
            n = num.group(1) if num else "—"
            tag = "烂" if ("烂" in s and "鲜" not in s.split("烂")[0][-2:]) else "鲜"
            cls = "rot" if tag == "烂" else "fresh"
            emo = "💀" if tag == "烂" else "🍅"
            old_txt = f'陈旧率 {old.group(1)}%' if old else ""
            out.append(
                f'<div class="score"><div class="emo">{emo}</div>'
                f'<div class="num">{n}<small>%</small></div>'
                f'<div class="lab">{esc(old_txt)}</div>'
                f'<div class="badge {cls}">{tag}</div></div>')
            continue

        # 省流行
        if s.startswith("**省流") or s.startswith("省流"):
            flush()
            body = re.sub(r"^\**\s*省流[：:]\s*", "", s).strip().strip("*").strip()
            out.append(f'<div class="tldr"><div class="k">⚡ 省流</div>'
                       f'<div class="v">{esc(body)}</div></div>')
            continue

        # 杂音/未入表（整行斜体）
        if s.startswith("*") and s.endswith("*") and not s.startswith("**"):
            flush()
            out.append(f'<div class="note">{esc(s.strip("*").strip())}</div>')
            continue

        para.append(s)
    flush()
    return "\n".join(out)


def build_html(md: str, width: int, scale: float = 1.0) -> str:
    """width 是逻辑宽；scale 是像素密度倍数（把所有 px 尺寸整体放大，等价于高清渲染）。"""
    def bump(m: re.Match) -> str:
        return f"{float(m.group(1)) * scale:g}px"

    raw_css = CSS.replace("{W}", str(int(width)))   # 逻辑宽；随后由 bump 统一放大
    raw_css = re.sub(r"(\d+(?:\.\d+)?)px", bump, raw_css)
    css = raw_css
    faces = ""
    for fam, path in FONT_FILES.items():
        if path.exists():
            b64 = base64.b64encode(path.read_bytes()).decode()
            faces += (f"@font-face{{font-family:{fam};"
                      f"src:url(data:font/ttf;base64,{b64}) format('truetype');"
                      "font-weight:100 900;font-display:block}")
    if font_uri(SANS_NAMES, FONT_DIRS):
        faces += (f"@font-face{{font-family:Geist;src:url('{font_uri(SANS_NAMES, FONT_DIRS)}')"
                  " format('woff2-variations');font-weight:100 900;font-display:block}")
    if font_uri(MONO_NAMES, FONT_DIRS):
        faces += (f"@font-face{{font-family:GeistMono;src:url('{font_uri(MONO_NAMES, FONT_DIRS)}')"
                  " format('woff2-variations');font-weight:100 900;font-display:block}")
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            f"<style>{faces}{css}</style></head><body>{render_body(md)}</body></html>")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default=None)
    ap.add_argument("--width", type=int, default=780)
    ap.add_argument("--scale", type=float, default=3.0, help="像素密度倍数（默认 3×）")
    ap.add_argument("--tall", type=int, default=2400, help="初始画布高度（CSS px）")
    a = ap.parse_args()

    text = sys.stdin.read() if a.src == "-" else pathlib.Path(a.src).read_text(encoding="utf-8")
    out = pathlib.Path(a.out or pathlib.Path(a.src).with_suffix(".png"))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="oml-card-"))

    def shoot(scale: float, tall_css: int, dest: pathlib.Path) -> None:
        """逻辑宽 a.width，按 scale 整体放大后截图（窗口尺寸也用放大后的像素）。"""
        page = tmp / f"card-{scale:g}.html"
        page.write_text(build_html(text, a.width, scale), encoding="utf-8")
        r = subprocess.run(["firefox", "--headless",
                            f"--window-size={int(a.width * scale)},{int(tall_css * scale)}",
                            "--screenshot", str(dest), page.as_uri()],
                           capture_output=True, text=True, timeout=300)
        if not dest.exists():
            sys.exit(f"截图失败 scale={scale}：{r.stderr[-300:]}")

    def bottom(png: pathlib.Path) -> tuple[int, int]:
        from PIL import Image
        im = Image.open(png).convert("RGB")
        w, h = im.size
        bg = im.getpixel((4, 4))
        for y in range(h - 1, -1, -1):
            if any(sum(abs(c - d) for c, d in zip(im.getpixel((x, y)), bg)) > 12
                   for x in range(0, w, 7)):
                return y, w
        return 0, w

    probe = tmp / "probe.png"
    shoot(1, a.tall, probe)
    y, _ = bottom(probe)
    h_css = y + 36
    if h_css >= a.tall - 4:
        h_css = a.tall + 2400
        shoot(1, h_css, probe)
        h_css = bottom(probe)[0] + 36

    final = tmp / "final.png"
    shoot(a.scale, h_css, final)
    try:
        from PIL import Image
    except ImportError:
        final.replace(out)
        print(f"⚠ 无 PIL，未裁剪；已按 {a.scale}× 出图 → {out}")
        return
    im = Image.open(final).convert("RGB")
    w, h = im.size
    keep = min(h, bottom(final)[0] + int(34 * a.scale))
    im.crop((0, 0, w, keep)).save(out)
    print(f"✓ {out}  {w}×{keep} px（逻辑宽 {a.width}，{a.scale:g}× 像素）")


if __name__ == "__main__":
    main()
