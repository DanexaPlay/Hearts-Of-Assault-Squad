"""Small lossless-span reader for text Clausewitz saves; no binary guessing."""
from dataclasses import dataclass, field
import re, zipfile
from pathlib import Path

TOKEN = re.compile(r'\s+|\#[^\r\n]*|"(?:\\.|[^"\\])*"|[{}=]|[^\s{}=\#"]+')

@dataclass
class Node:
    key: str
    value: str | None
    start: int
    end: int
    children: list = field(default_factory=list)
    def all(self, key): return [n for n in self.children if n.key == key]
    def one(self, key):
        values = self.all(key)
        if len(values) != 1: raise ValueError(f'Expected one {key}, got {len(values)}')
        return values[0]
    def get(self, key, default=None):
        values = self.all(key)
        return values[-1].value if values else default
    def walk(self, key):
        for n in self.children:
            if n.key == key: yield n
            yield from n.walk(key)

def unquote(s):
    return s[1:-1].replace('\\"', '"').replace('\\\\', '\\') if s.startswith('"') else s

def parse(text):
    toks = [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)
            if not m.group().isspace() and not m.group().startswith('#')]
    i = 0
    def group(stop=False):
        nonlocal i
        nodes=[]
        while i < len(toks):
            token, start, end=toks[i]
            if token == '}':
                if not stop: raise ValueError('Unexpected closing brace')
                i+=1; return nodes,end
            if token=='{':
                i+=1; children,end=group(True)
                nodes.append(Node('',None,start,end,children)); continue
            if token=='=': raise ValueError('Unexpected token '+token)
            i+=1
            if i<len(toks) and toks[i][0]=='=':
                i+=1
                if i>=len(toks): raise ValueError('Missing value')
                val,_,vend=toks[i]; i+=1
                if val=='{':
                    children,vend=group(True)
                    nodes.append(Node(unquote(token),None,start,vend,children))
                elif val in ('}','='): raise ValueError('Invalid value')
                else: nodes.append(Node(unquote(token),unquote(val),start,vend))
            else: nodes.append(Node('',unquote(token),start,end))
        if stop: raise ValueError('Unclosed brace')
        return nodes,len(text)
    nodes,_=group()
    return Node('root',None,0,len(text),nodes)

def read_save(path):
    path=Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            if 'gamestate' not in z.namelist(): raise ValueError('No gamestate in save')
            data=z.read('gamestate')
    else: data=path.read_bytes()
    if data.startswith(b'HOI4bin') or b'\x00' in data[:64]:
        raise ValueError('Binary save unsupported. Use a non-Ironman text save (save_as_binary=no).')
    text=data.decode('utf-8-sig')
    if text.startswith('HOI4txt'): text=text[7:]
    return text,parse(text)
