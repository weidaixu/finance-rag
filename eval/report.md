# 评测报告

由 `eval/run_eval.py` 生成，数字来自真实运行。样本量小，只能看大方向。

答案判定是偏严的子串匹配：换了说法的正确答案也会被判错，`manual_review` 的题要人工判断，所以没通过的题都要人工复核。

## 检索

Hit@k 和 MRR 按标准页计算。同一数字可能出现在多页，而题目只标了部分页面，所以它们偏严；「答案在前 8 条」看的是证据内容，较短的答案可能偶然命中，所以偏松。两者要一起看。

| 方式 | 题数 | Hit@1 | Hit@3 | Hit@8 | MRR | 找齐全部页面 | 答案在前 8 条 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bm25 | 80 | 54% | 74% | 79% | 0.633 | 71% | 74% |
| bm25（questions） | 24 | 54% | 79% | 88% | 0.667 | 79% | 88% |
| bm25（questions_v2） | 56 | 54% | 71% | 75% | 0.619 | 68% | 68% |
| vector | 80 | 51% | 75% | 81% | 0.633 | 78% | 84% |
| vector（questions） | 24 | 46% | 71% | 79% | 0.583 | 75% | 83% |
| vector（questions_v2） | 56 | 54% | 77% | 82% | 0.654 | 79% | 84% |
| hybrid | 80 | 61% | 74% | 84% | 0.688 | 79% | 86% |
| hybrid（questions） | 24 | 58% | 71% | 88% | 0.662 | 83% | 96% |
| hybrid（questions_v2） | 56 | 62% | 75% | 82% | 0.699 | 77% | 82% |
| hybrid+rerank | 80 | 64% | 86% | 95% | 0.761 | 88% | 91% |
| hybrid+rerank（questions） | 24 | 58% | 88% | 96% | 0.741 | 96% | 100% |
| hybrid+rerank（questions_v2） | 56 | 66% | 86% | 95% | 0.770 | 84% | 88% |

