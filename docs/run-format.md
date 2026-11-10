# 研究配置与运行记录格式

Empirical Workbench 的引擎、终端与网页查看器、报告插件、复算工具和 AI Agent 通过三份文件协作：研究者编写的 `study.json`，以及每次运行写出的 `run.json`、`events.jsonl`。本文是它们的约定。`run.json` 的格式标识为 `ew.run/1`，字段只增不改；不兼容的改动会提升版本号。

## study.json

```jsonc
{
  "title": "企业年度收入增长",              // 可选，报告与查看器标题
  "question": "各企业逐年收入增长率是多少？", // 可选，研究问题
  "unit": "一行一个企业年度",               // 可选，分析单位
  "sources": {                             // 必填：表名 → 本地文件
    "raw": {"file": "panel.csv",           // .csv .tsv .txt .parquet；装 [formats] 后可读 .xlsx .xls .dta
            "columns": ["firm", "year", "revenue"],  // 可选，省略则读取全部字段
            "types": {"firm": "VARCHAR"},  // 可选，覆盖自动识别的 DuckDB 类型
            "encoding": "gbk",             // 可选，默认自动识别（UTF-8，否则按 GB18030）
            "delimiter": ",", "sheet": 0}  // 可选
  },
  "decisions": {                           // 可选：需研究者确定的口径
    "延误定义": {"options": ["calendar", "clock"], "value": "calendar",
                "labels": {"calendar": "按自然日"}, "evidence": "口径比较.csv", "fields": {"switched": "换组数"}}
  },
  "stages": [{
    "name": "2 匹配相邻年度",               // 必填且唯一
    "description": "……",                   // 可选
    "sql": ["create table base as ..."],   // 或 candidates，二选一
    "candidates": [{"name": "方案甲", "sql": ["..."]}],
    "checks": {                            // 查询返回违规行；无行即通过
      "行数一致": "select ...",
      "收入为正": {"sql": "select ...", "severity": "warn", "description": "提醒但不阻断"}
    },
    "exports": {"分析表.csv": "select ...", "大表.parquet": "select ...", "回归样本.dta": "select ..."},  // .csv .csv.gz .parquet；[formats] 另支持 .dta .xlsx
    "decision": "延误定义",                 // 可选：本阶段结束时确定该口径，SQL 可读 decision 表
    "classroom": {"done": [], "rejected": []} // 可选：课堂投影页面
  }],
  "tools": {                               // 可选：运行后依次执行的独立复算
    "verify": {"argv": ["{python}", "{study}/verify.py", "{raw}", "{out}"], "label": "从原始 CSV 独立复算"}
  },
  "report": {"builder": "report.py"},      // 可选：研究自带的报告插件
  "guide": {}                              // 可选：课堂模式的引导文字
}
```

- SQL 使用 DuckDB 方言。来源按真实类型读入（时间戳、整数、浮点），以 0 开头的代码保持文本。GROUP BY 须列出所有非聚合字段；需要稳定行序的导出请写 ORDER BY。
- 每个候选方案在独立事务中执行：任何 SQL 错误或 error 级核验违规都会整体回滚该方案。
- 口径确定后，SQL 可读 `decision`（单列 value，最近确定的口径）或 `decisions(name, value)`。
- `ew validate STUDY` 一次列出全部问题：未知字段、重名阶段、未声明的口径、非法文件名等。
- 核验 `severity` 为 `error`（默认）时，违规会回滚当前候选方案并尝试下一个；为 `warn` 时只记录。
- 工具参数中的 `{python}` `{study}` `{raw}` `{out}` 分别替换为当前解释器、研究目录、原始数据目录和运行目录。工具运行时 `{out}/run.json` 已包含全部阶段结果与口径（`status` 仍为 `running`）。非零退出使整次运行失败。
- 报告插件是研究目录下的 Python 文件，定义 `build(out: Path, run: dict) -> str`，返回 Quarto markdown。未配置时使用通用表格报告。

