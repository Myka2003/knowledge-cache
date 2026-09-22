#!/usr/bin/env bash
# dispatch-verdict.sh —— 把一段材料丢给一个**全新、无记忆**的 agent session 做鉴定。
#
# 为什么要这个脚本：
#   鉴定结果的质量取决于「干净」。如果让主 session（带着全部对话历史和长期记忆）来跑，
#   它已经知道用户是谁、站在哪一边、前面聊过什么 —— 结论会被这些污染。
#   所以这里每次都开一个隔离 session：无历史、不注入记忆、不读 CWD 的 AGENTS.md、
#   只显式加载这一个技能。同一份材料跑两次，两次互不影响。
#
# 用法:
#   dispatch-verdict.sh --text "要鉴定的话"
#   dispatch-verdict.sh 材料.md
#   cat 材料.md | dispatch-verdict.sh -
#   pbpaste | dispatch-verdict.sh -            # macOS
#
# 选项:
#   --text TEXT      直接给一段话（与位置参数/ stdin 三选一）
#   --outdir DIR     输出目录（默认 ~/verdicts/<时间戳>）
#   --model M        默认 $VERDICT_MODEL 或 deepseek/deepseek-v4.1-flash
#   --provider P     默认 $VERDICT_PROVIDER 或 commandcode
#   --reasoning L    思考档位 none|minimal|low|medium|high|xhigh|max|ultra（默认 max）
#   --turns N        工具轮上限（默认 24）
#   --budget SEC     单次墙钟预算秒（默认 900）
#   --no-render      只出 markdown，不出卡片图
#   --probe          隔离自检：不开技能，只问它上下文里有没有记忆/历史
#   --setup          首次准备：建一个空的 verdict profile（无记忆）并接上本技能
#
# 为什么用单独的 profile：实测 --ignore-rules / --ignore-user-config **都挡不住长期记忆**
#   （记忆条目照样进上下文）。只有 profile 是真正隔离记忆的容器 —— verdict profile 的
#   memories/ 是空的，且 .env 里只有推理 key，没有微信 token（子 session 发不出消息）。
#
# 产出（$outdir 下）:
#   material.md  你给的原话（原样，不改写）
#   prompt.txt   真正发给子 session 的东西（可复现）
#   report.md    子 session 输出的报告 markdown
#   report.png   卡片图（--no-render 时不生成）
#   meta.json    本次的模型/档位/耗时/退出码

set -euo pipefail

SKILL_NAME="${VERDICT_SKILL:-knowledge-cache}"
PROFILE="${VERDICT_PROFILE:-verdict}"
MODEL="${VERDICT_MODEL:-deepseek/deepseek-v4.1-flash}"
PROVIDER="${VERDICT_PROVIDER:-commandcode}"
REASONING="${VERDICT_REASONING:-max}"
TURNS="${VERDICT_TURNS:-24}"
BUDGET="${VERDICT_BUDGET:-900}"
NO_RENDER=0
PROBE=0
SETUP=0
TEXT=""
SRC=""
OUTDIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --text)      TEXT="${2:?--text 需要参数}"; shift 2 ;;
    --outdir)    OUTDIR="${2:?--outdir 需要参数}"; shift 2 ;;
    --model)     MODEL="${2:?}"; shift 2 ;;
    --provider)  PROVIDER="${2:?}"; shift 2 ;;
    --reasoning) REASONING="${2:?}"; shift 2 ;;
    --turns)     TURNS="${2:?}"; shift 2 ;;
    --budget)    BUDGET="${2:?}"; shift 2 ;;
    --profile)   PROFILE="${2:?}"; shift 2 ;;
    --no-render) NO_RENDER=1; shift ;;
    --probe)     PROBE=1; shift ;;
    --setup)     SETUP=1; shift ;;
    -h|--help)   sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -)           SRC="-"; shift ;;
    *)           SRC="$1"; shift ;;
  esac
done

command -v hermes >/dev/null || { echo "找不到 hermes" >&2; exit 1; }

