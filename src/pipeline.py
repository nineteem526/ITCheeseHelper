"""Stage 1 returns search results and original answers, not generated answers."""
import argparse
import json

from .bm25_retriever import BM25Retriever
from .config import load_config
from .ingest import load_documents


def main():
    parser = argparse.ArgumentParser(description="阶段一：BM25 FAQ 检索基线")
    parser.add_argument("--mode", choices=["bm25"], default="bm25")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--debug", action="store_true", help="显示完整 JSON、分数和调试字段")
    args = parser.parse_args()
    try:
        if not args.query.strip():
            raise ValueError("请输入非空问题")
        cfg = load_config()
        docs = load_documents(cfg)
        results = BM25Retriever.load(docs, cfg.index_dir).retrieve(
            args.query, args.top_k if args.top_k is not None else cfg.top_k)
        by_id = {doc.id: doc for doc in docs}
        output = {"mode": "bm25", "status": "RESULTS" if results else "NO_MATCH",
                  "notice": "检索基线；返回知识库内容，不是模型生成答案。请核对来源及文档内的限制说明。",
                  "results": [{**hit.model_dump(), "document": by_id[hit.doc_id].model_dump(mode="json")}
                              for hit in results]}
        if args.debug:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        elif not results:
            print("没有匹配到相关章节，请换一种问法。")
        else:
            best = by_id[results[0].doc_id]
            print(f"问题：{args.query}\n")
            print(f"最相关章节：{best.title}\n")
            print(best.answer)
            print(f"\n来源：{best.source}")
            if len(results) > 1:
                print("\n其他匹配章节（仅供参考）：")
                for hit in results[1:]:
                    print(f"  · {by_id[hit.doc_id].title}")
    except (ValueError, OSError) as exc:
        raise SystemExit(f"查询失败：{exc}") from exc


if __name__ == "__main__":
    main()