### bm25 没有命中标准页或答案不全的题（23 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p12', 'moutai-2025-zh p10', 'moutai-2025-zh p20']
- `q03` table_number：宁德时代2025年营业收入是多少千元？请按年报原单位回答。；标准页 ['catl-2025-zh p11']，名次 None，答案在前 8 条 True，实际前 3 条 ['catl-2025-zh p30', 'catl-2025-zh p195', 'catl-2025-zh p208']
- `q17` text_fact：Tesla的2025年报规定，存货发生减记后，后续事实和情况变化是否会恢复或提高该存货新确立的成本基础？请回答并引用英文原文依据。；标准页 ['tesla-2025-en p67']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p136', 'tesla-2025-en p136', 'tesla-2025-en p135']
- `q24` multi_page：请分别给出Tesla截至2025年12月31日合并资产负债表中的现金及现金等价物（Cash and cash equivalents），以及2025年合并现金流量表中的经营活动现金净流入（Net cash provided by operating activities），均按百万美元原值回答，并分别引用出处。；标准页 ['tesla-2025-en p52', 'tesla-2025-en p56']，名次 2，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p45', 'tesla-2025-en p56', 'tesla-2025-en p56']
- `q31` table_number：贵州茅台2025年末，母公司自身账上的应收账款有多少？；标准页 ['moutai-2025-zh p59']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p138', 'moutai-2025-zh p86', 'moutai-2025-zh p87']
- `q33` table_number：茅台合并报表的应收账款坏账准备，到2025年底还留有多少？；标准页 ['moutai-2025-zh p86']，名次 1，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p86', 'moutai-2025-zh p87', 'moutai-2025-zh p138']
- `q43` cross_language：根据茅台2025年英文年报，合并范围内这一年实际核销了多少应收账款？；标准页 ['moutai-2025-en p115']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p4', 'moutai-2025-en p5', 'moutai-2025-en p159']
- `q44` cross_language：茅台2025年英文年报披露，作为承租方，这一年与租赁有关的现金一共流出了多少？；标准页 ['moutai-2025-en p156']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p4', 'moutai-2025-en p5', 'moutai-2025-en p159']
- `q45` cross_language：茅台2025年英文年报的设定提存计划里，基本养老保险本年新增了多少？；标准页 ['moutai-2025-en p138']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p4', 'moutai-2025-en p5', 'moutai-2025-en p159']
- `q46` multi_page：请根据茅台2025年英文年报，分别找出母公司和主要子公司合计有多少在职员工，以及合并口径年底尚未支付的短期职工薪酬有多少。；标准页 ['moutai-2025-en p137', 'moutai-2025-en p37']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p4', 'moutai-2025-en p5', 'moutai-2025-en p159']
- `q54` multi_page：比亚迪2025年员工持股计划有多少参与员工？2022年那期又为什么提前终止？请分别给出出处。；标准页 ['byd-2025-zh p73', 'byd-2025-zh p74']，名次 1，答案在前 8 条 False，实际前 3 条 ['byd-2025-zh p74', 'byd-2025-zh p246', 'byd-2025-zh p73']
- `q64` table_number：招行2025年末向房地产业发放的贷款，本公司口径记了多少？请按原表单位给出金额，不用集团数。；标准页 ['cmb-2025-zh p34']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p152', 'cmb-2025-zh p54', 'cmb-2025-zh p43']
- `q65` table_number：招商银行集团2025年末已经拖欠超过三年的贷款余额是多少？请保留表中的数字并说明单位。；标准页 ['cmb-2025-zh p36']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p55', 'cmb-2025-zh p54', 'cmb-2025-zh p43']
- `q70` multi_page：招行集团2025年底给金融业的贷款和垫款金额是多少？同一时点，已重组贷款里逾期超过90天的金额又是多少？请分别给原表数值、单位和出处。；标准页 ['cmb-2025-zh p33', 'cmb-2025-zh p37']，名次 1，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p37', 'cmb-2025-zh p36', 'cmb-2025-zh p179']
- `q71` multi_page：招行2025年末本公司对批发和零售业的贷款和垫款金额，以及集团2025年为贷款损失准备新计提的金额，分别是多少？请逐项标明口径和原表单位，各附出处。；标准页 ['cmb-2025-zh p34', 'cmb-2025-zh p37']，名次 2，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p26', 'cmb-2025-zh p37', 'cmb-2025-zh p37']
- `q76` cross_language：特斯拉的能源销售合同中，截至2025年底，原预计期限超过一年的合同还未完成的履约义务对应多少交易价格？其中预计未来12个月确认多少？请保留报告中的数字和单位。；标准页 ['tesla-2025-en p61']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p85', 'tesla-2025-en p100', 'tesla-2025-en p106']
- `q77` cross_language：特斯拉2025年的汽车销售成本因取得制造抵免减少了多少？请给出报告原值和单位，不要用能源业务的数据。；标准页 ['tesla-2025-en p62']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p84', 'tesla-2025-en p73', 'tesla-2025-en p88']
- `q78` cross_language：特斯拉给带有服务或业绩条件的股票期权及员工购股计划估算公允价值时，采用哪一个期权定价模型？；标准页 ['tesla-2025-en p63']，名次 None，答案在前 8 条 False，实际前 3 条 []
- `q79` cross_language：特斯拉2025年结束时累计计提的保修负债余额是多少？请按披露的原值和单位回答。；标准页 ['tesla-2025-en p69', 'tesla-2025-en p70']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p84', 'tesla-2025-en p73', 'tesla-2025-en p88']
- `q81` multi_company：截至2025年末，比亚迪和宁德时代各自整个集团账上的资产一共有多少？请分别列出。；标准页 ['byd-2025-zh p123', 'catl-2025-zh p112']，名次 None，答案在前 8 条 False，实际前 3 条 ['catl-2025-zh p220', 'byd-2025-zh p260', 'catl-2025-zh p221']
- `q83` multi_company：2025年底，茅台和招行各自合并报表里的资产总规模是多少？请分别给出原表数值。；标准页 ['cmb-2025-zh p127', 'moutai-2025-zh p57']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p10', 'moutai-2025-zh p48', 'cmb-2025-zh p8']
- `q84` multi_company：截至2025年底，茅台和Tesla的合并报表各列了多少负债总额？分别回答即可。；标准页 ['moutai-2025-zh p58', 'tesla-2025-en p52']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p136', 'moutai-2025-zh p48', 'tesla-2025-en p136']
- `q85` multi_company：2025年底，比亚迪和Tesla各有多少员工？比亚迪取母公司加主要子公司的在职总人数，Tesla取全球员工总数。；标准页 ['byd-2025-zh p69', 'tesla-2025-en p14']，名次 2，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p136', 'byd-2025-zh p69', 'tesla-2025-en p136']

