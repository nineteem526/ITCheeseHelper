import json

import pytest
from pydantic import ValidationError

from src.bm25_retriever import BM25Retriever
from src.config import Config, ROOT, load_config
from src.evaluation import evaluate, metrics
from src.ingest import load_documents
from src.models import TestQuestion as Question
from src.text import tokenize


@pytest.fixture
def docs():
    return load_documents(Config(knowledge_path=ROOT / "data/knowledge.json"))


@pytest.fixture
def retriever(docs, tmp_path):
    BM25Retriever.build(docs, tmp_path)
    return BM25Retriever.load(docs, tmp_path)


def test_aliases_share_tokens():
    assert tokenize("鲸加 密码") == tokenize("ZMP 密码")


@pytest.mark.parametrize("query,expected", [
    ("Teams 账号锁定", "KB009"), ("Outlook E-DEMO-401", "KB007"),
    ("新员工 修改用户密码失败", "KB002"), ("VPN 密码过期", "KB011")])
def test_product_error_retrieval(retriever, query, expected):
    assert retriever.retrieve(query)[0].doc_id == expected


def test_zero_match_and_empty_query(retriever):
    assert retriever.retrieve("zzzxxyy987654") == []
    assert retriever.retrieve("   !!!") == []
    with pytest.raises(ValueError):
        retriever.retrieve("VPN", 0)


def test_empty_kb(tmp_path):
    BM25Retriever.build([], tmp_path)
    assert BM25Retriever.load([], tmp_path).retrieve("密码") == []


def test_stale_index(docs, tmp_path):
    BM25Retriever.build(docs, tmp_path)
    changed = [doc.model_copy(deep=True) for doc in docs]
    changed[0].answer = "changed"
    with pytest.raises(ValueError, match="过期"):
        BM25Retriever.load(changed, tmp_path)


def test_missing_index(docs, tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        BM25Retriever.load(docs, tmp_path)


@pytest.mark.parametrize("change", ["duplicate", "empty_answer", "empty_system", "long"])
def test_invalid_kb(docs, tmp_path, change):
    raw = [doc.model_dump(mode="json") for doc in docs]
    if change == "duplicate":
        raw.append(raw[0])
    elif change == "empty_answer":
        raw[0]["answer"] = "  "
    elif change == "empty_system":
        raw[0]["system"] = [" "]
    else:
        raw[0]["answer"] = "长" * 6001
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises((ValueError, ValidationError)):
        load_documents(Config(knowledge_path=path))


def test_hand_calculated_metrics():
    actual = metrics(["noise", "a", "other", "b"], ["a", "b"])
    assert actual == {"recall@1": 0, "hit@1": 0, "recall@3": 0.5, "hit@3": 1, "mrr@10": 0.5}
    assert metrics(["none"], ["a"])["mrr@10"] == 0
    assert metrics(["a", "a"], ["a", "b"])["recall@3"] == 0.5


def test_excludes_negative_and_clarification(docs, retriever):
    cases = [Question(query="VPN 密码过期", expected_doc_ids=["KB011"]),
             Question(query="密码", should_clarify=True),
             Question(query="WiFi", should_no_answer=True)]
    summary, rows = evaluate(docs, retriever, cases)
    assert summary["retrieval_sample_count"] == 1
    assert summary["excluded_count"] == 2
    assert summary["recall@1"] == 1
    assert summary["clarification_accuracy"] is None
    assert "recall@1" not in rows[1]


def test_unknown_labels_fail(docs, retriever):
    with pytest.raises(ValueError, match="未知"):
        evaluate(docs, retriever, [Question(query="x", expected_doc_ids=["missing"])])


def test_no_eligible_cases(docs, retriever):
    summary, _ = evaluate(docs, retriever, [Question(query="密码", should_clarify=True)])
    assert summary["recall@1"] is None


def test_environment_override(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("top_k: 2\n", encoding="utf-8")
    monkeypatch.setenv("TOP_K", "7")
    assert load_config(path).top_k == 7


def test_stable_tie_break(docs, tmp_path):
    a = docs[0].model_copy(update={"id": "A"})
    b = docs[0].model_copy(update={"id": "B"})
    engine = BM25Retriever.build([b, a], tmp_path)
    assert [hit.doc_id for hit in engine.retrieve("ZMP")] == ["A", "B"]