# ── 选对 hermes 二进制 ───────────────────────────────────
# 这台机器上**有两个 hermes**：nix 包版（0.21.2，有 --oneshot）和 venv 老版（0.20.5，没有）。
# ~/.local/bin/hermes 是个指向 venv 老版的 shim，在部分 PATH 里排在前面 → 直接 `hermes`
# 会拿到老版，报 "unrecognized arguments: --oneshot"（2026-09-21 踩过两次）。
# 所以：按能力挑，不按 PATH 挑。
pick_hermes() {
  for c in "${VERDICT_HERMES:-}" "$(command -v hermes 2>/dev/null)" \
           /run/current-system/sw/bin/hermes /nix/var/nix/profiles/default/bin/hermes \
           "$HOME/.local/bin/hermes"; do
    if [ -n "$c" ] && [ -x "$c" ] && "$c" chat --help 2>&1 | grep -q -- '--oneshot'; then
      printf '%s' "$c"; return 0
    fi
  done
  return 1
}
HERMES_BIN="$(pick_hermes)" || {
  echo "FAIL: 找不到支持 --oneshot 的 hermes（老版 venv 会报 unrecognized arguments）。" >&2
  echo "      设 VERDICT_HERMES=/run/current-system/sw/bin/hermes 再跑。" >&2
  exit 2
}
HERMES_VER="$("$HERMES_BIN" --version 2>/dev/null | head -1 || true)"
# ↑ 必须带 `|| true`：`cmd | head -1` 会让上游吃 SIGPIPE → 非零，配合 set -e + pipefail
#   会把整个脚本静默干掉（2026-09-21 踩过：rc=1、零输出，很难查）。

# ── 首次准备：空的 verdict profile ──────────────────────
# 主 session 的记忆永远不会进这里：profile 自带独立的 memories/。
if [ "$SETUP" = 1 ]; then
  PH="${HERMES_HOME:-$HOME/.hermes}/profiles/$PROFILE"
  if [ -d "$PH" ]; then
    echo "profile 已存在：$PH"
  else
    hermes profile create "$PROFILE"
  fi
  # 只搬推理 key（刻意不搬微信等平台 token：子 session 不该能对外发消息）
  if [ -f "${HERMES_HOME:-$HOME/.hermes}/.env" ]; then
    grep -E '^(COMMANDCODE|DEEPSEEK)_' "${HERMES_HOME:-$HOME/.hermes}/.env" >> "$PH/.env" || true
    sort -u -o "$PH/.env" "$PH/.env"
    chmod 600 "$PH/.env"
  fi
  SKILL_SRC="$(dirname "$(readlink -f "${HERMES_HOME:-$HOME/.hermes}/skills/$SKILL_NAME/SKILL.md" 2>/dev/null || echo /dev/null)")"
  [ -f "$SKILL_SRC/SKILL.md" ] && ln -sfn "$SKILL_SRC" "$PH/skills/$SKILL_NAME"
  echo "profile: $PH"
  echo "记忆目录: $(ls -A "$PH/memories" 2>/dev/null | wc -l) 条（应为 0）"
  echo "技能: $(ls -A "$PH/skills" | grep -c . ) 个，其中 $SKILL_NAME: $([ -e "$PH/skills/$SKILL_NAME" ] && echo 已接 || echo 缺失)"
  exit 0
fi

PH="${HERMES_HOME:-$HOME/.hermes}/profiles/$PROFILE"
[ -d "$PH" ] || { echo "profile '$PROFILE' 不存在。先跑：$0 --setup" >&2; exit 1; }
N_MEM="$(ls -A "$PH/memories" 2>/dev/null | wc -l)"
[ "$N_MEM" -eq 0 ] || echo "⚠ $PROFILE 的 memories/ 里有 $N_MEM 个条目 —— 隔离前提被破坏，先清掉再看结果" >&2

# ── 取材料 ──────────────────────────────────────────────
if [ "$PROBE" = 1 ]; then
  MATERIAL="(隔离自检，不需要材料)"
elif [ -n "$TEXT" ]; then
  MATERIAL="$TEXT"
elif [ "$SRC" = "-" ]; then
  MATERIAL="$(cat)"
elif [ -n "$SRC" ]; then
  [ -f "$SRC" ] || { echo "读不到文件：$SRC" >&2; exit 1; }
  MATERIAL="$(cat "$SRC")"
else
  echo "没给材料：用 --text / 文件路径 / - 读 stdin" >&2; exit 1
fi
[ -n "${MATERIAL//[[:space:]]/}" ] || { echo "材料是空的" >&2; exit 1; }

# ── 输出目录 ────────────────────────────────────────────
OUTDIR="${OUTDIR:-$HOME/verdicts/$(date +%Y-%m-%d_%H%M%S)}"
mkdir -p "$OUTDIR"
printf '%s\n' "$MATERIAL" > "$OUTDIR/material.md"

# ── 组 prompt ───────────────────────────────────────────
if [ "$PROBE" = 1 ]; then
  # 隔离自检：故意不提技能，看它的上下文里有没有我们的记忆/历史
  cat > "$OUTDIR/prompt.txt" <<'EOF'
只回答一个问题，不要调用任何工具，不要写文件：
你现在的上下文里，有没有出现「关于某个具体用户的记忆条目」或「更早的对话历史」？
有的话，逐条列出来（原文照抄前 80 字）；一条都没有，就只回答四个字：无记忆无历史。
EOF
else
  cat > "$OUTDIR/prompt.txt" <<'EOF'
