+++
title = "引导Claude Code构建Agentic PDF Reader：从/init到V0.1"
description = "记录如何通过引导 Claude Code，在一天内完成一个具备 AI 阅读助手功能的 PDF 朗读工具。重点不在于代码本身，而在于如何与 Claude Code 协作——什么时候该推进，什么时候该质疑，什么时候该纠正。"
date = 2026-03-22

[taxonomies]
categories = ["工具"]
tags = ["claude", "ai", "教程", "开发工具"]

[extra]
lang = "zh"
toc = true
+++

> 本文记录了如何通过引导 Claude Code，在一天内完成一个具备 AI 阅读助手功能的 PDF 朗读工具。重点不在于代码本身，而在于**如何与 Claude Code 协作**——什么时候该推进，什么时候该质疑，什么时候该纠正。

---

## 一、项目背景

**Agentic PDF Reader** 是一个命令行 PDF 朗读工具，核心特点是：

- 用 TTS 逐句朗读 PDF 内容
- 每读完一句，AI agent（Claude Haiku）自动判断：继续、降速、标记生词、或发起测验
- 生词根据真实词频库过滤，只收录超出用户词汇量的词
- 进度和词汇持久化到 SQLite

技术栈：Python 3.14 + pymupdf + pyttsx3 + tkinter + anthropic SDK + sqlite3 + wordfreq

---

## 二、第一阶段：初始化项目结构

### 2.1 用 /init 建立起点

在空目录里运行 `/init`，Claude 探索后发现没有代码可分析，直接说：

> "Once you add code, run /init again and I'll generate an accurate CLAUDE.md."

这时不要等 Claude 猜你要做什么，直接给出完整的约束。

### 2.2 一次性给出完整上下文

这是初始化最重要的一步——用一个结构化的 prompt 告诉 Claude 所有约束，而不是边走边说：

```
Before writing any code, do the following in order:

1. Rewrite CLAUDE.md with this content:
   - Stack: Python 3.14, pymupdf, pyttsx3, tkinter, anthropic SDK, sqlite3
   - Architecture: src/agent.py / pdf_parser.py / tts.py / vocab_store.py / gui.py
   - Never hardcode ANTHROPIC_API_KEY

2. Create docs/PLAN.md with 3 phases:
   - Phase 1 MVP: PDF load + TTS + sentence highlight (no API needed)
   - Phase 2 Agent: Claude agent decides pace/alerts/quiz
   - Phase 3 Memory: vocab SQLite + Anki export
   Each phase must list acceptance criteria and test cases.

3. Create the directory structure (empty files with docstrings only).
4. Show me PLAN.md and wait for my approval before writing any logic.
```

几个关键设计：
- **先写 CLAUDE.md**，让后续所有操作都在正确的上下文里进行
- **分阶段计划 + 验收标准**，每个阶段有明确的 test case
- **先创建骨架，不写逻辑**，避免一上来就陷入细节
- **等待审批**，在写真正的代码前给自己一个确认机会

### 2.3 审批计划，再动手

Claude 展示了 PLAN.md（包含三个阶段、18 个 test case 的完整表格），确认无误后说：

> "Good. Do it."

Claude 随即并行写完了所有模块，含完整实现和 26 个测试用例。

### 2.4 发现并纠正配置错误

代码生成后，立刻发现两个问题：

**问题一**：`pyproject.toml` 里 `requires-python = ">=3.11"`，明明指定了 3.14。

**问题二**：所有文件都有 `from __future__ import annotations`，这在 Python 3.14 里是多余的——PEP 649 已经让注解默认惰性求值，不再需要这个 backport。

直接指出：

> "我在 init 时说了 Python 用 3.14，你的配置文件里还是 3.11。而且 `from __future__ import annotations` 这个没用的吧？"

Claude 承认错误，同时修复了 `pyproject.toml` 的三处配置（`requires-python`、`target-version`、`python_version`），并删除了 9 个文件里的多余导入，还在 `CLAUDE.md` 里补充了说明。

**经验**：生成完代码后要扫一遍配置文件。Claude 很容易在版本号上用默认值，而不是你指定的值。

初始化完成后，项目骨架如下：

```
src/agent.py        LLM agent 决策循环
src/pdf_parser.py   PDF 解析，提取句子
src/tts.py          TTS 封装（pyttsx3 daemon 线程）
src/vocab_store.py  SQLite 词汇与进度
src/gui.py          tkinter 图形界面
tests/              26 个测试用例，覆盖三个阶段
```

---

