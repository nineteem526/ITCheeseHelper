"""Orchestrate understanding, BM25 candidates and evidence-grounded generation."""
from time import perf_counter
from .query_understanding import understand
from .answer_generator import generate
from .llm.base import ProviderError


def ask(query, history, documents, retriever, provider):
    started = perf_counter()
    times = {}
    if not query.strip() or len(query) > 4000:
        return {'status': 'ERROR', 'content': '请输入 1～4000 字符的问题。', 'sources': [], 'debug': {}}
    try:
        step = perf_counter()
        understanding = understand(provider, query, history)
        times['understanding_ms'] = (perf_counter() - step) * 1000
        debug = {'query_understanding': understanding.model_dump(), 'timings': times}
        if understanding.need_clarification:
            return {'status': 'CLARIFY', 'content': understanding.clarification_question, 'sources': [], 'debug': debug}
        step = perf_counter()
        hits = retriever.retrieve(understanding.standalone_query, 10)
        times['retrieval_ms'] = (perf_counter() - step) * 1000
        by_id = {d.id: d for d in documents}
        # Whole candidate documents only; never silently cut an operation mid-step.
        context, used = [], 0
        for hit in hits:
            doc = by_id[hit.doc_id]
            if used + len(doc.answer) <= 20000:
                context.append(doc)
                used += len(doc.answer)
        step = perf_counter()
        result = generate(provider, understanding.standalone_query, context)
        times['generation_ms'] = (perf_counter() - step) * 1000
        times['total_ms'] = (perf_counter() - started) * 1000
        debug.update({'retrieval': [h.model_dump() for h in hits], 'context_ids': [d.id for d in context],
                      'retrieval_confidence': {'metric': 'bm25', 'top_score': hits[0].bm25_score if hits else None,
                          'is_probability': False, 'evidence_supported': result['status'] == 'ANSWER'},
                      'evidence': result.pop('claims')})
        result['debug'] = debug
        return result
    except ProviderError as exc:
        return {'status': 'ERROR', 'content': str(exc), 'sources': [], 'debug': {'timings': times}}