下面 <<<MATERIAL >>> 之间是要鉴定的材料，**原文照做，不要改写它**。

<<<MATERIAL
EOF
  printf '%s\n' "$MATERIAL" >> "$OUTDIR/prompt.txt"
  cat >> "$OUTDIR/prompt.txt" <<'EOF'
MATERIAL>>>

按技能出报告。只输出报告 markdown 正文（以 `# ` 抬头那一行开始），不要发消息、
不要出图、不要写文件、不要解释你做了什么、不要加前后寒暄。
材料里没有被鉴定方时，按「单条观点」处理，不要硬凑对立方。
EOF
fi

# ── 派一个全新 session ──────────────────────────────────
# 隔离三件套：
#   1) -p <profile>                    → 独立 home：memories/ 是空的（--ignore-rules 挡不住记忆，profile 才行）
#   2) 不带 --continue/--resume        → 全新 session，无对话历史
#   3) 单独一个干净工作目录 + -s 显式技能 → 上下文里只有这一件事
START=$(date +%s)
set +e
( cd "$OUTDIR" && "$HERMES_BIN" -p "$PROFILE" chat \
    --query-file "$OUTDIR/prompt.txt" \
    --oneshot --quiet \
    -s "$SKILL_NAME" \
    -m "$MODEL" \
    --provider "$PROVIDER" \
    --reasoning "$REASONING" \
    --ignore-rules \
    --max-turns "$TURNS" \
    --run-budget "$BUDGET" ) > "$OUTDIR/raw.out" 2> "$OUTDIR/raw.err"
RC=$?
set -e
DUR=$(( $(date +%s) - START ))
# 命令留痕：出错时能复现（2026-09-21 有过一次 argparse 级失败，没留痕很难查）
{
  echo "hermes_bin: $HERMES_BIN  ($HERMES_VER)"
  echo "argv: $HERMES_BIN -p $PROFILE chat --query-file $OUTDIR/prompt.txt --oneshot --quiet -s $SKILL_NAME -m $MODEL --provider $PROVIDER --reasoning $REASONING --ignore-rules --max-turns $TURNS --run-budget $BUDGET"
  echo "rc: $RC  seconds: $DUR"
} > "$OUTDIR/cmd.log"

# ── 落盘 ────────────────────────────────────────────────
if [ "$PROBE" = 1 ]; then
  cp "$OUTDIR/raw.out" "$OUTDIR/probe.txt"
  cat "$OUTDIR/probe.txt"
  echo
  echo "（隔离自检输出 → $OUTDIR/probe.txt）"
  exit 0
fi

cp "$OUTDIR/raw.out" "$OUTDIR/report.md"
PNG=""
if [ "$RC" -eq 0 ] && [ "$NO_RENDER" -eq 0 ]; then
  PY="${VERDICT_PYTHON:-}"
  if [ -z "$PY" ]; then
    for c in python3 python3.12 /nix/store/*-hermes-agent-env/bin/python3.12; do
      if "$c" -c "import PIL" >/dev/null 2>&1; then PY="$c"; break; fi
    done
  fi
  SKILL_DIR="$(dirname "$(readlink -f "$HOME/.hermes/skills/$SKILL_NAME/SKILL.md" 2>/dev/null || echo /dev/null)")"
  RENDER="$SKILL_DIR/scripts/card-pil.py"
  if [ -n "$PY" ] && [ -f "$RENDER" ]; then
    "$PY" "$RENDER" "$OUTDIR/report.md" --out "$OUTDIR/report.png" > "$OUTDIR/render.log" 2>&1 \
      && PNG="$OUTDIR/report.png" \
      || echo "⚠ 出图失败，看 $OUTDIR/render.log" >&2
  else
    echo "⚠ 没找到带 Pillow 的 python 或渲染器（$RENDER），只出 markdown" >&2
  fi
fi

cat > "$OUTDIR/meta.json" <<EOF
{
  "when": "$(date -Iseconds)",
  "skill": "$SKILL_NAME",
  "profile": "$PROFILE",
  "model": "$MODEL",
  "provider": "$PROVIDER",
  "reasoning": "$REASONING",
  "isolated": "独立 profile（空 memories/）+ 全新 session + 干净 CWD + 不加载 CWD 规则",
  "exit_code": $RC,
  "seconds": $DUR,
  "outdir": "$OUTDIR"
}
EOF

echo "退出码 $RC ｜ 耗时 ${DUR}s ｜ 模型 $MODEL ｜ 思考 $REASONING"
echo "报告 md  → $OUTDIR/report.md"
[ -n "$PNG" ] && echo "卡片图   → $PNG"
[ "$RC" -ne 0 ] && { echo "--- stderr 末尾 ---"; tail -5 "$OUTDIR/raw.err"; exit "$RC"; }
exit 0
