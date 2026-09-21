# AGENTS.md — knowledge-cache 包

本文件约束 agent 在这个包里的行为。

## 这个包是什么

一个**单技能包**：把一段争论鉴定成"旧货"，并让说话的人认出自己在念现成台词。

- **机制层在本包**：`SKILL.md`（Hermes 读它）
- **实例数据不进包**：用户的争论内容、产出报告一律不落进本目录
- **单一事实源就是这个包**：`~/.hermes/skills/knowledge-cache` 是**软链**过来的。任何那里的同名 `SKILL.md` 实体拷贝都是 bug，发现即删。

## 改完必须自检

```bash
F=$(dirname "$(readlink -f ~/.hermes/skills/knowledge-cache/SKILL.md)")
# ① 不许残留会被照抄的具体例子（标签/口号/固定句式/比喻）
grep -nE "红丸|社会正义|1850|衣服是新的|anecdotal|bullets" "$F" && echo "FAIL: 有会被照搬的例子" || echo "OK: 无例子残留"
# ② 牌子必须齐全（中文标记）
# 牌子按当前契约（自然段版，无小标题）
for k in 旧货鉴定 新鲜度 真正吵的是 省流; do grep -q "$k" "$F" || echo "FAIL: 缺牌 $k"; done
grep -qE "自然段|不设小标题" "$F" || echo "FAIL: 输出契约没写明自然段"
grep -q "交付形态" "$F" || echo "FAIL: 缺「交付形态」节（出图）"
# 卡片工具必须能跑（有脚本、语法过；两个渲染器都要）
python3 -c "import ast,pathlib;ast.parse(pathlib.Path('scripts/report-card.py').read_text())" 2>/dev/null || echo "FAIL: scripts/report-card.py 语法错"
python3 -c "import ast,pathlib;ast.parse(pathlib.Path('scripts/card-pil.py').read_text())" 2>/dev/null || echo "FAIL: scripts/card-pil.py 语法错"
python3 scripts/card-pil.py --help >/dev/null 2>&1 || echo "FAIL: scripts/card-pil.py 跑不起来（需要 Pillow）"
# 色值不许自造：渲染器里出现的十六进制颜色必须都在 Cyber-Lab Dark 令牌集内（红/绿语义色除外）
grep -oE "0x[0-9A-Fa-f]{2}, 0x[0-9A-Fa-f]{2}, 0x[0-9A-Fa-f]{2}" scripts/card-pil.py | sort -u
# ③ 步骤数与契约必须一致（改过一条就要回头改另一条）
grep -n "five in order" "$F" || echo "WARN: 步骤措辞与契约可能不同步"
```

改契约必须同时补一遍上面的自检 —— 这个包的历史教训就是"改了输出契约、忘了改正文步骤"，两边打架。

## 内容层的三条硬规矩（改了就等于换掉这个技能）

1. **不举例子**：技能里不留任何现成标签、口号、句子、比喻。举例会让 LLM 整套照搬，写出千篇一律的报告。
2. **谱系优先近的、荒诞的**：要让他认出自己在跟风一个已经被笑过的东西。老学派只做兜底，且要点出它的滑稽处；**找不到就说不确定，绝不编**。
3. **不许退路词**：含糊的报告等于没写。判断可以错，不可以软。

## 边界

- 只做**过时性鉴定**，不做对错判决，不给行动建议（除非用户问下一步）
- 不猜用户支持哪一方；用户自己的观点与陌生人一视同仁
- 不因为受众可能是用户本人就软化结论

## 版本与发布

- 本地 git：`git -C /home/riff/skills/personal/knowledge-cache log --oneline`
- 远端（GitHub）**待接**：这台机器上没有 `gh`、没有全局 git 身份，远端地址与凭据需用户提供后再推

## 卡片渲染的两个坑（踩过，别重踩）

1. **`file://` 加载字体被 CORS 拦** —— @font-face 会**静默失败**，页面看起来正常但字体从未生效。解法：字体内嵌 base64（data URI）。
2. **CSS 变量名与 @font-face 名字必须一致** —— 对不上也是静默兜底。验收方法：**真字体 vs 强制兜底 A/B 对比墨迹**，两份一样就说明没生效（只看图会被骗）。
