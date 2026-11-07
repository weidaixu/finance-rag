# 评测报告

由 `eval/run_eval.py` 生成，数字来自真实运行。样本量小，只能看大方向。

答案判定是偏严的子串匹配：换了说法的正确答案也会被判错，`manual_review` 的题要人工判断，所以没通过的题都要人工复核。

## 检索

Hit@k 和 MRR 按标准页计算。同一数字可能出现在多页，而题目只标了部分页面，所以它们偏严；「答案在前 8 条」看的是证据内容，较短的答案可能偶然命中，所以偏松。两者要一起看。

| 方式 | 题数 | Hit@1 | Hit@3 | Hit@8 | MRR | 找齐全部页面 | 答案在前 8 条 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bm25 | 24 | 54% | 79% | 88% | 0.667 | 79% | 88% |
| vector | 24 | 46% | 71% | 79% | 0.583 | 75% | 83% |
| hybrid | 24 | 58% | 71% | 88% | 0.662 | 83% | 96% |
| hybrid+rerank | 24 | 58% | 88% | 96% | 0.741 | 96% | 100% |

### bm25 没有命中标准页或答案不全的题（4 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p12', 'moutai-2025-zh p10', 'moutai-2025-zh p20']
- `q03` table_number：宁德时代2025年营业收入是多少千元？请按年报原单位回答。；标准页 ['catl-2025-zh p11']，名次 None，答案在前 8 条 True，实际前 3 条 ['catl-2025-zh p30', 'catl-2025-zh p195', 'catl-2025-zh p208']
- `q17` text_fact：Tesla的2025年报规定，存货发生减记后，后续事实和情况变化是否会恢复或提高该存货新确立的成本基础？请回答并引用英文原文依据。；标准页 ['tesla-2025-en p67']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p136', 'tesla-2025-en p136', 'tesla-2025-en p135']
- `q24` multi_page：请分别给出Tesla截至2025年12月31日合并资产负债表中的现金及现金等价物（Cash and cash equivalents），以及2025年合并现金流量表中的经营活动现金净流入（Net cash provided by operating activities），均按百万美元原值回答，并分别引用出处。；标准页 ['tesla-2025-en p52', 'tesla-2025-en p56']，名次 2，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p45', 'tesla-2025-en p56', 'tesla-2025-en p56']

### vector 没有命中标准页或答案不全的题（6 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p63', 'moutai-2025-zh p69', 'moutai-2025-zh p64']
- `q04` table_number：招商银行集团截至2025年12月31日的不良贷款率是多少（%）？；标准页 ['cmb-2025-zh p16']，名次 None，答案在前 8 条 True，实际前 3 条 ['cmb-2025-zh p31', 'cmb-2025-zh p19', 'cmb-2025-zh p32']
- `q13` text_fact：招商银行2025年年报“信用风险管理”如何定义信用风险？；标准页 ['cmb-2025-zh p63']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p260', 'cmb-2025-zh p64', 'cmb-2025-zh p40']
- `q14` text_fact：贵州茅台2025年年报“可能面对的风险”列出了哪四类风险？；标准页 ['moutai-2025-zh p23']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p122', 'moutai-2025-zh p3', 'moutai-2025-zh p2']
- `q21` english：In Kweichow Moutai's 2025 English annual report, which three major segments are described as working synergistically to stabilize market fundamentals?；标准页 ['moutai-2025-en p9']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p89', 'moutai-2025-en p8', 'moutai-2025-en p81']
- `q22` multi_page：请分别列出贵州茅台2025年经营活动产生的现金流量净额，以及2025年末合并报表存货中原材料的账面价值，均按元人民币原值回答；为两个指标分别给出处，不要计算。；标准页 ['moutai-2025-zh p6', 'moutai-2025-zh p91']，名次 5，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p66', 'moutai-2025-zh p64', 'moutai-2025-zh p65']

### hybrid 没有命中标准页或答案不全的题（3 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p12', 'moutai-2025-zh p141', 'moutai-2025-zh p10']
- `q03` table_number：宁德时代2025年营业收入是多少千元？请按年报原单位回答。；标准页 ['catl-2025-zh p11']，名次 None，答案在前 8 条 True，实际前 3 条 ['catl-2025-zh p24', 'catl-2025-zh p195', 'catl-2025-zh p30']
- `q21` english：In Kweichow Moutai's 2025 English annual report, which three major segments are described as working synergistically to stabilize market fundamentals?；标准页 ['moutai-2025-en p9']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p5', 'moutai-2025-en p169', 'moutai-2025-en p8']

### hybrid+rerank 没有命中标准页或答案不全的题（1 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p54', 'moutai-2025-zh p61', 'moutai-2025-zh p63']

## 答案：hybrid+rerank

通过 30/30，按标价估算费用 0.0863 元。

| 类型 | 通过 / 题数 |
| --- | --- |
| company_not_covered | 2/2 |
| english | 4/4 |
| fact_not_disclosed | 2/2 |
| investment_advice | 1/1 |
| multi_page | 3/3 |
| table_number | 9/9 |
| text_fact | 8/8 |
| year_not_covered | 1/1 |

### 没有通过的题（0 道）

无