## 三、第二阶段：手动测试，理解代码

新会话开始时，我告诉 Claude Code：**"我想自己手动测试来加深对代码的理解，该怎么开始"**。

Claude 给出了从底层到顶层的测试路径：
1. `VocabStore`（零依赖，最好验证）
2. `pdf_parser`（需要一个 PDF）
3. `ReadingAgent`（需要 API Key）
4. 完整 GUI

### 3.1 测试环境搭建

这里有个重要细节：**先建 venv**。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

安装过程中出现了大量 `pyobjc-*` 包，Claude 解释这是 `pyttsx3` 在 macOS 上调用原生语音引擎（`NSSpeechSynthesizer`）的必要桥接层，是正常现象。

### 3.2 `python -c` 的问题

最初 Claude 给出的测试代码用了 `python -c "..."` 的形式。我问：**"为什么不把测试代码放另一个文件夹"**。

Claude 承认放文件里更好，于是建了 `scratch/` 目录专门放探索性代码。

```
scratch/
  test_vocab.py
  test_parser.py
  test_agent.py
```

运行时遇到了模块找不到的问题：

```
ModuleNotFoundError: No module named 'src'
```

原因：`python scratch/test_vocab.py` 会把 `scratch/` 加入搜索路径，而不是项目根目录。修法：

```bash
PYTHONPATH=. python scratch/test_vocab.py
```

### 3.3 理解 VocabStore 设计

测试过程中，我问了一个设计问题：**"为什么需要同时一个 correct 字段和一个 incorrect 字段"**。

Claude 解释：两个字段独立记录才能算正确率和测验次数，缺一不可。这类问题虽然简单，但对理解数据模型很重要——不要跳过。

### 3.4 理解 Agent 决策机制

我逐一问了 `CONTEXT_WINDOW`、`_TOOLS`、`AgentAction`、`decide()` 的作用，得到了清晰的数据流说明：

```
PDF 句子
  → decide(current_sentence, context[-5:])
      → Claude API（带 _TOOLS）
      → AgentAction
  → CLI 根据 action.name 执行：
       ├── continue_reading → 播放下一句
       ├── slow_down        → 降低 TTS 速度
       ├── flag_vocab       → 调用 VocabStore.flag_word()
       └── quiz             → 弹出问题
```

---

## 四、第三阶段：从 GUI 改为 CLI

### 4.1 质疑 GUI 的必要性

我直接问：**"为什么还要用 GUI，现在大家都喜欢用 CLI"**。

Claude 解释了 GUI 在 TTS 场景下的合理性（播放控制、进度显示），但也承认如果不在意 TTS，CLI 更方便调试。

然后我说：**"不要用 GUI，用 CLI，终端控制"**。

这是一个关键的方向性决策。Claude 没有反驳，而是读完 `gui.py` 和 `tts.py` 后，重新写了 `src/cli.py`。

### 4.2 CLI 的架构设计

Claude 给出的 CLI 架构核心思路：

- **raw mode**：用 `tty.setraw()` 让终端逐字符响应，不需要回车
- **双线程**：主线程做 playback，后台线程读按键
- **Quiz 时还原终端**：切回普通模式输入答案，完成后再回 raw mode

控制键：`space` 暂停/恢复，`n` 跳句，`v` 查词汇，`q` 退出

---

## 五、第四阶段：TTS 问题排查

### 5.1 所有句子瞬间打印完毕

第一次运行时，152 句话一下子全部打印出来，没有声音。

Claude 分析原因：**pyttsx3 在 macOS 上必须在主线程运行**，但原来的 `TTSEngine` 把它放在 worker 线程，导致 `engine.runAndWait()` 立刻返回。

**修法**：放弃 `TTSEngine`，改用 macOS 自带的 `say` 命令：

```python
def _speak(self, text: str) -> None:
    self._proc = subprocess.Popen(["say", "-r", str(self._rate), text])
    self._proc.wait()
    self._proc = None
```

`subprocess.Popen` 的优势：阻塞、可中断（`terminate()`）、不依赖 pyttsx3 的线程问题。

### 5.2 `n` 键跳两句

按 `n` 时发现总是跳两句（44→46→48）。

原因：按 `n` 时 input 线程加了一次 `_current`，`_speak()` 返回后主线程又加了一次。

修法：引入 `_interrupted` 标志位：

```python
# input 线程按 n：
self._interrupted = True
self._current += 1
self._interrupt_speech()

# 主线程 speak 返回后：
if self._playing and not self._interrupted:
    self._current += 1
self._interrupted = False
```

