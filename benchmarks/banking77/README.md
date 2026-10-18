# 公开数据上的选择性意图分诊实验

这是 ResolveAI 的独立研究原型：词/字符双视角分类、开发集校准的低置信度转人工、可复现实验和误差分析。它没有替换当前中文IT诊断路由，不能称为现有系统上线后的效果提升；组合使用已有方法，不宣称算法首创。

## 数据与公平对照

使用 [PolyAI官方BANKING77](https://github.com/PolyAI-LDN/task-specific-datasets)，固定提交 `57ec275d8078af65b7731c2a98be812d844a6d6b`。官方train有10,003条，固定seed42分层拆为8,002条拟合和2,001条开发；官方test 3,080条、77类。数据是英文金融客服问题，不是中文IT工单。

三模型都只拟合8,002条，SVM的C固定为1，不搜索测试集结果：

- Word：词TF-IDF 1–2 gram + LinearSVC。
- Char：词边界字符TF-IDF 3–5 gram + 同一分类器，是必要的消融对照。
- Fusion：两种特征拼接 + 同一分类器，random_state均为42。

词表/IDF仅在拟合集拟合；开发集只用于阈值。最终不重新拟合全部train，避免模型分数尺度改变后沿用旧阈值。

## 最终结果

| 方案 | 测试准确率 | Macro-F1 | 合成错字准确率 | 自动接收覆盖率 | 接收部分误分率 | 单条P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Word | 88.34% | 88.36% | 78.05% | 86.72% | 5.62% | 0.563 |
| Char | 89.90% | 89.87% | 83.34% | 88.60% | 5.28% | 0.664 |
| Fusion | 90.81% | 90.82% | 83.70% | 90.58% | 5.02% | 1.449 |

融合相对词基线：准确率 **+2.47个百分点**，配对bootstrap 95%区间 **[+1.85,+3.18]个百分点**（2000次、seed42）；纠正95条、退步19条，净增加76条正确预测。合成错字准确率增加5.65个百分点；相对字符单视角仅增加0.36个百分点，说明抗错字收益主要来自字符视角。完整逐类结果见 [per_class.csv](results/per_class.csv)，常见混淆及正负变化见 [confusions.json](results/confusions.json)。不要只展示纠正案例而隐藏退步。

融合并非所有方面更好：单条P95约为词基线的2.6倍，字符单视角是更便宜的替代。这里是同机单线程、预热后前200个测试样本的本地稀疏模型推理（含向量化和分类），不含HTTP、LLM或真实服务负载；不代表在线SLA。整批吞吐单独记录于 [report.json](results/report.json)，不能代替逐请求延迟。

## 低置信度转人工

以SVM第一、第二名分数差作为置信度代理，不是概率。每个模型在开发集选择至少接收100条且接收误分率不超过5%的最大覆盖阈值，再冻结用于test。

融合在test接收2,790/3,080条（90.58%），其余290条交人工；接收部分错140条，误分率5.02%，自动正确覆盖全部样本的86.04%。开发集5%约束不是test保证，这次test确实略超过5%，如实保留。BANKING77没有自然OOS集，因此这不是“未知问题识别率”实验。

## 实验局限与执行记录

- 合成扰动固定为每条首个至少5个ASCII字母词的中间相邻字母交换；不按标签选择，也不等价于真实用户噪声。
- 官方train与test存在7个标准化文本的交集（按小写和空白归一计唯一文本）；保留官方拆分并披露，不宣称严格无重复泛化。
- bootstrap区间仅反映本测试样本的重采样差异，不覆盖其他领域、语言、全部训练随机性或生产数据漂移。
- 本次实际执行过5次测试评估，涉及首轮、显式随机种子和依赖修正、CSV导出及报告写入故障修复；不是只打开过一次测试集。没有基于test改变C、特征、拆分或阈值策略，一律采用最后完整成功轮次，不挑最好成绩。首轮记录私有归档。
- 发布报告的预测CSV哈希和协议哈希已记录，18,480条预测的准确率、覆盖率、接收误差已独立重算一致。模型参数冻结后增加的导出原子替换不会改变模型结果；逐行预测在本地生成，原始CSV及模型缓存不上传。
- 无真实LLM调用、企业部署、业务降本或工单解决率的实测，不能将本结果写成这些指标。下一步应在获授权的中文IT标注集上验证迁移效果。

## 复现

本模块不依赖主应用数据库或密钥。建议Python3.12独立环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe download_data.py
.\.venv\Scripts\python.exe run_benchmark.py
```

下载器核验固定SHA-256，写入忽略的 `.local/data/`；阈值在读取test标签前确定。代码和 [protocol.json](protocol.json) 给出拆分、特征、阈值及扰动规则，报告保存数据/协议/拟合索引哈希、环境与CPU训练耗时。新机器时延会改变，不能期待报告时间完全一致。

## 来源与许可

BANKING77由 Iñigo Casanueva、Tadas Temcinas、Daniela Gerz、Matthew Henderson、Ivan Vulić 等作者公开，数据遵循 **CC BY 4.0**，完整条款见 [LICENSE.data.txt](LICENSE.data.txt)；固定URL及校验和见 [source_manifest.json](source_manifest.json)。实验产生拆分、特征和合成扰动，原始数据不随本模块再分发。

引用：Casanueva et al. (2020), [Efficient Intent Detection with Dual Sentence Encoders](https://arxiv.org/abs/2003.04807), Proceedings of the 2nd Workshop on NLP for ConvAI, ACL 2020。主项目代码沿用原有来源和许可证，本数据许可与代码许可分别适用。
