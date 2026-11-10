"""Interactive, dependency-free terminal viewer for saved runs."""
import csv
import sys
from itertools import islice
from pathlib import Path

from . import record

MARKS = {'passed': '✓', 'failed': '×', 'needs_decision': '◆', 'running': '…', 'pending': '·'}
STATUS = {'passed': '已通过', 'failed': '失败', 'needs_decision': '待研究者决定', 'interrupted': '已中断', 'running': '运行中'}


def stage_lines(stage):
    yield f'{MARKS.get(stage["status"], "?")} {stage["name"]}'
    for attempt in stage['attempts']:
        if len(stage['attempts']) > 1 or attempt['outcome'] != 'accepted':
            yield f'    {"✓ 采用" if attempt["outcome"] == "accepted" else "↶ 回滚"}  {attempt["plan"]}'
            if attempt.get('reason'):
                yield f'        {attempt["reason"]}'
    for change in stage['tables']:
        if change['change'] == 'created':
            yield f'    + {change["name"]}  {change["rows"]:,} 行'
        elif change['change'] == 'modified':
            yield f'    ~ {change["name"]}  {change["rows_before"]:,} → {change["rows"]:,} 行'
        else:
            yield f'    - {change["name"]}'
    if stage.get('decision'):
        yield f'    ◆ {stage["decision"]["name"]} = {stage["decision"]["value"]}（{stage["decision"]["source"]}）'


def show_run(out: Path):
    run = record.load(out)
    exports = [out / e['file'] for s in run['stages'] for e in s['exports'] if e['file'].endswith('.csv')]
    tab = '1'
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    while True:
        if interactive:
            print('\033[2J\033[H', end='')
        print(f"EMPIRICAL WORKBENCH    {out.name}    [{STATUS.get(run['status'], run['status'])}]")
        print(run['study']['question'])
        print('─' * 62)
        if tab == '1':
            for stage in run['stages']:
                for line in stage_lines(stage):
                    print(line)
            if run.get('reason'):
                print('\n' + run['reason'])
        elif tab == '2':
            for name, source in run['sources'].items():
                print(f'  {name}  {source["file"]}  {source["rows"]:,} 行')
            print()
            for stage in run['stages']:
                for attempt in stage['attempts']:
                    for check in attempt['checks']:
                        mark = '✓' if check['passed'] else ('!' if check['severity'] == 'warn' else '×')
                        extra = '' if check['passed'] else f'  {check["violations"]:,} 行'
                        print(f'{mark} {check["name"]}{extra}')
        elif tab == '3':
            for i, path in enumerate(exports, 1):
                print(f'  t{i}  {path.stem}')
        elif tab.startswith('t'):
            path = exports[int(tab[1:]) - 1]
            print(path.stem)
            with path.open(newline='', encoding='utf-8') as stream:
                for row in islice(csv.reader(stream), 16):
                    print('  │  '.join(row))
        if not interactive:
            return
        try:
            key = input('\n[1] 流程  [2] 来源与核验  [3] 导出表  [t编号] 查看表  [q] 退出 › ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if key == 'q':
            return
        if key in ('1', '2', '3') or (key.startswith('t') and key[1:].isdigit() and 1 <= int(key[1:]) <= len(exports)):
            tab = key
