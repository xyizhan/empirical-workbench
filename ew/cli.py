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


def report(out):
    log=json.loads((out/'run.json').read_text())
    if log['status']!='passed':
        raise ValueError('Only verified runs can render a report')
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
    (out/'report.qmd').write_text('\n'.join(lines))
    subprocess.run([os.environ.get('QUARTO_BIN','quarto'),'render','report.qmd'],cwd=out,check=True)


def main():
    parser=argparse.ArgumentParser(prog='ew')
    cmds=parser.add_subparsers(dest='cmd',required=True)
    inspect=cmds.add_parser('inspect')
    inspect.add_argument('raw',type=Path)
    run=cmds.add_parser('run')
    run.add_argument('study',type=Path)
    run.add_argument('--raw',required=True,type=Path)
    run.add_argument('--out',required=True,type=Path)
    run.add_argument('--decision',action='append',default=[],metavar='KEY=VALUE')
    for name in ['view','report']:
        cmds.add_parser(name).add_argument('out',type=Path)
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
        dashboard(out)
        webbrowser.open((out/'index.html').as_uri())
        return
    study=args.study.resolve()
    spec=json.loads(study.read_text())
    for setting in args.decision:
        key,value=setting.split('=',1)
        spec['decisions'][key]['value']=value or None
    out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'study.json'
    save(snapshot,spec)
    work=out/'processing'
    error=None
    try:
        engine.run(SimpleNamespace(study=snapshot,out=work,raw=args.raw))
        ctx=dict(python=sys.executable,study=str(study.parent),raw=str(args.raw.resolve()),out=str(work))
        for name,argv in spec.get('tools',{}).items():
            result=subprocess.run([part.format_map(ctx) for part in argv],capture_output=True,text=True,timeout=300)
            (work/(name+'.log')).write_text(result.stdout+result.stderr)
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
    print(out/'index.html')
    if error: sys.exit(error)

if __name__=='__main__':
    main()
