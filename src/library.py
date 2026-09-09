"""Atomic immutable library snapshots. Index failures leave the active library intact."""
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import TypeAdapter
from .models import FAQ
from .bm25_retriever import BM25Retriever
from .document_import import parse_document, PARSER_VERSION
from .ingest import load_documents

LOCK = RLock()


class Library:
    def __init__(self, root: Path):
        self.root = root

    def current(self):
        pointer = self.root / 'current.json'
        if not pointer.exists():
            return None
        name = json.loads(pointer.read_text(encoding='utf-8'))['generation']
        if not isinstance(name, str) or len(name) != 32 or any(c not in '0123456789abcdef' for c in name):
            raise ValueError('知识库版本记录损坏。')
        folder = self.root / name
        state = json.loads((folder / 'library.json').read_text(encoding='utf-8'))
        docs = TypeAdapter(list[FAQ]).validate_python(state['documents'])
        return state, docs, BM25Retriever.load(docs, folder / 'index')

    def publish(self, sources, docs):
        self.root.mkdir(parents=True, exist_ok=True)
        generation = uuid4().hex
        folder = self.root / generation
        folder.mkdir()
        docs = sorted(docs, key=lambda d: d.id)
        if len({d.id for d in docs}) != len(docs):
            raise ValueError('重复的文档 ID，未更新知识库。')
        BM25Retriever.build(docs, folder / 'index')
        state = {'generation': generation, 'sources': sources,
                 'documents': [doc.model_dump(mode='json') for doc in docs]}
        (folder / 'library.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        temp = self.root / (generation + '.tmp')
        temp.write_text(json.dumps({'generation': generation}), encoding='utf-8')
        os.replace(temp, self.root / 'current.json')
        return state

    def initialize(self, cfg):
        with LOCK:
            if self.current() is not None:
                return
            docs = load_documents(cfg)
            sources = {}
            for doc in docs:
                name = doc.source.split('｜')[0]
                entry = sources.setdefault(name.casefold(), {'name': name, 'hash': None, 'parser_version': 'legacy',
                    'doc_ids': [], 'warnings': ['由原有 FAQ 导入；图片未解析。']})
                entry['doc_ids'].append(doc.id)
            self.publish(sources, docs)

    def import_file(self, name, data):
        name = name.replace('\\', '/').rsplit('/', 1)[-1]
        digest = hashlib.sha256(data).hexdigest()
        with LOCK:
            current = self.current()
            state, docs = (current[0], current[1]) if current else ({'sources': {}}, [])
            sources = dict(state['sources'])
            for entry in sources.values():
                if entry['hash'] == digest and entry['parser_version'] == PARSER_VERSION:
                    return {'name': name, 'status': '已存在，跳过', 'count': len(entry['doc_ids']), 'warnings': entry['warnings']}
            parsed = parse_document(name, data)
            key = name.casefold()
            old = set(sources.get(key, {}).get('doc_ids', []))
            docs = [doc for doc in docs if doc.id not in old] + parsed.documents
            sources[key] = {'name': name, 'hash': digest, 'parser_version': PARSER_VERSION,
                            'doc_ids': [d.id for d in parsed.documents], 'warnings': parsed.warnings}
            self.publish(sources, docs)
            return {'name': name, 'status': '已更新' if old else '已导入', 'count': len(parsed.documents), 'warnings': parsed.warnings}

    def remove(self, key):
        with LOCK:
            state, docs, _ = self.current()
            sources = dict(state['sources'])
            removed = sources.pop(key, None)
            if removed:
                ids = set(removed['doc_ids'])
                self.publish(sources, [d for d in docs if d.id not in ids])