这是一个典型的**多线程状态同步问题**，通过标志位而不是锁来解决，够用且简单。

---

## 六、第五阶段：词汇系统优化

### 6.1 Agent 的不可控性

测试中发现：同一句话反复运行，agent 有时返回 `flag_vocab`，有时返回 `continue_reading`，不稳定。

原因：LLM 有随机性（temperature 默认不为 0）。

**第一步修复**：将 temperature 设为 0：

```python
response = self._client.messages.create(
    model=MODEL,
    max_tokens=256,
    temperature=0,
    ...
)
```

### 6.2 词频阈值可配置

我提出：**"每个用户的词汇量不一样，我想把词频 > 多少这个条件做成可以配置"**。

Claude 在 `ReadingAgent.__init__` 加了 `vocab_threshold` 参数，CLI 加了 `--vocab-threshold` 选项：

```bash
python main.py book.pdf --vocab-threshold 3000
```

### 6.3 Claude 的主观判断不可靠

测试中发现：即使设了 `--vocab-threshold 2000`，像 `spectacles` 这样的词也没有进入词汇表。

原因：**system prompt 里要求 Claude 判断词是否在前 N 个常用词中，但 Claude 只是凭感觉，没有真实词频数据**。

我直接点出这个问题，Claude 建议引入 `wordfreq` 库——它基于真实语料库，有精确的词频数据。

```python
from wordfreq import top_n_list

# 初始化时建立常用词集合
self._common_words = set(top_n_list("en", vocab_threshold))

# 判断时直接查集合
if word not in self._common_words:
    return action  # 超出阈值，保留
```

### 6.4 一个重要的概念纠正

Claude 最初用 `1/freq` 来近似 rank，我指出：**"rank 和 freq 不是同一个事情，我们通常说的词汇量是四千、六千，哪有几十万的"**。

这是一个关键纠正。`word_frequency()` 返回的是 0~1 的概率值，`1/freq` 得到的数字在几万到几百万之间，和"词汇量 4000"完全不是一个概念。

正确做法是用 `top_n_list('en', N)` 直接取前 N 个词，这才对应"词汇量 N"的直觉。

**经验**：Claude 给出的方案要理解其含义，数字是否合理、概念是否对应，需要自己判断。

---

## 七、发布到 GitHub

### 7.1 发布前的检查清单

- `pyproject.toml` 补全新依赖（`wordfreq`）
- 创建 `.gitignore`（排除 `.venv/`、`*.pdf`、`vocab.db`、`scratch/`）
- 写双语 README

### 7.2 工具缺失时的处理

推送时发现 `gh` 没有安装，直接让 Claude 处理：

```bash
brew install gh
gh auth login
gh repo create agentic-pdf-reader --public --source=. --remote=origin --push
```

---

## 八、经验总结：如何引导 Claude Code

### 8.1 先理解，再修改

不要让 Claude 直接改代码。先让它解释模块的作用、数据流、设计决策，理解之后再决定是否修改，以及如何修改。

### 8.2 质疑设计决策

Claude 给出的方案不一定是最适合你场景的。本项目中的例子：
- 质疑 GUI 的必要性 → 换成 CLI
- 质疑词频判断的可靠性 → 引入 wordfreq

### 8.3 纠正概念错误要果断

Claude 有时会用近似手段绕过问题（如用 `1/freq` 近似 rank）。发现概念不对要直接指出，不要将就。

### 8.4 从底层模块开始测试

测试顺序：最独立的模块 → 有依赖的模块 → 完整系统。每一层测通了再往上走，问题容易定位。

### 8.5 Bug 要描述现象，不要猜原因

"n 键隔着跳"比"n 键有 bug"更有用。描述你观察到的现象，让 Claude 去分析原因。

### 8.6 工具链问题让 Claude 一起解决

venv、PYTHONPATH、缺少 `gh`——这些环境问题可以直接扔给 Claude 处理，不用自己查文档。

---

## 九、项目现状（v0.1）
项目地址: https://github.com/Hamiltonxx/agentic-pdf-reader.git , 来个star鞭笞我吧。

```bash
git clone https://github.com/Hamiltonxx/agentic-pdf-reader.git
cd agentic-pdf-reader
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key
python main.py your_book.pdf --vocab-threshold 4000
```

当前版本实现了核心功能闭环。后续可以考虑：
- 支持 Linux/Windows TTS
- 词汇复习模式（间隔重复）
- 多语言支持

---

*本文由作者与 Claude Code 协作整理。*