### vector 没有命中标准页或答案不全的题（19 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p63', 'moutai-2025-zh p69', 'moutai-2025-zh p64']
- `q04` table_number：招商银行集团截至2025年12月31日的不良贷款率是多少（%）？；标准页 ['cmb-2025-zh p16']，名次 None，答案在前 8 条 True，实际前 3 条 ['cmb-2025-zh p31', 'cmb-2025-zh p19', 'cmb-2025-zh p32']
- `q13` text_fact：招商银行2025年年报“信用风险管理”如何定义信用风险？；标准页 ['cmb-2025-zh p63']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p260', 'cmb-2025-zh p64', 'cmb-2025-zh p40']
- `q14` text_fact：贵州茅台2025年年报“可能面对的风险”列出了哪四类风险？；标准页 ['moutai-2025-zh p23']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p122', 'moutai-2025-zh p3', 'moutai-2025-zh p2']
- `q21` english：In Kweichow Moutai's 2025 English annual report, which three major segments are described as working synergistically to stabilize market fundamentals?；标准页 ['moutai-2025-en p9']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p89', 'moutai-2025-en p8', 'moutai-2025-en p81']
- `q22` multi_page：请分别列出贵州茅台2025年经营活动产生的现金流量净额，以及2025年末合并报表存货中原材料的账面价值，均按元人民币原值回答；为两个指标分别给出处，不要计算。；标准页 ['moutai-2025-zh p6', 'moutai-2025-zh p91']，名次 5，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p66', 'moutai-2025-zh p64', 'moutai-2025-zh p65']
- `q31` table_number：贵州茅台2025年末，母公司自身账上的应收账款有多少？；标准页 ['moutai-2025-zh p59']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p70', 'moutai-2025-zh p137', 'moutai-2025-zh p138']
- `q35` text_fact：茅台哪家境外子公司使用了人民币以外的记账货币，具体用什么币种？；标准页 ['moutai-2025-zh p72']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p116', 'moutai-2025-en p156', 'moutai-2025-zh p117']
- `q37` text_fact：茅台把用于出租的房地产入账以后，后续采用什么计量模式？；标准页 ['moutai-2025-zh p78']，名次 4，答案在前 8 条 False，实际前 3 条 ['moutai-2025-zh p82', 'moutai-2025-zh p96', 'moutai-2025-zh p96']
- `q40` english：What amount did Moutai report for freight services obtained from its group's logistics company in 2025?；标准页 ['moutai-2025-en p47']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-en p172', 'moutai-2025-en p171', 'moutai-2025-en p176']
- `q44` cross_language：茅台2025年英文年报披露，作为承租方，这一年与租赁有关的现金一共流出了多少？；标准页 ['moutai-2025-en p156']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p87', 'moutai-2025-en p87', 'moutai-2025-en p85']
- `q50` table_number：比亚迪集团2025年末机器设备扣完折旧和减值后的账面价值是多少？；标准页 ['byd-2025-zh p184']，名次 None，答案在前 8 条 False，实际前 3 条 ['byd-2025-zh p42', 'byd-2025-zh p188', 'byd-2025-zh p41']
- `q56` table_number：宁德时代集团2025年末原材料扣掉减值准备后，在账上还剩多少？；标准页 ['catl-2025-zh p172']，名次 2，答案在前 8 条 False，实际前 3 条 ['catl-2025-zh p181', 'catl-2025-zh p172', 'catl-2025-zh p125']
- `q64` table_number：招行2025年末向房地产业发放的贷款，本公司口径记了多少？请按原表单位给出金额，不用集团数。；标准页 ['cmb-2025-zh p34']，名次 None，答案在前 8 条 True，实际前 3 条 ['cmb-2025-zh p47', 'cmb-2025-zh p175', 'cmb-2025-zh p43']
- `q70` multi_page：招行集团2025年底给金融业的贷款和垫款金额是多少？同一时点，已重组贷款里逾期超过90天的金额又是多少？请分别给原表数值、单位和出处。；标准页 ['cmb-2025-zh p33', 'cmb-2025-zh p37']，名次 1，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p37', 'cmb-2025-zh p262', 'cmb-2025-zh p36']
- `q71` multi_page：招行2025年末本公司对批发和零售业的贷款和垫款金额，以及集团2025年为贷款损失准备新计提的金额，分别是多少？请逐项标明口径和原表单位，各附出处。；标准页 ['cmb-2025-zh p34', 'cmb-2025-zh p37']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p53', 'cmb-2025-zh p26', 'cmb-2025-zh p184']
- `q81` multi_company：截至2025年末，比亚迪和宁德时代各自整个集团账上的资产一共有多少？请分别列出。；标准页 ['byd-2025-zh p123', 'catl-2025-zh p112']，名次 None，答案在前 8 条 False，实际前 3 条 ['catl-2025-zh p128', 'byd-2025-zh p256', 'catl-2025-zh p111']
- `q83` multi_company：2025年底，茅台和招行各自合并报表里的资产总规模是多少？请分别给出原表数值。；标准页 ['cmb-2025-zh p127', 'moutai-2025-zh p57']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p15', 'moutai-2025-zh p92', 'cmb-2025-zh p320']
- `q84` multi_company：截至2025年底，茅台和Tesla的合并报表各列了多少负债总额？分别回答即可。；标准页 ['moutai-2025-zh p58', 'tesla-2025-en p52']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p79', 'moutai-2025-zh p105', 'tesla-2025-en p34']

