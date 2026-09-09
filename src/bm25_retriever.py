import importlib.metadata
import json
from pathlib import Path

import bm25s

from .ingest import fingerprint
from .models import FAQ, RetrievalResult
from .text import TEXT_VERSION, document_text, tokenize


def metadata(docs):
    return {"fingerprint": fingerprint(docs), "text_version": TEXT_VERSION,
            "bm25s_version": importlib.metadata.version("bm25s"),
            "jieba_version": importlib.metadata.version("jieba"),
            "doc_ids": [doc.id for doc in docs]}


class BM25Retriever:
    def __init__(self, docs, engine):
        self.docs = docs
        self.engine = engine

    @classmethod
    def build(cls, docs: list[FAQ], directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / "manifest.json"
        marker.unlink(missing_ok=True)
        engine = None
        if docs:
            engine = bm25s.BM25(method="lucene")
            engine.index([tokenize(document_text(doc)) for doc in docs], show_progress=False)
            engine.save(str(directory))
        marker.write_text(json.dumps(metadata(docs), ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(docs, engine)

    @classmethod
    def load(cls, docs: list[FAQ], directory: Path):
        marker = directory / "manifest.json"
        if not marker.exists():
            raise ValueError("索引不存在，请运行 python -m src.ingest")
        if json.loads(marker.read_text(encoding="utf-8")) != metadata(docs):
            raise ValueError("索引已过期，请重新运行 python -m src.ingest")
        engine = bm25s.BM25.load(str(directory), load_corpus=False) if docs else None
        return cls(docs, engine)

    def retrieve(self, query: str, top_k: int = 10) -> list[RetrievalResult]:
        if top_k < 1:
            raise ValueError("top_k 必须为正整数")
        tokens = tokenize(query)
        if not self.engine or not tokens:
            return []
        # Score all documents: this tiny KB permits deterministic ID tie-breaking.
        scores = self.engine.get_scores(tokens)
        ranked = sorted(((doc.id, float(score)) for doc, score in zip(self.docs, scores)
                         if score > 0), key=lambda item: (-item[1], item[0]))[:top_k]
        return [RetrievalResult(doc_id=doc_id, bm25_rank=rank, bm25_score=score)
                for rank, (doc_id, score) in enumerate(ranked, 1)]
