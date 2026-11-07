# 财报问答系统（finance-rag）

用中文或英文询问上市公司财报，系统给出带页码引用的答案；证据不足时拒答，不提供投资建议。目前支持本地运行。

**English summary.** A retrieval-augmented QA system over six 2025 annual reports (five companies, Chinese and English). Users ask in Chinese or English and get answers with PDF page citations; the system refuses when evidence is insufficient and never gives investment advice. Retrieval combines BM25, vector search, RRF fusion and a reranker. On a frozen 30-question evaluation set (24 answerable, 6 refusal), all 30 pass, but the questions are on the easy side and the sample is small. Most of the code was written by Claude and Codex; the author made the design decisions, spot-checked the evaluation questions and accepted the results.

## 目录

| 想了解 | 跳到 |
| --- | --- |
| 能做什么 | [能做什么](#能做什么) |
| 怎么设计的 | [架构](#架构)、[关键设计和理由](#关键设计和理由) |
| 效果如何 | [评测](#评测) |
| 有什么局限 | [局限和下一步](#局限和下一步) |
| 是谁做的 | [开发方式](#开发方式) |

## 能做什么

| 能力 | 说明 |
| --- | --- |
| 中英文提问 | 中文问英文财报也能检索（评测里有 4 道英文题、跨语言的 q17） |
| 带引用回答 | 每个事实标来源编号，网页里点引用跳到 PDF 对应页 |
| 证据不足拒答 | 资料里找不到时，回复“证据不足” |
| 不给投资建议 | 用规则在调用模型之前拦截 |

**资料范围：** 6 份 2025 年报，5 家公司，来源见 `data/manifest.json`。

| 公司 | 文档 | 语言 |
| --- | --- | --- |
| 贵州茅台 | 2025 年年度报告 | 中文 |
| 贵州茅台 | 2025 Annual Report | 英文 |
| 比亚迪 | 2025 年年度报告 | 中文 |
| 招商银行 | 2025 年度报告 | 中文 |
| 宁德时代 | 2025 年年度报告 | 中文 |
| Tesla | 2025 Form 10-K | 英文 |

## 架构

```mermaid
flowchart TD
    subgraph 离线：建索引
        D[scripts/download_reports.py<br/>下载 6 份财报 PDF] --> P[finrag/parsing.py<br/>解析：按坐标取词、识别表格]
        P --> C[finrag/chunking.py<br/>切分：表格带表头、记录页码和章节]
        C --> I[scripts/build_index.py<br/>生成向量并缓存]
    end
    subgraph 在线：回答问题
        W[web/index.html<br/>网页] -->|POST /api/ask| A[finrag/api.py<br/>接口，流式返回]
        A --> S[finrag/answer.py<br/>预检、组装、核对]
        S --> R[finrag/retrieval.py<br/>公司过滤、BM25 + 向量、RRF、重排]
        S --> L[finrag/llm.py<br/>调用聊天模型]
    end
    I -.索引文件.-> R
    E[eval/run_eval.py<br/>评测] --> S
```

| 层 | 文件 | 一句话职责 |
| --- | --- | --- |
| 数据 | `scripts/download_reports.py`、`data/manifest.json` | 记录并下载财报，校验下载到的是 PDF |
| 解析 | `finrag/parsing.py`、`finrag/text.py` | 把 PDF 变成带页码的段落和表格，统一简繁 |
| 切分 | `finrag/chunking.py` | 切成检索用的片段，表格每段都带表头 |
| 索引 | `scripts/build_index.py` | 生成向量，按内容哈希缓存，避免重复计费 |
| 检索 | `finrag/retrieval.py` | 公司过滤，BM25 和向量各取候选，RRF 合并，重排后取 8 段 |
| 问答 | `finrag/answer.py`、`finrag/llm.py` | 预检、组装提示词、流式调用模型、核对引用和数字 |
| 接口和网页 | `finrag/api.py`、`web/index.html` | 流式返回答案，引用可点击跳到 PDF 对应页 |
| 评测 | `eval/` | 冻结的 30 道题、校验脚本、评测脚本和报告 |

模型服务用阿里云百炼：`qwen3.8-flash` 聊天、`text-embedding-v4` 向量、`qwen3-rerank` 重排（走 OpenAI 兼容接口）。

## 关键设计和理由

| 设计 | 做了什么 | 为什么 |
| --- | --- | --- |
| 表格解析 | 不用 PyMuPDF 的 `table.extract()`，按单元格坐标取词（`parsing.py` 的 `_table_rows`）；没有横线的表格，检测到一个单元格里有两行以上数字时，改为按坐标逐行还原 | `table.extract()` 把 `168,838,102,514.79` 拆成了 `168 838 102 514 79 , , , .`；招商银行的表格没有横线，多行数字被合进一个单元格 |
| 切分规则 | 正文每段最多 900 字、相邻重叠 120 字，尽量停在句末；表格按行切，每段最多 1400 字且都重复表头，并带上表格上方 2 行说明；跨页表格沿用上一页表头；文字不跨页合并 | 财报关键数字在表格里，硬切会让数字和表头分家；“单位：元”常写在表格外面；不跨页是为了页码引用准确，代价是换页处的正文会被切断。900 和 120 是经验值，没有做过对比实验 |
| 混合检索 + 重排 | 公司过滤后，BM25 和向量各取 40 段，用 RRF（k=60）合并，再由重排模型留下 8 段 | 24 题对比里混合 + 重排最好（见下文）。财报里专有名词和数字多，适合关键词匹配；向量补足换说法和跨语言。重排每次多一次网络请求，延迟和费用没有单独统计 |
| 引用和数字核对 | 提示词要求每个事实标来源编号；没有有效引用的回答改判为拒答；答案里的数字在引用片段中找不到时返回警告（`answer.py` 的 `review`、`find_unverified_numbers`） | 把模型输出当作不可信输入，在模型外面加可以确定的检查。这一步只能确认数字出现在引用里，**查不出读错了列** |
| 投资建议规则预检 | 用正则匹配提问意图（如“是否应该买入”“我该买”），命中就直接拒答，不调用模型；也拦截晚于资料范围的年份 | 结果确定且省钱。规则不能只匹配“买入”，否则会误伤招商银行的科目“买入返售金融资产”（有测试覆盖） |
| 向量缓存 | 向量按片段内容哈希缓存，缓存键含模型名和维度 | 相同内容只计费一次；换模型后旧缓存不会被误用 |

## 评测

**怎么建的：**

1. 由不参与实现的 Agent（Codex）出 30 道题，出题时不看实现，以减少作者偏差。是否读过实现只能依据它自己的说明。
2. 作者对照 PDF 原页抽查了 6 道（q06、q07、q09、q23、q24、q30）后冻结。题目文件的 SHA-256 存在 `eval/questions.sha256`，内容一改 `eval/run_eval.py` 就拒绝运行。
3. 题目冻结后不为了分数改题。评分口径调整过一次：同一个数字常出现在多页，而题目只标了其中一页，所以引用的片段确实含有答案时也算引用正确。代价是这个口径偏松，因此同时报告严格口径的结果。
4. 30 题 = 24 道回答题 + 6 道拒答题（公司不在资料内 2、年份不在资料内 1、年报未披露 2、投资建议 1）。

### 检索对比（24 道回答题，2026-11-07）

| 方式 | 题数 | Hit@1 | Hit@3 | Hit@8 | MRR | 找齐全部页面 | 答案在前 8 条 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bm25 | 24 | 54% | 79% | 88% | 0.667 | 79% | 88% |
| vector | 24 | 46% | 71% | 79% | 0.583 | 75% | 83% |
| hybrid | 24 | 58% | 71% | 88% | 0.662 | 83% | 96% |
| hybrid+rerank | 24 | 58% | 88% | 96% | 0.741 | 96% | 100% |

- Hit@k、MRR 按标准页计算，偏严；“答案在前 8 条”看证据内容，偏松。两者要一起看。
- 24 题里 1 题约 4 个百分点，小差距不能当稳定结论。混合检索的 Hit@3 比 BM25 还低，说明合并也会把好结果挤下去（如 q21）。

### 答案评测（混合 + 重排，30 题）

| 项 | 结果 |
| --- | --- |
| 回答题 | 24 道全部判为正确 |
| 拒答题 | 6 道全部正确拒答（q28 由规则预检拦截，其余 5 道由模型回复“证据不足”） |
| 严格口径的引用命中 | 20/24（按标准页计算） |
| 费用 | 78,111 输入 Token、8,814 输出 Token，按标价估算约 0.086 元 |

严格口径下另有 4 道题（q01、q03、q09、q24）引用的不是标准页，是靠放宽后的规则（引用片段含答案）才算对。逐页核对后含义一致，例如茅台第 61 页是合并利润表的营业收入。

**满分要打折看：** 题目写明了单位和口径，部分措辞贴近原文，比真实用户的提问容易。30/30 只说明在这批题上没发现错误，不代表系统不会出错。完整数字见 [eval/report.md](eval/report.md)。

## 开发中的典型问题

| 问题 | 原因和处理 |
| --- | --- |
| 表格数字被拆散 | `table.extract()` 把数字拆成碎片，改为按坐标取词。修复前单元测试全过，因为用的是构造的干净数据，之后加了用真实页面的测试。PDF 里带千分位的数字去重后合计 15,970 个，切分结果里全部能原样找到；这只说明没被拆散，不说明和表头对应正确 |
| 只按标准页评分会冤枉正确结果 | q03 的答案出现在 5 页上，题目只标了 1 页。题目已冻结不能改，于是新增“答案在前 8 条”指标，并写明它偏松的代价 |
| 网页用的不是最好的检索方案 | 网页启动时用默认的混合检索（不加重排），测试替换了检索器所以没发现。改为混合 + 重排并加测试；日志改为记录脱敏后的异常信息 |
| 引用页码和页面印的页码对不上 | 引用用的是 PDF 物理页码，和页面上印的页码不一定相同（招商银行物理第 30 页印的是 29）。代码继续用物理页码，网页写成“PDF 第 N 页” |
| Git 换行转换会让冻结哈希失效 | `core.autocrlf` 会改变题目文件的字节，导致哈希对不上。题目文件本来就是 CRLF，所以把两个冻结文件标为 `-text`，按原样存取 |

## 局限和下一步

| 局限 | 说明 |
| --- | --- |
| 评测题偏容易 | 30 题全部通过，区分度不够；部分题措辞贴近原文并写明单位 |
| 样本小 | 检索对比只有 24 题；下一步计划扩到 100 题，加入换说法、不写单位、需区分口径的问题 |
| 数字核对只查“出现过” | 查不出读错了列（如把 2024 年的数字当成 2025 年） |
| 合并单元格 | 有合并单元格的表格，真正为空的单元格会让后面的列左移 |
| 资料外的公司 | 问资料里没有的公司时不做公司过滤，只靠模型拒答；评测里只有 2 道这类题 |
| 没做对比实验 | 没有对比过不同的切分大小、Embedding 模型和向量维度 |
| 重排的代价 | 延迟和 Token 费用没有单独统计 |
| 部署 | 提供了 Docker 配置；限流计数在进程内存里，重启清零 |

## 快速开始

环境：Windows、Python 3.12、[uv](https://docs.astral.sh/uv/)。

安装依赖：

```bash
uv sync
```

把 `.env.example` 复制为 `.env`，填入阿里云百炼的 API Key（以 `sk-` 开头）。生成向量和回答问题都要用到它。

下载财报并建立索引。PDF 和索引文件不在 Git 里，第一次运行要用脚本生成：

```bash
uv run python scripts/download_reports.py
uv run python scripts/build_chunks.py
uv run python scripts/build_index.py
```

最后一条默认只估算费用（6 份财报约 1 元）。确认后加 `--yes` 才会真正调用接口生成向量：

```bash
uv run python scripts/build_index.py --yes
```

启动网页：

```bash
uv run python -m finrag.api
```

打开 http://127.0.0.1:8000 。

运行测试（2026-11-07 共 132 个项目测试，全部通过；用到真实 PDF 的测试在缺文件时会跳过）：

```bash
uv run pytest
```

## 部署（Docker）

服务器上只运行问答服务，不解析 PDF、不生成向量：`data/raw/` 和 `data/index/` 在开发机生成后拷贝过去，以只读卷挂载进容器，不打进镜像。镜像里只有代码、网页和 `data/manifest.json`。

1. **准备 `.env`**：在服务器的项目目录里，把 `.env.example` 复制为 `.env` 并填入 API Key。`.env` 不会进镜像，由 `compose.yaml` 的 `env_file` 在运行时注入。
2. **拷贝数据**：把开发机上的 `data/raw/`（约 45MB）和 `data/index/` 拷到服务器项目目录下的同名位置。运行只需要 `data/index/chunks.jsonl` 和 `data/index/embeddings.npy`，其他文件可以不拷。容器以非 root 用户（uid 10001）运行，这些文件需要对其他用户可读（目录可进入）。
3. **构建并启动**：

   ```bash
   docker compose up -d --build
   ```

4. **查看状态和日志**：

   ```bash
   docker compose ps            # STATUS 显示 healthy 即健康检查通过
   docker compose logs -f finrag
   ```

   启动要加载索引，健康检查在启动后 60 秒内的失败不计数。缺密钥或索引时服务会带着中文提示退出，原因能在日志里看到。

5. **更新**：改了代码后重新执行 `docker compose up -d --build`；只更新数据则替换文件后执行 `docker compose restart`。

端口映射为 `8000:8000`，访问 `http://<服务器地址>:8000`。服务本身不带 HTTPS 和登录；对公网开放时建议放在带 TLS 的反向代理后面，并在防火墙上限制来源。

### 访问频率限制

`POST /api/ask` 每次都会调用付费的大模型接口，所以做了限流，超限返回 HTTP 429 和中文提示（`/health`、`/api/pdf` 不受限）。可在 `.env` 里调整，修改后执行 `docker compose up -d` 重建容器使其生效：

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `FINRAG_RATE_LIMIT_PER_IP` | 10 | 每个客户端 IP 在时间窗口内最多提问次数 |
| `FINRAG_RATE_LIMIT_WINDOW_SECONDS` | 60 | 上面那个时间窗口的长度（秒） |
| `FINRAG_DAILY_LIMIT` | 300 | 全站每 24 小时最多提问次数 |

注意：

- 计数保存在进程内存里，服务重启后清零；多进程或多副本时各自独立计数。
- 客户端 IP 取自 TCP 连接的对端地址，不信任 `X-Forwarded-For`（客户端可随意伪造）。如果前面加了反向代理，所有请求会显示为代理的地址，此时每 IP 限制等同于全站限制，每日上限仍然有效。
- 其他可配置项：`FINRAG_HOST`（监听地址，默认 `127.0.0.1`，compose 里设为 `0.0.0.0`）、`FINRAG_PORT`（监听端口，默认 8000；改它时需同步修改 `compose.yaml` 里的端口映射和健康检查）。取值不是正整数时服务拒绝启动。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `finrag/` | 核心代码：解析、切分、检索、问答、接口 |
| `scripts/` | 下载财报、生成切分结果、生成向量索引 |
| `data/` | `manifest.json` 财报清单；原始 PDF（`raw/`）和索引文件（`index/`）不进 Git，用脚本生成 |
| `eval/` | 冻结的评测题、校验和评测脚本、评测报告 |
| `web/` | 网页 |
| `tests/` | 单元测试和用真实财报页面的回归测试 |

## 开发方式

本项目在 AI 编程助手的协助下完成：Claude（Anthropic）编写了大部分代码并负责代码审查，Codex 编写了评测题和网页。作者负责需求和方案决策、抽查评测题和验收。编写评测题的 Agent 不参与实现，以减少评测偏差。