### hybrid 没有命中标准页或答案不全的题（15 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p12', 'moutai-2025-zh p141', 'moutai-2025-zh p10']
- `q03` table_number：宁德时代2025年营业收入是多少千元？请按年报原单位回答。；标准页 ['catl-2025-zh p11']，名次 None，答案在前 8 条 True，实际前 3 条 ['catl-2025-zh p24', 'catl-2025-zh p195', 'catl-2025-zh p30']
- `q21` english：In Kweichow Moutai's 2025 English annual report, which three major segments are described as working synergistically to stabilize market fundamentals?；标准页 ['moutai-2025-en p9']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p5', 'moutai-2025-en p169', 'moutai-2025-en p8']
- `q31` table_number：贵州茅台2025年末，母公司自身账上的应收账款有多少？；标准页 ['moutai-2025-zh p59']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p138', 'moutai-2025-zh p87', 'moutai-2025-zh p133']
- `q40` english：What amount did Moutai report for freight services obtained from its group's logistics company in 2025?；标准页 ['moutai-2025-en p47']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-en p172', 'moutai-2025-en p171', 'moutai-2025-en p173']
- `q44` cross_language：茅台2025年英文年报披露，作为承租方，这一年与租赁有关的现金一共流出了多少？；标准页 ['moutai-2025-en p156']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p159', 'moutai-2025-en p4', 'moutai-2025-en p85']
- `q45` cross_language：茅台2025年英文年报的设定提存计划里，基本养老保险本年新增了多少？；标准页 ['moutai-2025-en p138']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p159', 'moutai-2025-en p140', 'moutai-2025-en p65']
- `q46` multi_page：请根据茅台2025年英文年报，分别找出母公司和主要子公司合计有多少在职员工，以及合并口径年底尚未支付的短期职工薪酬有多少。；标准页 ['moutai-2025-en p137', 'moutai-2025-en p37']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p77', 'moutai-2025-en p140', 'moutai-2025-en p79']
- `q64` table_number：招行2025年末向房地产业发放的贷款，本公司口径记了多少？请按原表单位给出金额，不用集团数。；标准页 ['cmb-2025-zh p34']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p47', 'cmb-2025-zh p43', 'cmb-2025-zh p55']
- `q65` table_number：招商银行集团2025年末已经拖欠超过三年的贷款余额是多少？请保留表中的数字并说明单位。；标准页 ['cmb-2025-zh p36']，名次 4，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p32', 'cmb-2025-zh p31', 'cmb-2025-zh p37']
- `q71` multi_page：招行2025年末本公司对批发和零售业的贷款和垫款金额，以及集团2025年为贷款损失准备新计提的金额，分别是多少？请逐项标明口径和原表单位，各附出处。；标准页 ['cmb-2025-zh p34', 'cmb-2025-zh p37']，名次 5，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p26', 'cmb-2025-zh p184', 'cmb-2025-zh p53']
- `q77` cross_language：特斯拉2025年的汽车销售成本因取得制造抵免减少了多少？请给出报告原值和单位，不要用能源业务的数据。；标准页 ['tesla-2025-en p62']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p41', 'tesla-2025-en p97', 'tesla-2025-en p43']
- `q81` multi_company：截至2025年末，比亚迪和宁德时代各自整个集团账上的资产一共有多少？请分别列出。；标准页 ['byd-2025-zh p123', 'catl-2025-zh p112']，名次 None，答案在前 8 条 False，实际前 3 条 ['catl-2025-zh p128', 'byd-2025-zh p256', 'catl-2025-zh p220']
- `q83` multi_company：2025年底，茅台和招行各自合并报表里的资产总规模是多少？请分别给出原表数值。；标准页 ['cmb-2025-zh p127', 'moutai-2025-zh p57']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p252', 'moutai-2025-zh p101', 'cmb-2025-zh p10']
- `q84` multi_company：截至2025年底，茅台和Tesla的合并报表各列了多少负债总额？分别回答即可。；标准页 ['moutai-2025-zh p58', 'tesla-2025-en p52']，名次 None，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p79', 'moutai-2025-zh p105', 'tesla-2025-en p136']

