from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_chat_history_and_reset(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('KNOWLEDGE_PATH', str(root / 'data/hermes_knowledge.json'))
    from src.config import Config
    from src.ingest import load_documents
    from src.bm25_retriever import BM25Retriever
    BM25Retriever.build(load_documents(Config(knowledge_path=root / 'data/hermes_knowledge.json')), tmp_path)
    monkeypatch.setenv('INDEX_DIR', str(tmp_path))
    monkeypatch.setenv('LIBRARY_DIR', str(tmp_path / 'library'))
    at = AppTest.from_file(str(root / 'app/streamlit_app.py'), default_timeout=15).run()
    assert not at.exception
    at.sidebar.radio[0].set_value('原文检索').run()
    at.chat_input[0].set_value('如何启动 Hermes Agent').run()
    assert not at.exception
    assert len(at.chat_message) == 2
    assert any('4.5' in item.value for item in at.subheader)
    at.chat_input[0].set_value('如何接入钉钉').run()
    assert len(at.chat_message) == 4
    at.sidebar.button[0].click().run()
    assert len(at.chat_message) == 0
    assert not at.exception

def test_model_ui_answer_and_no_answer(monkeypatch, tmp_path):
    import json
    from src import llm
    from src.llm import internal
    from src.models import FAQ
    from src.llm.base import LLMProvider
    class FakeProvider(LLMProvider):
        def __init__(self): self.n = 0
        def chat(self, messages):
            self.n += 1
            if self.n in (1, 3):
                return json.dumps({'standalone_query':'demo 启动', 'need_clarification':False})
            if self.n == 2:
                return json.dumps({'status':'ANSWER','claims':[{'text':'运行 demo start。','doc_id':'A','quote':'运行 demo start。'}]},ensure_ascii=False)
            return json.dumps({'status':'NO_ANSWER','claims':[]})
    provider=FakeProvider()
    monkeypatch.setattr(internal, 'configured_provider', lambda: provider)
    knowledge=tmp_path/'knowledge.json'
    doc=FAQ(id='A',category='manual',system=['demo'],title='demo 启动',question='demo 启动',answer='运行 demo start。',source='demo.txt',updated_at='2026-09-09')
    knowledge.write_text(json.dumps([doc.model_dump(mode='json')]),encoding='utf-8')
    monkeypatch.setenv('KNOWLEDGE_PATH',str(knowledge))
    monkeypatch.setenv('LIBRARY_DIR',str(tmp_path/'library'))
    root=Path(__file__).resolve().parents[1]
    at=AppTest.from_file(str(root/'app/streamlit_app.py'),default_timeout=15).run()
    at.chat_input[0].set_value('demo 怎么启动').run()
    assert not at.exception
    assert any('运行 demo start。 [1]' in t.value for t in at.text)
    at.chat_input[0].set_value('启动失败呢').run()
    assert any('没有找到足够的信息' in t.value for t in at.text)
    assert len(at.chat_message)==4
