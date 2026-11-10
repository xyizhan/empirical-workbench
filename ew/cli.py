"""Command line and external tool boundary for Empirical Workbench."""
import argparse
import csv
import importlib.resources
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from types import SimpleNamespace
from . import engine
from .terminal import show_run


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2))


def dashboard(out):
    manifest=json.loads((out/'run.json').read_text())
    tables={}
    for file in sorted(out.glob('*.csv')):
        with file.open(newline='') as stream:
            reader=csv.reader(stream)
            from itertools import islice
            tables[file.name]=list(islice(reader,51))
    payload=json.dumps(dict(run=manifest,tables=tables),ensure_ascii=False).replace('<','\\u003c')
    template=importlib.resources.files('ew').joinpath('console.html').read_text()
    (out/'index.html').write_text(template.replace('__PAYLOAD__',payload))


def report(out, quiet=False):
    log=json.loads((out/'run.json').read_text())
    if log['status']!='passed':
        raise ValueError('Only verified runs can render a report')
    if '延误定义' in log.get('decisions', {}) and (out/'探索对照.csv').exists():
        from .olist_report import manuscript
        source = manuscript(out, log)
    else:
        source = tabular_report(out, log)
    (out/'report.qmd').write_text(source, encoding='utf-8')
    binary=shutil.which(os.environ.get('QUARTO_BIN','quarto'))
    if not binary:
        sys.exit('生成报告需要 Quarto CLI。请安装或设置 QUARTO_BIN 指向可执行文件。')
    with (out/'quarto.log').open('w') as stream:
        subprocess.run([str(Path(binary).resolve()),'render','report.qmd'],cwd=out,check=True,stdout=stream if quiet else None,stderr=subprocess.STDOUT if quiet else None)


def tabular_report(out, log):
    lines=['---','title: "Empirical Workbench · 研究报告"','format:','  html:','    embed-resources: true','---','',log.get('question',''), '']
    for path in sorted(out.glob('*.csv')):
        with path.open(newline='') as stream:
            from itertools import islice
            rows=list(islice(csv.reader(stream),31))
        if rows:
            lines+=['## '+path.stem,'','预览至多 30 行。','']
            rows.insert(1,['---']*len(rows[0]))
            lines.extend('| '+' | '.join(x.replace('|','\\|').replace('\n',' ') for x in row)+' |' for row in rows)
            lines.append('')
    return '\n'.join(lines)


def prompt_decision(name, decision, out):
    print(f'\n◆ 需要研究者选择 · {name}', flush=True)
    if decision.get('evidence'):
        with (out/decision['evidence']).open(newline='') as stream:
            row = next(csv.DictReader(stream), {})
        for field, label in decision.get('fields', {}).items():
            print(f'  {label}  {row[field]}')
    options = decision['options']
    for index, value in enumerate(options, 1):
        print(f"  [{index}] {decision.get('labels', {}).get(value, value)}  ({value})")
    while True:
        try:
            answer = input('选择编号或口径名称 › ').strip()
        except (EOFError, KeyboardInterrupt):
            raise ValueError('研究者未选择口径，运行已停止') from None
        for index, value in enumerate(options, 1):
            if answer in (str(index), value):
                decision['source'] = 'interactive'
                return value
        print('请从上列选项中选择。')