### hybrid+rerank 没有命中标准页或答案不全的题（8 道）

- `q01` table_number：贵州茅台2025年营业收入是多少元人民币？请保留年报原始数字，不换算单位。；标准页 ['moutai-2025-zh p6']，名次 None，答案在前 8 条 True，实际前 3 条 ['moutai-2025-zh p54', 'moutai-2025-zh p61', 'moutai-2025-zh p63']
- `q44` cross_language：茅台2025年英文年报披露，作为承租方，这一年与租赁有关的现金一共流出了多少？；标准页 ['moutai-2025-en p156']，名次 None，答案在前 8 条 False，实际前 3 条 ['moutai-2025-en p85', 'moutai-2025-en p174', 'moutai-2025-en p87']
- `q65` table_number：招商银行集团2025年末已经拖欠超过三年的贷款余额是多少？请保留表中的数字并说明单位。；标准页 ['cmb-2025-zh p36']，名次 1，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p36', 'cmb-2025-zh p276', 'cmb-2025-zh p37']
- `q69` multi_page：请分别查一下招行集团2025年底正常类贷款的金额，以及逾期三个月至一年的贷款金额；两项各给出处，并按年报原单位回答。；标准页 ['cmb-2025-zh p31', 'cmb-2025-zh p36']，名次 5，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p279', 'cmb-2025-zh p178', 'cmb-2025-zh p179']
- `q70` multi_page：招行集团2025年底给金融业的贷款和垫款金额是多少？同一时点，已重组贷款里逾期超过90天的金额又是多少？请分别给原表数值、单位和出处。；标准页 ['cmb-2025-zh p33', 'cmb-2025-zh p37']，名次 1，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p37', 'cmb-2025-zh p279', 'cmb-2025-zh p178']
- `q71` multi_page：招行2025年末本公司对批发和零售业的贷款和垫款金额，以及集团2025年为贷款损失准备新计提的金额，分别是多少？请逐项标明口径和原表单位，各附出处。；标准页 ['cmb-2025-zh p34', 'cmb-2025-zh p37']，名次 None，答案在前 8 条 False，实际前 3 条 ['cmb-2025-zh p182', 'cmb-2025-zh p184', 'cmb-2025-zh p174']
- `q81` multi_company：截至2025年末，比亚迪和宁德时代各自整个集团账上的资产一共有多少？请分别列出。；标准页 ['byd-2025-zh p123', 'catl-2025-zh p112']，名次 None，答案在前 8 条 False，实际前 3 条 ['catl-2025-zh p220', 'byd-2025-zh p41', 'catl-2025-zh p221']
- `q84` multi_company：截至2025年底，茅台和Tesla的合并报表各列了多少负债总额？分别回答即可。；标准页 ['moutai-2025-zh p58', 'tesla-2025-en p52']，名次 2，答案在前 8 条 False，实际前 3 条 ['tesla-2025-en p76', 'moutai-2025-zh p58', 'tesla-2025-en p73']

## 答案：hybrid+rerank

通过 88/100，按标价估算费用 0.3480 元。

