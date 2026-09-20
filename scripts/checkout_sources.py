#!/usr/bin/env python3
"""Clone pinned public source/feeds. No credentials or user firmware backups needed."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def run(args,**kw): return subprocess.run([str(x) for x in args],check=True,**kw)

def checkout(spec,dest):
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git',spec['url']):
        raise ValueError('Only explicit public GitHub HTTPS repositories are allowed')
    if not re.fullmatch('[0-9a-f]{40}',spec['sha']): raise ValueError('Expected a full commit SHA')
    dest.mkdir(parents=True,exist_ok=False)
    run(['git','init',dest]); run(['git','-C',dest,'remote','add','origin',spec['url']])
    run(['git','-C',dest,'fetch','--depth=1','--no-tags','origin',spec['sha']])
    run(['git','-C',dest,'checkout','--detach','FETCH_HEAD'])
    actual=run(['git','-C',dest,'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    if actual!=spec['sha']: raise ValueError('Checked-out commit does not match lock')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args(); src=args.source.resolve()
    if src.exists(): raise SystemExit('Refusing to replace an existing source directory; use a new empty build folder.')
    lock=json.loads((ROOT/'config/source-lock.json').read_text())
    checkout(lock['source'],src)
    feeds=src.parent/'feeds-pinned'; feeds.mkdir(exist_ok=False)
    lines=[]
    for item in lock['feeds']:
        name=item['name']
        if not re.fullmatch('[a-z0-9_]+',name): raise ValueError('Invalid feed name')
        dest=feeds/name; checkout(item,dest)
        # src-link avoids a later feeds update silently moving a pinned checkout.
        lines.append(f'src-link {name} {dest}\n')
    (src/'feeds.conf').write_text(''.join(lines))
