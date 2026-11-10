---
name: empirical-workbench
description: 用 ew CLI 从原始 CSV 检查粒度、尝试并验证处理方案、比较研究口径，生成可回查的分析数据与 Quarto 报告。
---
先运行 ew inspect RAW --json 查看各字段类型、缺失、候选主键与前导零代码，结合数据字典判断候选观察单位，并用全量分组查询核对键。索取影响研究解释且无法从数据验证的定义。参照 studies/panel/study.json 创建该研究自己的配置，用 ew validate STUDY 检查，格式见 docs/run-format.md。sources 的 file 与 columns 映射本地 CSV；stages 中的 sql 生成中间结果，checks 返回违规源行，exports 输出底表。候选变换可以放入 candidates，每项带 name、sql，同阶段共用独立验收条件。

运行 ew run STUDY --raw RAW --out NEW_DIR。SQL 使用 DuckDB 方言。运行后可用 ew query OUT "SQL" --format json 只读查询任意中间表来检验假设。运行状态见 run.json 的 status（passed、failed、needs_decision、interrupted）。用 run.json 中各阶段的 attempts（核验违规行数与样例）和 tables（行数变化）定位最早可疑操作，记录假设并执行可区分解释的查询。修改方案后在新目录重跑；保持原验收条件，另查至少一个正常例子。关键业务定义不明时保留备选，交付影响数量、边界源行并请研究者决定。用 --decision KEY=VALUE 在新运行中重建。

探索中若同时改变样本与指标，增加固定样本的中间对照。先核对成员集合，再比较统计量。为关键结果编写从原表独立复算的工具，通过 tools 注册。核验通过后执行 ew report OUT 和 ew view OUT。说明证据覆盖、未决项以及哪些分支是预先设计的。

研究项目模式：ew run PROJECT 运行数据底座，ew run PROJECT --topic SLUG 运行选题。底座只做与选题无关的理解、合并、对账与质量标记，只标记不删除；变量构造与探索放在选题中，且须先与研究者确认选题。格式见 docs/run-format.md 的「研究项目」。