| 题目文件 | 通过 / 题数 |
| --- | --- |
| questions | 30/30 |
| questions_v2 | 58/70 |

| 类型 | 通过 / 题数 |
| --- | --- |
| company_not_covered | 5/5 |
| cross_language | 6/8 |
| english | 12/12 |
| fact_not_disclosed | 7/7 |
| investment_advice | 4/4 |
| multi_company | 4/6 |
| multi_page | 6/9 |
| table_number | 23/25 |
| text_fact | 17/20 |
| year_not_covered | 4/4 |

### 没有通过的题（12 道）

- `q37` wrong_answer：茅台把用于出租的房地产入账以后，后续采用什么计量模式？；期望 ['投资性房地产', '成本模式']，标准页 ['moutai-2025-zh p78']，引用 ['moutai-2025-zh p96', 'moutai-2025-en p105', 'moutai-2025-zh p78']
- `q44` wrongly_refused：茅台2025年英文年报披露，作为承租方，这一年与租赁有关的现金一共流出了多少？；期望 ['79,478,309.20']，标准页 ['moutai-2025-en p156']，引用 []
- `q53` wrong_answer：比亚迪2025年报对裁员补偿何时确认负债采用怎样的先后原则？需要比较哪两个时点？；期望 ['孰早日', '单方面撤回', '重组']，标准页 ['byd-2025-zh p153']，引用 ['byd-2025-zh p153']
- `q61` wrong_answer：宁德时代在2025年报中判断一项安排是否受共同控制时，哪一类权利不纳入考虑？；期望 ['保护性权利', '共同控制']，标准页 ['catl-2025-zh p146']，引用 ['catl-2025-zh p146']
- `q65` wrongly_refused：招商银行集团2025年末已经拖欠超过三年的贷款余额是多少？请保留表中的数字并说明单位。；期望 ['8,024', '逾期3年以上']，标准页 ['cmb-2025-zh p36']，引用 []
- `q66` wrong_answer：招行集团在2025年底列入关注类的贷款有多少？请给出年报原值及其单位。；期望 ['103,860', '关注类贷款']，标准页 ['cmb-2025-zh p31']，引用 ['cmb-2025-zh p31']
- `q69` partial_answer：请分别查一下招行集团2025年底正常类贷款的金额，以及逾期三个月至一年的贷款金额；两项各给出处，并按年报原单位回答。；期望 ['7,085,992', '26,666']，标准页 ['cmb-2025-zh p31', 'cmb-2025-zh p36']，引用 ['cmb-2025-zh p178', 'cmb-2025-zh p36']
- `q70` partial_answer：招行集团2025年底给金融业的贷款和垫款金额是多少？同一时点，已重组贷款里逾期超过90天的金额又是多少？请分别给原表数值、单位和出处。；期望 ['146,117', '8,165']，标准页 ['cmb-2025-zh p33', 'cmb-2025-zh p37']，引用 ['cmb-2025-zh p37']
- `q71` partial_answer：招行2025年末本公司对批发和零售业的贷款和垫款金额，以及集团2025年为贷款损失准备新计提的金额，分别是多少？请逐项标明口径和原表单位，各附出处。；期望 ['277,000', '42,582']，标准页 ['cmb-2025-zh p34', 'cmb-2025-zh p37']，引用 ['cmb-2025-zh p217']
- `q79` wrong_answer：特斯拉2025年结束时累计计提的保修负债余额是多少？请按披露的原值和单位回答。；期望 ['8,607', 'warranty']，标准页 ['tesla-2025-en p69', 'tesla-2025-en p70']，引用 ['tesla-2025-en p70']
- `q81` wrongly_refused：截至2025年末，比亚迪和宁德时代各自整个集团账上的资产一共有多少？请分别列出。；期望 ['883,729,883', '974,827,544']，标准页 ['byd-2025-zh p123', 'catl-2025-zh p112']，引用 []
- `q84` partial_answer：截至2025年底，茅台和Tesla的合并报表各列了多少负债总额？分别回答即可。；期望 ['49,875,590,112.37', '54,941']，标准页 ['moutai-2025-zh p58', 'tesla-2025-en p52']，引用 ['moutai-2025-zh p58']

### 引用原文里找不到的数字

- `q70`：['37']
- `q71`：['1', '2']