def main():
    parser=argparse.ArgumentParser(prog='ew')
    cmds=parser.add_subparsers(dest='cmd',required=True)
    inspect=cmds.add_parser('inspect')
    inspect.add_argument('raw',type=Path)
    run=cmds.add_parser('run', aliases=['demo'])
    run.add_argument('study',type=Path)
    run.add_argument('--raw',required=True,type=Path)
    run.add_argument('--out',required=True,type=Path)
    run.add_argument('--decision',action='append',default=[],metavar='KEY=VALUE')
    mode=run.add_mutually_exclusive_group()
    mode.add_argument('--interactive', dest='interactive', action='store_true')
    mode.add_argument('--batch', dest='interactive', action='store_false')
    run.set_defaults(interactive=None)
    run.add_argument('--report', action='store_true', help='核验后调用 Quarto')
    for name in ['view','report']:
        sub=cmds.add_parser(name)
        sub.add_argument('out',type=Path)
        if name=='view':
            sub.add_argument('--web',action='store_true')
    args=parser.parse_args()
    if args.cmd=='inspect':
        profile={}
        for path in sorted(args.raw.glob('*.csv')):
            with path.open(newline='', encoding='utf-8-sig') as f:
                reader=csv.DictReader(f)
                fields=reader.fieldnames or []
                nulls=dict.fromkeys(fields,0)
                count=0
                for row in reader:
                    count+=1
                    for field in fields:
                        if not row[field]: nulls[field]+=1
                profile[path.name]=dict(rows=count,missing=nulls)
        print(json.dumps(profile,ensure_ascii=False,indent=2))
        return
    out=args.out.resolve()
    if args.cmd=='report':
        report(out)
        return
    if args.cmd=='view':
        if args.web:
            dashboard(out)
            webbrowser.open((out/'index.html').as_uri())
        else:
            show_run(out)
        return
    study=args.study.resolve()
    spec=json.loads(study.read_text())
    explicit=set()
    for setting in args.decision:
        key,value=setting.split('=',1)
        explicit.add(key)
        spec['decisions'][key]['value']=value or None
        spec['decisions'][key]['source']='command-line'
    classroom = args.cmd=='demo'
    if classroom and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error('ew demo 需要交互终端；自动化请使用 ew run --batch')
    out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'study.json'
    save(snapshot,spec)
    work=out/'processing'
    error=None
    interactive = sys.stdin.isatty() if args.interactive is None else args.interactive
    def emit(kind, message):
        with (out/'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'event':kind,'message':message},ensure_ascii=False)+'\n')
        if presenter:
            presenter.event(kind,message)
        elif interactive:
            if kind=='SQLite' and len(message)>108:
                message=message[:105]+'…'
            print(f'[{kind}] {message}', flush=True)
    presenter=None
    if classroom:
        from .demo import Classroom
        presenter=Classroom(spec,emit)
        interactive=True
    def choose(name, decision, directory):
        if interactive and name not in explicit:
            return prompt_decision(name, decision, directory)
        return decision['value']
    try:
        if presenter:
            presenter.intro()
        emit('研究问题', spec.get('question',study.stem))
        engine.run(SimpleNamespace(study=snapshot,out=work,raw=args.raw),emit,choose,presenter.checkpoint if presenter else None)
        ctx=dict(python=sys.executable,study=str(study.parent),raw=str(args.raw.resolve()),out=str(work))
        for name,argv in spec.get('tools',{}).items():
            command=[part.format_map(ctx) for part in argv]
            emit('调用工具', ' '.join(command))
            result=subprocess.run(command,capture_output=True,text=True,timeout=300)
            (work/(name+'.log')).write_text(result.stdout+result.stderr)
            emit('工具结果', (result.stdout+result.stderr).strip() or f'exit {result.returncode}')
            result.check_returncode()
    except Exception as exc:
        error=str(exc)
    if work.exists():
        for file in work.iterdir(): shutil.move(str(file),out/file.name)
        work.rmdir()
    log=json.loads((out/'run.json').read_text()) if (out/'run.json').exists() else {}
    log.update(question=spec.get('question',''),stages=[s['name'] for s in spec['stages']])
    if error: log.update(status='stopped',reason=error)
    save(out/'run.json',log)
    dashboard(out)
    print(f'运行记录：{out}（ew view 查看）')
    if error: sys.exit(error)
    if args.report:
        emit('调用工具', 'Quarto · render report.qmd')
        report(out, quiet=classroom)
        emit('报告完成',str(out/'report.html'))
    if presenter:
        presenter.finish(out)

if __name__=='__main__':
    main()
