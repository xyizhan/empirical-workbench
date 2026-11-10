"""Interactive, dependency-free viewer for saved runs."""
import csv
import json
import sys
from itertools import islice
from pathlib import Path


def show_run(out: Path):
    run = json.loads((out / 'run.json').read_text())
    tables = sorted(out.glob('*.csv'))
    tab = '1'
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    while True:
        if interactive:
            print('\033[2J\033[H', end='')
        print(f"EMPIRICAL WORKBENCH    {out.name}    [{run['status']}]")
        print(run.get('question', ''))
        print('─' * 62)
        if tab == '1':
            for stage in run.get('stages', []):
                print(stage)
                for attempt in run.get('attempts', []):
                    if attempt['stage'] == stage:
                        print('   ', '✓' if attempt['outcome']=='accepted' else '↶', attempt['plan'])
                        if attempt.get('reason'):
                            print('      ', attempt['reason'])
            if run.get('reason'):
                print(run['reason'])
        elif tab == '2':
            for check in run['checks']:
                print('✓' if check['passed'] else '×', check['name'])
        elif tab == '3':
            for i, path in enumerate(tables, 1):
                print(f'  t{i}  {path.stem}')
        elif tab.startswith('t'):
            path = tables[int(tab[1:])-1]
            print(path.stem)
            with path.open(newline='') as stream:
                for row in islice(csv.reader(stream), 16):
                    print('  │  '.join(row))
        if not interactive:
            return
        try:
            key = input('\n[1] 轨迹  [2] 核验  [3] 底表  [t编号] 查看表  [q] 退出 › ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if key == 'q':
            return
        if key in ('1','2','3') or (key.startswith('t') and key[1:].isascii() and key[1:].isdigit() and 1 <= int(key[1:]) <= len(tables)):
            tab = key
