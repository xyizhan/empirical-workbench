# Empirical Workbench

一个本地运行的实证数据工作台。通过 CLI 或配套 Agent Skill 读取原始 CSV，在 SQLite 中执行候选变换与核验，生成分析数据、中文终端交互控制台和 Quarto 报告。

## 五分钟运行

需要 Python 3.10+。在仓库根目录运行：

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
ew inspect studies/panel
ew run studies/panel/study.json --raw studies/panel --out runs/panel
ew view runs/panel
```

内置八行企业面板检验复合键、年度断档和零基期。两条可计算增长率分别为 +10%、−20%。终端控制台按 1/2/3 切换执行轨迹、数据核验和探索底表，按 q 退出。可用 ew view RUN --web 打开网页视图，每次运行均可离线回看。

## 课堂现场运行

在工程根目录启动，raw 指向解压后的 Olist CSV。每次使用新的输出目录。

```sh
ew run studies/olist/study.json --raw raw --out "runs/live-$(date +%s)" --interactive --report
```

终端逐项显示读取的文件、SQLite 操作、检查结果、回滚和替代方案。第 4 阶段展示本次计算的换组数量，等待输入 1（自然日）或 2（完整时点），之后再构建主分组、调用独立复算工具及 Quarto。完整事件保存在 events.jsonl，实际选择在 run.json。交互终端默认启用提问；自动化可指定 --batch 或用 --decision 预选口径。--report 需要本地 Quarto，省略该参数仍可运行其余环节。

## Olist 演示

从 [Olist 发布页](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) 下载并解压 CSV 至 raw/。本仓库提供配置与代码，原始订单数据由使用者放在本地。

```sh
ew run studies/olist/study.json --raw raw --out runs/olist
ew view runs/olist
ew report runs/olist
```

最后一条通过 Quarto CLI 生成 report.qmd 和独立 report.html。将 quarto 加入 PATH，或用 QUARTO_BIN 指定其可执行文件。运行目录同时保存完整压缩分析表、来源哈希、逐项检查和独立复算日志。网页视图「探索与底表」展示评分差的三步对照。

在新目录中以 `--decision '延误定义=clock'` 比较完整时点口径。指定空值 `--decision '延误定义='` 会在生成影响统计后暂停并以非零退出，控制台仍可回看。选择后用新目录重建。

## 扩展项目

- **新研究**复制 studies/panel。sources 声明输入文件及字段；stages 的 sql、checks、exports 描述变换、违规记录查询与导出。候选方案使用 candidates 数组，每项提供 name 与 sql。SQLite 保存点隔离尝试，失败后回滚并尝试下一项，保留证据。
- **新工具**在研究配置的 tools 中声明命名参数数组，例如 `["{python}","{study}/verify.py","{raw}","{out}"]`。参数逐项传递，调用顺序与配置一致，输出写入日志，失败阻止报告发布。配置和脚本可以执行本地代码，只运行信任的项目。工具的输出目录参数指向本次处理目录。
- **AI 调度**将 skills/empirical-workbench 提供给宿主 Agent。CLI 的命令、源码、检查与日志均可独立使用。当前内核依赖 Python 标准库；模型推理由宿主负责。Olist 内置候选连接和探索分支用于可重复教学；它们在配置中预定义。
- **验收**运行 `python -m unittest discover -s tests`。每次运行使用新目录，主表与中间计算在同一 SQLite 会话内生成。当前支持整次重跑，跨进程增量缓存、自由生成分支及跨项目自动升级尚属后续工作。

## 课堂演示顺序

先展开第二阶段查看直接连接失去订单唯一性的证据，再查看连接诊断底表。切换探索页，观察只改变样本和只改变评分口径时的差异。最后打开 Quarto 输出与 verify.log，核对结果的来源。
