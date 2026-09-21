# knowledge-cache · 老登观点鉴定器

给一段争论做**过时性鉴定**，不判对错。

对错没法量；能量的是另一件事：**每一方的说法有多旧**。输出给每一方一个精确到个位的「新鲜度」分数 —— 这是一个反着跑的烂番茄指数，越陈旧越烂 —— 并说清每一方的说辞在**哪一群人、哪一场运动**里出现过、后来怎么收场、那个死因跟他当下这句话什么关系。

目的不是说服人，是让人认出自己在念一份早就有人念过的台词。

## 它长什么样

一份报告 = 自然段 + 分数 + 一张卡片图。

```
# 老登观点鉴定器 · <这一条在争什么>

**新鲜度 12%（陈旧率 88%）烂【这观点烂爆了】**

**论断：** <第一句就拆穿 —— 属于哪一支、那支最丢人的死因翻成人话砸出来>

[自然段 · 按节拍分两到四段，粗体拎要害]
① 这句话站在什么地基上 → ② 这是哪一群人、哪场运动
→ ③ 那场运动怎么收场、为什么 → ④ 把那个死因对准他这句原话

**省流：** <一句能转述的话>
```

规则：

- **新鲜度 = 100% − 陈旧率**，精确到个位，不许写「约」（「约 90%」和「97%」在人心里的重量完全不同）。≥60 记「鲜」🍅，<60 记「烂」💀
- **分档盖固定章（品牌签名，一个字不改）**：0–29【登瘾又犯了是么】／【出租车司机级别的】；30–59【嘉豪觉得又自己行了】／【只有我】；60–89【至少不无聊】；90–100【这观点能处】。正文每次当场写，章永远一样 —— 卡片靠这几句被认出来
- **输入里根本没有观点的**（纯情绪、复读、人身攻击，或极端到不可证伪）：新鲜度 0%，盖【Not even wrong —— 连错的资格都没有】，一两句说明为什么连争论都不构成，然后停
- **每一方的分数写进那一方那段话里**，不另开打分表。只有一方就只有一个分数，不为对称去凑对立方
- **单条观点也合法**；不要硬撑篇幅

## 用法

贴一段争论、聊天记录、推文串，甚至一条孤立的观点，触发即可。

### 在 Hermes 里

```bash
git clone <仓库地址> ~/skills/knowledge-cache
ln -sfn ~/skills/knowledge-cache ~/.hermes/skills/knowledge-cache
```

（本仓库是**单一事实源**。`~/.hermes/skills/knowledge-cache/` 下出现同名 `SKILL.md` 实体文件 = 装错了，删掉。）

### 干净地派一个 agent 来跑（推荐）

鉴定结果的质量取决于**上下文有多干净**。如果让一个带着长期记忆、还知道你和谁在聊什么的 agent 来写，结论会被这些污染 —— 所以 `scripts/dispatch-verdict.sh` 每次都开一个**隔离 session**：

```bash
scripts/dispatch-verdict.sh --setup                    # 首次：建一个空的 verdict profile（无记忆）
scripts/dispatch-verdict.sh 材料.md                     # 出 report.md + report.png
scripts/dispatch-verdict.sh --text "要鉴定的话"
cat 材料.md | scripts/dispatch-verdict.sh -
scripts/dispatch-verdict.sh --probe                    # 隔离自检：让它自报上下文里有没有记忆
```

隔离靠四件事，缺一不可：

| | 做法 | 为什么 |
|---|---|---|
| 长期记忆 | 单独的 `verdict` profile（`memories/` 是空的） | **实测 `--ignore-rules` 和 `--ignore-user-config` 都挡不住记忆注入**，只有 profile 能 |
| 对话历史 | 不带 `--continue/--resume` | 每次全新 session |
| 环境规则 | 单独一个空工作目录 + `--ignore-rules` | 不读 CWD 的 `AGENTS.md`/`SOUL.md` |
| 能对外发消息 | profile 的 `.env` 只放推理 key | 子 session 拿不到平台 token，发不出去 |