## run.json

```jsonc
{
  "schema": "ew.run/1",
  "ew_version": "0.3.0",
  "status": "passed",          // running | passed | failed | needs_decision | interrupted
  "reason": null,              // 未通过时的原因
  "started_at": "2026-11-10T01:40:00+00:00", "finished_at": "...", "duration_s": 4.7,
  "study": {"path": "...", "dir": "...", "sha256": "...", "title": "...", "question": "...", "unit": "..."},
  "raw": "/abs/path/to/raw",
  "database": "run.duckdb",    // 运行结束时的工作数据库，可用 ew query RUN "SQL" 只读查询
  "sources": {"orders": {"file": "olist_orders_dataset.csv", "sha256": "...", "rows": 99441, "columns": ["..."],
                         "types": {"order_id": "VARCHAR", "order_purchase_timestamp": "TIMESTAMP"}, "encoding": "utf-8"}},
  "stages": [{
    "name": "2 整理与合并",
    "status": "passed",        // pending | running | passed | failed | needs_decision
    "duration_s": 1.2,
    "attempts": [{
      "plan": "直接连接", "outcome": "rejected", "reason": "每单至多一行：12,489 行违规，例如 [...]",
      "duration_s": 0.4,
      "checks": [{"name": "每单至多一行", "severity": "error", "passed": false,
                  "violations": 12489, "columns": ["order_id"], "examples": [["0008..."]]}]
    }],
    "tables": [{"name": "base", "change": "created", "rows": 99441, "columns": ["..."]},
               {"name": "qc", "change": "modified", "rows_before": 120, "rows": 98, "columns": ["..."]}],
    "exports": [{"file": "匹配对账.csv", "rows": 4, "columns": ["..."]}],
    "decision": {"name": "延误定义", "value": "calendar", "source": "interactive"}  // 仅含口径的阶段
  }],
  "decisions": {"延误定义": {"options": ["..."], "value": "calendar", "source": "interactive"}},
  "tools": [{"name": "verify", "label": "...", "argv": ["..."], "returncode": 0, "log": "verify.log", "duration_s": 0.9}],
  "report": {"source": "report.qmd", "builder": "tabular", "html": "report.html"}  // 生成报告后
}
```

- 运行开始即写入 `run.json`，所有声明的阶段先标记为 `pending`，每个阶段结束后更新，便于实时查看。
- `tables` 记录阶段前后有变化的表及行数，是样本流失与合并诊断的依据。被回滚的候选方案不留下表。
- 口径来源 `source`：`default`（配置默认值）、`command-line`（`--decision`）、`interactive`（运行中选择）。

## events.jsonl

每行一个事件，按发生顺序追加：

```json
{"seq": 12, "ts": "2026-11-10T01:40:01+00:00", "kind": "check.fail", "stage": "2 整理与合并", "message": "每单至多一行 · 12,489 行", "data": {"violations": 12489}}
```

| kind | 含义 | data |
|---|---|---|
| `run.start` / `run.end` | 运行开始 / 结束 | `run.end`: `status`, `reason` |
| `source.load` / `source.loaded` | 读取来源 | `table`, `rows` |
| `stage.start` / `stage.end` | 阶段开始 / 完成 | `tables`, `exports` |
| `plan.start` / `plan.accept` / `plan.rollback` | 候选方案 | `plan`, `candidates` |
| `sql` | 执行一条 SQL | |
| `check.start` / `check.pass` / `check.warn` / `check.fail` | 核验 | 与 run.json 中核验结果相同 |
| `export` | 导出文件 | |
| `decision.made` | 采用口径 | `name`, `value`, `source` |
| `evidence` | 课堂模式展示的现场查询 | `sql`, `columns`, `rows` |
| `tool.start` / `tool.end` | 外部工具 | `name`, `label`, `returncode` |

中文显示名见 `ew/record.py` 的 `EVENTS`。新增事件类型属于兼容改动。
