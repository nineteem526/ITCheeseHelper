"""Retrieval-only evaluation; negative/clarification cases are excluded explicitly."""
import argparse
import csv
import json
from time import perf_counter

from pydantic import TypeAdapter

from .bm25_retriever import BM25Retriever
from .config import load_config
from .ingest import fingerprint, load_documents
from .models import TestQuestion


def metrics(ranked: list[str], expected: list[str]) -> dict:
    relevant = set(expected)
    if not relevant:
        raise ValueError("检索指标要求至少一个相关文档")
    result = {}
    for k in (1, 3):
        hits = len(set(ranked[:k]) & relevant)
        result[f"recall@{k}"] = hits / len(relevant)
        result[f"hit@{k}"] = float(hits > 0)
    result["mrr@10"] = next((1 / rank for rank, doc in enumerate(ranked[:10], 1)
                              if doc in relevant), 0.0)
    return result


def evaluate(docs, retriever, cases):
    known = {doc.id for doc in docs}
    rows = []
    for case in cases:
        if not set(case.expected_doc_ids) <= known:
            raise ValueError(f"测试集包含未知 Document ID：{case.expected_doc_ids}")
        eligible = not case.should_clarify and not case.should_no_answer
        started = perf_counter()
        hits = retriever.retrieve(case.query, 10)
        elapsed = (perf_counter() - started) * 1000
        ranked = [hit.doc_id for hit in hits]
        rows.append({"query": case.query, "expected_doc_ids": case.expected_doc_ids,
                     "expected_intent": case.expected_intent,
                     "should_clarify": case.should_clarify, "should_no_answer": case.should_no_answer,
                     "eligible": eligible, "bm25_top1": ranked[0] if ranked else None,
                     "ranked_doc_ids": ranked, "scores": [hit.bm25_score for hit in hits],
                     "latency_ms": elapsed,
                     **(metrics(ranked, case.expected_doc_ids) if eligible else {})})
    eligible_rows = [row for row in rows if row["eligible"]]
    keys = ("recall@1", "recall@3", "hit@1", "hit@3", "mrr@10")
    summary = {"total": len(rows), "retrieval_sample_count": len(eligible_rows),
               "excluded_count": len(rows) - len(eligible_rows),
               **{key: sum(row[key] for row in eligible_rows) / len(eligible_rows)
                  if eligible_rows else None for key in keys},
               "clarification_accuracy": None, "no_answer_accuracy": None,
               "note": "阶段一未实现澄清和拒答；相关指标未运行，不能视为零分。"}
    return summary, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", choices=["bm25"], default=["bm25"])
    parser.parse_args()
    try:
        cfg = load_config()
        docs = load_documents(cfg)
        cases = TypeAdapter(list[TestQuestion]).validate_json(cfg.test_questions_path.read_text(encoding="utf-8-sig"))
        summary, rows = evaluate(docs, BM25Retriever.load(docs, cfg.index_dir), cases)
        cfg.report_dir.mkdir(parents=True, exist_ok=True)
        report = {"mode": "bm25", "knowledge_fingerprint": fingerprint(docs),
                  "demo_data": any(doc.is_demo for doc in docs), "summary": summary, "details": rows}
        (cfg.report_dir / "bm25.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        columns = list(dict.fromkeys(key for row in rows for key in row)) or ["query"]
        with (cfg.report_dir / "bm25.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                cells = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                         for key, value in row.items()}
                # Prevent spreadsheet formulas in user-authored questions.
                writer.writerow({key: "'" + value if isinstance(value, str) and
                                 value.lstrip().startswith(("=", "+", "-", "@")) else value
                                 for key, value in cells.items()})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"报告：{cfg.report_dir}")
    except (ValueError, OSError) as exc:
        raise SystemExit(f"评测失败：{exc}") from exc


if __name__ == "__main__":
    main()