默认模型 `deepseek/deepseek-v4.1-flash`、思考档 `max`，可用 `--model/--provider/--reasoning` 覆盖；产出目录里有 `material.md`（你的原话，原样不改）、`prompt.txt`（真正发出去的东西）、`report.md`、`report.png`、`meta.json`。跑一次大约 4~5 分钟。

### 只想要渲染器

`scripts/` 下的两个脚本都能把上面的 markdown 变成卡片图，可以单独拿去用：

```bash
# 推荐：纯 Python + Pillow，不启动浏览器、不联网
python3 scripts/card-pil.py 报告.md                 # → 报告.png
cat 报告.md | python3 scripts/card-pil.py - --out out.png

# 备选：无头浏览器版（同一套版式，需要 firefox；留作视觉对照）
python3 scripts/report-card.py 报告.md
```

依赖只有 **Pillow**（`pip install pillow`）。中文正文走系统字体（`fc-list` 找 `Noto Sans CJK SC`，找不到会明确报错，不会画出一堆豆腐块）。

**人多了怎么区分**：段落开头写 `[名字]` 或 `【名字】`，这一段就归他 —— 左侧色条换成他的深浅档，段首多一行「色块 + 名字」小签。这套设计是单色的，区分靠「深浅 + 文字签」，不引入色相。

```markdown
[老张] **「这就是新一轮互联网泡沫」—— 已被驳倒。** ……
[阿凯] **「不是泡沫，是基础设施」—— 对一半。** ……
```

## 设计要点

**不许在技能里举内容层的例子。** 不给任何现成的标签、口号、句子、比喻 —— 一给就会被整套照搬，每份报告长得一模一样，反而像它自己在念台词。方法可以抽象；名字和句子必须每次当场找。

**谱系优先挑近年的、网上现成且滑稽的那一支。** 要的是荒诞，不是庄重：一个已经被人笑过的东西，比一门体面的老学派难接得多 —— 报两百年前的正经学派，等于给对方发了一张"我在参与大事"的门票。老运动只能兜底，且要连它滑稽的地方一起点出来。**找不到就直说不确定，绝不编。**

**不许用退路词。**「可能」「某种程度上」「不排除」「可以理解为」一律不写。判断力优先于考据：两三个特征就该知道对方要放什么屁。允许错（读者会自己修），含糊才是没用的。

**不猜用户站哪一边。** 用户自己的观点与陌生人一视同仁。

## 目录

```
SKILL.md               技能本体（Hermes 读这个）
AGENTS.md              改这个包时的规矩
README.md              这份
docs/design.md         迭代记录：为什么这么改
scripts/card-pil.py    卡片渲染器（纯 Pillow）
scripts/report-card.py 卡片渲染器（无头浏览器版，对照用）
scripts/dispatch-verdict.sh  干净地派一个隔离 session 来跑（无记忆、无历史）
assets/fonts/          标题字体 + 正文字体 + 它们的授权
examples/              示例报告与成品图
```

## 字体授权

`assets/fonts/` 下的字体均为 **SIL Open Font License 1.1**，可自由再分发，许可全文见 [`assets/fonts/OFL.txt`](assets/fonts/OFL.txt)：

- 中文标题：[WD-XL Lubrifont SC](https://github.com/NightFurySL2001/WD-XL-font)、[ZCOOL QingKe HuangYou](https://github.com/googlefonts/zcool-qingke-huangyou)
- 中文正文：[Noto Sans CJK SC](https://github.com/notofonts/noto-cjk)（静态 Regular + Bold 一对，渲染器查找链的最优先项，随仓库走，机器上没装 Noto 也能出图）

渲染器找不到包内字体时会退到系统字体链（`fc-list` → 固定路径 glob），都没有才报错退出。emoji 钉死 **Apple Color Emoji**（macOS 自带，鲜/烂章靠它），Linux 上退 Noto Color Emoji。

## License

代码以 **MIT** 授权，见 [`LICENSE`](LICENSE)。`assets/fonts/` 下的字体不适用 MIT，见上一节。
