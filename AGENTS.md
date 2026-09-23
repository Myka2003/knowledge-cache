# AGENTS.md — knowledge-cache 包

本文件约束 agent 在这个包里的行为。

## 包与修改范围

这是单技能包：给主张做过时性鉴定，让说话的人认出重复的说法。

- **机制在包内**：`SKILL.md` 是当前行为与输出契约的唯一事实源，Hermes 读它；README 是使用说明，`docs/design.md` 与 `examples/` 是历史记录，不是模板。
- **实例数据不进包**：用户材料、报告、图片放包外。不修改已有用户产物。
- **安装使用软链**：`~/.hermes/skills/knowledge-cache` 应指向包，不能保留脱离源包的技能副本。先查清软链和目标，只有确认是多余副本且获准修复时才删除；不能删目标中的源文件。
- **worktree 只改当前目录**：自检检查当前 worktree，不追随安装软链去测原包；不修改原包、安装软链或用户 profile。
- **文档联动**：改契约须同步正文步骤、README 与下列自检；不复制第二套不同的正文顺序。
- **脚本边界**：`card-pil.py` 的渲染逻辑、`dispatch-verdict.sh` 的调用契约已可用；确需改动，先说明理由。文档重构不顺手改脚本。

## 内容层的三条硬规矩

1. **不举例子**：技能里不留内容层的现成标签、口号、句子、比喻。格式、固定品牌标记与边界声明除外。举例会让模型照搬成稿。
2. **谱系优先近的、荒诞的**：先找近年真实流行且已被嘲笑的说法；老运动只作兜底，且要指出滑稽处。**找不到就说不确定，绝不编。**
3. **不许退路词**：含糊等于没写。判断可以错，不可以软；明确说出知识缺口不算软化结论。

## 行为与交付边界

- 只做**过时性鉴定**，不做对错判决；除非用户另问下一步，否则不给行动建议。
- 不猜用户支持哪方；用户自己的观点与陌生人同一标准，不因受众是用户而软化结论。
- 常规报告用自然段，正文沿用判定流程的五步；牌子与固定声明保留。单方分数不重复，多方分数写入各自段落。
- 空主张用专用章和 0% 解析占位，一两句说明后停，不做常规估分。
- 默认发图；调度器子会话只返回 Markdown，由脚本落盘和出图。材料、产物始终在包外。

## 改完必须自检

在**待验收的包或 worktree 根目录**执行整段命令。不能用安装软链决定检查路径，否则会把原包当成改后的文件。

```bash
set -euo pipefail
F="$PWD"
S="$F/SKILL.md"
test -f "$S" && test -f "$F/scripts/card-pil.py"
echo "检查目录: $F"

# ① 历史污染词哨兵；只能拦已知残留，不能代替人工通读
if grep -nE "红丸|社会正义|1850|衣服是新的|anecdotal|bullets|笛卡尔|自由派|大国博弈|地缘" "$S"; then
  echo "FAIL: 有会被照搬的例子"; exit 1
fi
echo "OK: 无例子残留（历史黑名单）"

# ② 固定牌子、自然段与交付路径
for k in 老登观点鉴定器 新鲜度 陈旧率 论断 先说清楚 省流 'Not even wrong' '连错的资格都没有' 登瘾又犯了是么 出租车司机级别的 嘉豪觉得又自己行了 只有我 至少不无聊 这观点能处; do
  grep -Fq "$k" "$S" || { echo "FAIL: 缺牌 $k"; exit 1; }
done
grep -q '自然段，不设小标题' "$S"
grep -q '^## 交付形态' "$S"
grep -q 'scripts/dispatch-verdict.sh' "$S"
echo "OK: 牌子齐全 / 自然段 / 交付形态"

# ③ 两个渲染器语法、Pillow 入口、调度器语法；不运行真实鉴定任务
python3 - <<'PY'
import ast
from pathlib import Path
for name in ('report-card.py', 'card-pil.py'):
    ast.parse(Path('scripts', name).read_text())
print('OK: 两个渲染器语法')
PY
python3 scripts/card-pil.py --help >/dev/null
bash -n scripts/dispatch-verdict.sh
echo "OK: card-pil.py --help / dispatch-verdict.sh 语法"

# ④ 打印并校验色值；红绿语义色除外，其余须属于 Cyber-Lab Dark
python3 - <<'PY'
import re
from pathlib import Path
tokens = {'000000', 'ededed', 'a1a1a1', '6e6e6e', '242424', '3d3d3d', '8f8f8f'}
semantic = {'ff0000', '008000'}
source = Path('scripts/card-pil.py').read_text()
triples = re.findall(r'0x([0-9A-Fa-f]{2}), 0x([0-9A-Fa-f]{2}), 0x([0-9A-Fa-f]{2})', source)
colors = {''.join(t).lower() for t in triples}
assert colors, '未提取到颜色'
assert colors <= tokens | semantic, f'未知色值: {colors - tokens - semantic}'
print('色值: ' + ' '.join('#' + c for c in sorted(colors)))
print('OK: Cyber-Lab Dark 令牌 / 红绿语义色')
PY

# ⑤ 五步只有一个定义；输出契约引用它，不再另列四步
python3 - <<'PY'
import re
from pathlib import Path
s = Path('SKILL.md').read_text()
flow = s.split('## 判定流程\n', 1)[1].split('\n## ', 1)[0]
assert re.findall(r'^\d\. \*\*(.+?)\*\*', flow, re.M) == [
    '地基', '谱系', '内部反驳', '话语作用', '推到尽头']
contract = s.split('## 输出契约\n', 1)[1].split('\n## ', 1)[0]
assert '正文按「判定流程」的五步顺序写' in contract
for stale in ('five in order', '各方新鲜度 block', 'Actually New', 'Cache Score', 'Output Contract'):
    assert stale not in s, f'旧契约残留: {stale}'
assert not re.search(r'^#{1,3} .*?[A-Za-z]', s, re.M), '标题语言未统一'
print('OK: 五步与输出契约同源 / 无旧契约残留 / 中文标题')
PY
```

另须人工确认：无内容层例子；近且荒诞的真实谱系优先；正文无退路词；声明、空主张分支、盖章档位和脚本解析约定不冲突。`--help` 只验证入口；需要验证出图时，用包外临时占位材料，不能拿用户产物做测试或在包内生成报告。

## 版本与发布

- 用当前 worktree 的 `git status --short`、`git log --oneline`、`git remote -v` 核对状态，不硬编码原包路径或远端可用性。
- **不自动 commit、push 或 merge**；只有用户明确授权才执行。

## 字体渲染的两个坑

1. **`file://` 字体会被 CORS 拦**：`@font-face` 可静默失败；应内嵌 base64 数据。
2. **CSS 变量与 `@font-face` 字体名必须一致**：对不上会静默兜底。验收用真字体与强制兜底做墨迹对比，两份一样说明没生效，不能只看图猜。
