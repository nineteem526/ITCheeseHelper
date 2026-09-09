"""Validate the whole KB before creating an index."""
import hashlib
import json

from pydantic import TypeAdapter

from .config import Config, load_config
from .models import FAQ
from .text import document_text


def load_documents(cfg: Config) -> list[FAQ]:
    docs = TypeAdapter(list[FAQ]).validate_json(cfg.knowledge_path.read_text(encoding="utf-8-sig"))
    ids = [doc.id for doc in docs]
    if len(ids) != len(set(ids)):
        raise ValueError("知识库包含重复 Document ID")
    for doc in docs:
        if len(document_text(doc)) > cfg.max_document_chars:
            raise ValueError(f"{doc.id} 超过长度限制，请人工精简或拆分；不会静默截断")
    return sorted(docs, key=lambda doc: doc.id)


def fingerprint(docs: list[FAQ]) -> str:
    payload = json.dumps([doc.model_dump(mode="json") for doc in docs], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main():
    from .bm25_retriever import BM25Retriever
    cfg = load_config()
    try:
        docs = load_documents(cfg)
        BM25Retriever.build(docs, cfg.index_dir)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"导入失败：{exc}") from exc
    print(f"已校验并索引 {len(docs)} 条 FAQ；路径：{cfg.index_dir}")
    if any(doc.is_demo for doc in docs):
        print("注意：包含虚构演示数据，不代表真实企业流程。")


if __name__ == "__main__":
    main()
