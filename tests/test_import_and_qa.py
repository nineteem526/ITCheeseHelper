"""Integration checks for imports, publication, grounded responses and transport errors."""
import io
import json
from pathlib import Path

import httpx
import pytest
from docx import Document
from pypdf import PdfWriter

from src.document_import import parse_document
from src.library import Library
from src.llm.base import LLMProvider, ProviderError
from src.llm.internal import InternalLLMProvider
from src.answer_generator import generate
from src.qa_pipeline import ask
from src.models import FAQ


def sample():
    return FAQ(id='A', category='manual', system=['demo'], title='启动', question='如何启动',
               answer='先进入目录，再运行 demo start。', source='manual.txt｜启动', updated_at='2026-09-09')


class Fake(LLMProvider):
    def __init__(self, values):
        self.values = iter(values)
        self.requests = []
    def chat(self, messages):
        self.requests.append(messages)
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value


def answer():
    return {'status': 'ANSWER', 'claims': [{'text': '运行 demo start。', 'doc_id': 'A', 'quote': '运行 demo start。'}]}


def test_docx_heading_table_and_media_warning():
    document = Document()
    document.add_heading('安装', 1)
    document.add_paragraph('第一步安装软件。')
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = '参数'
    table.cell(0, 1).text = '值'
    data = io.BytesIO()
    document.save(data)
    parsed = parse_document('手册.docx', data.getvalue())
    assert parsed.documents[0].title == '安装'
    assert '第一步' in parsed.documents[0].answer
    assert '参数 | 值' in parsed.documents[0].answer
    assert '正文块' in parsed.documents[0].source


def test_plain_text_long_content_preserved_and_redacted():
    text = '甲' * 4000 + '\nAPI_KEY=super-secret\nhttp://10.1.2.3:80/v1'
    parsed = parse_document('manual.txt', text.encode())
    merged = ''.join(d.answer for d in parsed.documents)
    assert merged.count('甲') == 4000
    assert 'super-secret' not in merged and '10.1.2.3' not in merged
    assert parsed.warnings


def test_scan_pdf_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(ValueError, match='正文'):
        parse_document('scan.pdf', data.getvalue())


def test_mixed_pdf_keeps_text_and_warns_empty_page():
    # A minimal text page with a standard font, plus an empty second page.
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 10 200 Td (Start the demo service) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_blank_page(width=300, height=300)
    data = io.BytesIO(); writer.write(data)
    parsed = parse_document('mixed.pdf', data.getvalue())
    assert 'Start the demo service' in parsed.documents[0].answer
    assert '第 1 页' in parsed.documents[0].source
    assert any('第 2 页' in w for w in parsed.warnings)


def test_library_duplicate_replace_remove_and_failure(tmp_path, monkeypatch):
    library = Library(tmp_path)
    first = library.import_file('demo.md', '# 安装\n安装软件'.encode())
    assert first['status'] == '已导入'
    generation = library.current()[0]['generation']
    assert library.import_file('copy.md', '# 安装\n安装软件'.encode())['status'] == '已存在，跳过'
    assert library.current()[0]['generation'] == generation
    library.import_file('demo.md', '# 启动\n启动软件'.encode())
    assert len(library.current()[1]) == 1
    assert '启动' in library.current()[1][0].answer
    from src.bm25_retriever import BM25Retriever
    original = BM25Retriever.build
    monkeypatch.setattr(BM25Retriever, 'build', lambda *a, **k: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError): library.import_file('demo.md', b'new version')
    assert '启动' in library.current()[1][0].answer
    monkeypatch.setattr(BM25Retriever, 'build', original)
    library.remove('demo.md')
    assert library.current()[1] == []


def test_upload_names_cannot_escape_root(tmp_path):
    library = Library(tmp_path / 'library')
    library.import_file('../../outside.txt', b'hello world')
    assert 'outside.txt' in library.current()[0]['sources']
    assert not (tmp_path / 'outside.txt').exists()


def test_answer_citations_repair_and_no_answer():
    bad = answer(); bad['claims'][0]['doc_id'] = 'invented'
    result = generate(Fake([bad, answer()]), '如何启动', [sample()])
    assert result['status'] == 'ANSWER' and result['sources'][0]['id'] == 'A'
    with pytest.raises(ProviderError): generate(Fake([bad, bad]), '如何启动', [sample()])
    result = generate(Fake([{'status': 'NO_ANSWER', 'claims': []}]), '启动失败怎么办', [sample()])
    assert result['status'] == 'NO_ANSWER' and not result['sources']


def test_fabricated_quote_rejected():
    bad = answer(); bad['claims'][0]['quote'] = '这是不存在的操作步骤'
    with pytest.raises(ProviderError): generate(Fake([bad, bad]), 'q', [sample()])


def test_clarification_does_not_retrieve():
    class NoRetrieval:
        def retrieve(self, *a): raise AssertionError('should not retrieve')
    result = ask('密码', [], [], NoRetrieval(), Fake([{'standalone_query': '密码', 'need_clarification': True, 'clarification_question': '哪个系统的密码？'}]))
    assert result['status'] == 'CLARIFY'


def test_followup_history_and_error_separation():
    from src.models import RetrievalResult
    class Retriever:
        def retrieve(self, query, top_k):
            assert query == '如何启动 demo'
            return [RetrievalResult(doc_id='A', bm25_score=1)]
    fake = Fake([{'standalone_query':'如何启动 demo','need_clarification':False}, answer()])
    result = ask('怎么启动', [{'role':'user','content':'我用 demo'}], [sample()], Retriever(), fake)
    assert result['status'] == 'ANSWER'
    assert '我用 demo' in fake.requests[0][1]['content']
    result = ask('q', [], [], Retriever(), Fake([ProviderError('超时')]))
    assert result['status'] == 'ERROR'


def test_structure_validation_and_transport_redaction():
    from src.query_understanding import Understanding
    with pytest.raises(ProviderError):
        Fake(['not-json', 'still-not-json']).structured_output([], Understanding)
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text='private-response-secret'))
    provider = InternalLLMProvider('https://example.test/v1', 'private-key', 'model', transport=transport)
    with pytest.raises(ProviderError) as exc: provider.chat([])
    assert 'private' not in str(exc.value) and '认证' in str(exc.value)
    good = httpx.MockTransport(lambda request: httpx.Response(200, json={'choices':[{'message':{'content':'ok'}}]}))
    assert InternalLLMProvider('https://example.test/v1', 'k', 'm', transport=good).chat([]) == 'ok'
