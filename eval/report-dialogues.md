# 多轮对话评测报告

由 `eval/run_dialogues.py` 生成。样本量：20 组对话、45 轮，样本量小，只能看大方向。

回答轮同时要求改写包含关键词、答案和引用正确；判定是偏严的子串匹配，没通过的轮次需要人工复核。

按标价估算费用 0.1923 元。

## 按对话类型

| 对话类型 | 全部轮次通过的对话 / 对话数 | 通过轮次 / 总轮次 |
| --- | --- | --- |
| clarify | 2/2 | 4/4 |
| company_switch | 0/2 | 2/4 |
| compare | 1/2 | 3/4 |
| pronoun_followup | 7/9 | 21/23 |
| refuse_in_dialogue | 1/2 | 3/4 |
| topic_change | 0/1 | 1/2 |
| year_switch | 2/2 | 4/4 |

## 按轮次类别

| 类别 | 通过 / 轮次 |
| --- | --- |
| answer | 34/41 |
| clarify | 2/2 |
| refuse | 2/2 |

改写通过率（回答轮）：41/41

## 没有通过的轮次（7 轮）

- `d02` 第 2 轮 wrong_answer
  - 问题：And net profit?
  - 改写结果：What was Kweichow Moutai's net profit in 2025?
  - 回答前 200 字：The evidence reports Kweichow Moutai Sales Co., Ltd.'s net profit in 2025 as 4,722,835.76 RMB '0,000 [4].
- `d03` 第 1 轮 wrong_answer
  - 问题：What were Tesla's total revenues in 2025?
  - 改写结果：（未改写）
  - 回答前 200 字：Tesla's total revenues in 2025 were $94.83 billion [1].
- `d05` 第 2 轮 wrong_answer
  - 问题：那比亚迪呢？
  - 改写结果：比亚迪2025年末合并报表的资产总额是多少？
  - 回答前 200 字：比亚迪2025年末合并报表的资产总额为883,729,883千元 [1][8]。
- `d06` 第 2 轮 wrong_answer
  - 问题：What about Tesla?
  - 改写结果：What was Tesla's revenue in 2025?
  - 回答前 200 字：Tesla's total revenues in 2025 were $94.83 billion [1].
- `d09` 第 1 轮 wrong_answer
  - 问题：茅台2025年的营业收入是多少？
  - 改写结果：（未改写）
  - 回答前 200 字：贵州茅台2025年的营业收入为人民币16,883,810.25万元 [1]。
- `d13` 第 2 轮 wrong_answer
  - 问题：Separately, what were Tesla's total revenues in 2025?
  - 改写结果：（未改写）
  - 回答前 200 字：Tesla's total revenues in 2025 were $94.83 billion [1].
- `d14` 第 1 轮 wrong_answer
  - 问题：茅台2025年的营业收入是多少？
  - 改写结果：（未改写）
  - 回答前 200 字：贵州茅台2025年度营业收入为人民币16,883,810.25万元[1]。
