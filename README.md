# knowledge-cache · 老登观点鉴定器

给争论、单条观点或对言论的观察做**过时性鉴定**，不判对错。目的不是说服人，而是让人认出自己的说法已有谱系，并看清剩下的新意。

## 报告契约

规则以 [`SKILL.md`](SKILL.md) 为准，这里只概述：

- 常规报告依次为：标题 → 新鲜度与固定章 → 论断 → 固定边界声明 → 自然段 → 省流。正文无小标题、无清单、无打分表。
- 每条主张按五步展开：地基 → 谱系 → 内部反驳 → 话语作用 → 推到尽头。每方至少一段，篇幅随内容；单条主张一段即可，不凑对立方。新意只在确有时说明，不设新货栏。
- **新鲜度 = 100% − 陈旧率**，给精确到个位的整数；这是估计，不是正确率。≥60% 为「鲜」，低于 60% 为「烂」。抬头给整体分数；多方各在正文给一次分数，单方不重复。
- 固定章：0–29【登瘾又犯了是么】／【出租车司机级别的】；30–59【嘉豪觉得又自己行了】／【只有我】；60–89【至少不无聊】；90–100【这观点能处】。同档有两句时择一，不能改字。
- 没有可鉴定主张时：标题 → 带 `新鲜度 0%` 的【Not even wrong —— 连错的资格都没有】→ 一两句原因，然后停。0% 是卡片识别底档的占位，不是估分；不补普通报告各栏。
- 默认交付图片；用户明确要可复制内容时才交文字。材料和产物一律存包外。

## 使用

贴入材料并要求鉴定是否陈旧、重复或有新意，即可触发。对材料的概括本身承担主张时，鉴定概括，不误评其中的引文。

### 安装到 Hermes

```bash
git clone <仓库地址> ~/skills/knowledge-cache
ln -sfn ~/skills/knowledge-cache ~/.hermes/skills/knowledge-cache
```

技能安装目录应软链到包，不能另存一份 `SKILL.md`。检查软链后再修复安装，不要误删软链目标里的源文件。开发 worktree 只改本地文档，不自动切换安装软链。

### 隔离会话鉴定

`scripts/dispatch-verdict.sh` 每次开一个独立会话，避免已有用户记忆和聊天历史影响结论。以下相对脚本路径从包目录执行，材料路径和输出目录须在包外：

```bash
scripts/dispatch-verdict.sh --setup
scripts/dispatch-verdict.sh /包外目录/材料.md
scripts/dispatch-verdict.sh --text "<待鉴定材料>"
scripts/dispatch-verdict.sh - < /包外目录/材料.md
scripts/dispatch-verdict.sh --probe
```

隔离设置：

| 项目 | 做法 |
|---|---|
| 长期记忆 | 独立的 `verdict` profile，确认 `memories/` 为空；忽略规则或用户配置不能代替它 |
| 历史 | 不传续聊参数，每次全新会话 |
| 工作目录 | 使用包外、无规则文件的输出目录，并传 `--ignore-rules` |
| 发消息权限 | profile 只放推理密钥，不放平台令牌 |

`--setup` 不会清空已存在的 profile；复用前自行确认记忆和密钥配置。默认模型 `deepseek/deepseek-v4.1-flash`、provider `commandcode`、思考档 `max`，可用 `--model/--provider/--reasoning` 覆盖。

**子会话只交报告 Markdown，调度脚本负责落盘和渲染**；`--no-render` 跳过出图。默认输出到 `~/verdicts/<时间戳>/`，可用 `--outdir` 指定包外目录。文件包括 `material.md`、`prompt.txt`、`report.md`、`report.png`、`meta.json`，以及原始输出和运行日志。

注意：脚本按安装技能名加载 profile 中的技能，并从 `~/.hermes/skills/knowledge-cache` 解析渲染器；在 worktree 内运行脚本，**不等于自动加载这个 worktree 的新文档**。

### 单独渲染

默认版只需 Python 与 Pillow（`pip install pillow`），不启动浏览器、不联网：

```bash
python3 scripts/card-pil.py /包外目录/报告.md --out /包外目录/报告.png
python3 scripts/card-pil.py - --out /包外目录/报告.png < /包外目录/报告.md
```

默认逻辑宽 780px、3 倍像素。多方段首用 `[名字]` 或 `【名字】` 标归属，名字不超过 16 字；按单色深浅与名字签区分，超过四档时色阶回卷。各方分数写在句子里，**不要在该行连写「新鲜度」与数字百分号**，否则会被当成额外分数卡。

`scripts/report-card.py` 是旧浏览器对照版，额外需要 Firefox，可用同样的输入路径和 `--out` 参数。它与默认版的盖章、归属签、声明样式和色值尚未完全同步，不作为默认交付路径。

## 三条硬规矩

1. **技能不举内容层例子**：不预置可照抄的标签、口号、句子或比喻；格式、固定品牌标记与边界声明除外。
2. **谱系优先近的、荒诞的**：老运动只作兜底，且要指出滑稽处；找不到就说不确定，绝不编。
3. **不许退路词**：判断直接，不用含糊措辞软化结论；知识缺口明确说清。

用户自己的观点与陌生人一视同仁，不猜用户立场。不骂人、不臆测品格；除非另问下一步，否则不给行动建议。

## 目录

```text
SKILL.md                    技能本体与当前输出契约
AGENTS.md                   包维护规则与自检命令
README.md                   使用说明
docs/refactor-notes.md      本次重构说明与冲突处理
docs/design.md              历史迭代记录（不是当前契约）
scripts/card-pil.py         默认卡片渲染器（Pillow）
scripts/report-card.py      旧浏览器对照版
scripts/dispatch-verdict.sh 隔离会话调度器
assets/fonts/               字体与授权
examples/                   历史示例（不是模板，本次不改）
```

## 字体与授权

`assets/fonts/` 中字体均采用 **SIL Open Font License 1.1**，见 [`assets/fonts/OFL.txt`](assets/fonts/OFL.txt)：

- 中文标题：[WD-XL Lubrifont SC](https://github.com/NightFurySL2001/WD-XL-font)、[ZCOOL QingKe HuangYou](https://github.com/googlefonts/zcool-qingke-huangyou)。
- 中文正文：[Noto Sans CJK SC](https://github.com/notofonts/noto-cjk)，附 Regular 与 Bold；默认渲染器会在包内与系统候选中查找，没有可用中文字体时明确报错。
- 表情字体：macOS 使用 Apple Color Emoji，Linux 查找 Noto Color Emoji；无法使用彩色字体时画图形兜底。

代码采用 **MIT**，见 [`LICENSE`](LICENSE)；字体不适用 MIT。
