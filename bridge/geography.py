"""Read vanilla province connectivity and current save controllers."""
import csv,re
from pathlib import Path
from .clausewitz import parse
from .gem import block_at
from .core import BridgeError

def neighbors(province,game_dir):
    import numpy as np
    from PIL import Image
    root=Path(game_dir); rows={int(r[0]):r for r in csv.reader((root/'map/definition.csv').open(encoding='utf-8-sig'),delimiter=';')}
    colors={tuple(map(int,r[1:4])):pid for pid,r in rows.items()}
    if province not in rows: raise BridgeError('Unknown province')
    pixels=np.asarray(Image.open(root/'map/provinces.bmp').convert('RGB'))
    ys,xs=np.where(np.all(pixels==list(map(int,rows[province][1:4])),axis=2)); result=set()
    for dy,dx in ((0,1),(0,-1),(1,0),(-1,0)):
        y=np.clip(ys+dy,0,pixels.shape[0]-1); x=(xs+dx)%pixels.shape[1]
        for color in np.unique(pixels[y,x],axis=0):
            pid=colors.get(tuple(color))
            if pid is not None and pid!=province and rows[pid][4]=='land': result.add(pid)
    adjacency=root/'map/adjacencies.csv'
    if adjacency.exists():
        with adjacency.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream,delimiter=';'):
                if row.get('Type')!='impassable': continue
                a,b=int(row['From']),int(row['To'])
                if a==province: result.discard(b)
                if b==province: result.discard(a)
    return result

def controllers(text,game_dir):
    state_controls={}; overrides={}
    for section,target,key in [('states',state_controls,'owner'),('provinces',overrides,'controller')]:
        match=re.search(r'(?m)^'+section+r'=\{',text)
        if not match: raise BridgeError('Missing '+section)
        tree=parse(section+'='+block_at(text,text.index('{',match.start()))).one(section)
        for node in tree.children:
            if node.key.isdigit() and node.get(key): target[int(node.key)]=node.get('controller',node.get(key))
    result={}
    for path in (Path(game_dir)/'history/states').glob('*.txt'):
        source=path.read_text(encoding='utf-8-sig'); state=re.search(r'\bid\s*=\s*(\d+)',source); group=re.search(r'\bprovinces\s*=\s*\{([^}]+)\}',source)
        if state and group and int(state[1]) in state_controls:
            for pid in group[1].split(): result[int(pid)]=state_controls[int(state[1])]
    result.update(overrides); return result
