"""Report sources for a verified run, and optional rendering with the Quarto CLI.

A study may supply its own builder via study.json {"report": {"builder": "report.py"}}:
a Python file, relative to the study directory, defining build(out: Path, run: dict) -> str
that returns Quarto markdown. Without one, a generic tabular report is written.
"""
import csv
import importlib.util
import json
import os
import shutil
import subprocess
from itertools import islice
from pathlib import Path

from . import record

PREVIEW_ROWS = 30


def tabular(out, run):
    title = json.dumps(run['study']['title'], ensure_ascii=False)
    lines = ['---', f'title: {title}', 'lang: zh', 'format:', '  html:',
             '    embed-resources: true', '    toc: true', '---', '', run['study']['question'], '']
    for stage in run['stages']:
        lines += [f'## {stage["name"]}', '']
        if stage.get('description'):
            lines += [stage['description'], '']
        for change in stage['tables']:
            if change['change'] == 'dropped':
                lines.append(f'- 删除表 `{change["name"]}`')
            elif change['change'] == 'modified':
                lines.append(f'- 表 `{change["name"]}`：{change["rows_before"]:,} → {change["rows"]:,} 行')
            else:
                lines.append(f'- 新建表 `{change["name"]}`：{change["rows"]:,} 行')
        for attempt in stage['attempts']:
            for check in attempt['checks']:
                mark = '✓' if check['passed'] else ('!' if check['severity'] == 'warn' else '×')
                lines.append(f'- {mark} {check["name"]}')
        lines.append('')
        for item in stage['exports']:
            path = out / item['file']
            if path.suffix != '.csv':
                continue
            with path.open(newline='', encoding='utf-8') as stream:
                rows = list(islice(csv.reader(stream), PREVIEW_ROWS + 1))
            if not rows:
                continue
            lines += [f'### {path.stem}', '', f'共 {item["rows"]:,} 行，预览至多 {PREVIEW_ROWS} 行。', '']
            rows.insert(1, ['---'] * len(rows[0]))
            lines.extend('| ' + ' | '.join(x.replace('|', '\\|').replace('\n', ' ') for x in row) + ' |' for row in rows)
            lines.append('')
    return '\n'.join(lines)


def builder(out, run):
    """Return (name, build function) for this run's report, as configured in the run's study snapshot."""
    spec = json.loads((Path(out) / 'study.json').read_text(encoding='utf-8'))
    config = spec.get('report')
    if not config:
        return 'tabular', tabular
    path = Path(run['study']['dir']) / config['builder']
    if not path.is_file():
        raise FileNotFoundError(f'报告构建脚本不存在：{path}')
    module_spec = importlib.util.spec_from_file_location(f'ew_study_report_{abs(hash(str(path)))}', path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if not callable(getattr(module, 'build', None)):
        raise AttributeError(f'{path} 需要定义 build(out, run) -> str')
    return str(path), module.build


def write_source(out):
    """Write report.qmd for a passed run and return its path."""
    out = Path(out)
    run = record.load(out)
    if run['status'] != record.PASSED:
        raise ValueError('只有全部核验通过的运行才能生成报告')
    name, build = builder(out, run)
    path = out / 'report.qmd'
    path.write_text(build(out, run), encoding='utf-8')
    run['report'] = dict(source=path.name, builder=name, html=None)
    record.save_json(out / 'run.json', run)
    return path


def quarto():
    return shutil.which(os.environ.get('QUARTO_BIN', 'quarto'))


def render(out, quiet=False):
    """Write report.qmd and render report.html with Quarto; returns the html path."""
    out = Path(out)
    source = write_source(out)
    binary = quarto()
    if not binary:
        raise FileNotFoundError(f'已写出 {source.name}；渲染 HTML 需要 Quarto CLI，请安装或设置 QUARTO_BIN')
    with (out / 'quarto.log').open('w') as log:
        subprocess.run([str(Path(binary).resolve()), 'render', source.name], cwd=out, check=True,
                       stdout=log if quiet else None, stderr=subprocess.STDOUT if quiet else None)
    run = record.load(out)
    run['report']['html'] = 'report.html'
    record.save_json(out / 'run.json', run)
    return out / 'report.html'
