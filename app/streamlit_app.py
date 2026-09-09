"""Local document library and evidence-grounded chat UI."""
import os
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from src.config import load_config
from src.library import Library
from src.llm.internal import configured_provider
from src.llm.base import ProviderError
from src.qa_pipeline import ask

st.set_page_config(page_title='IT 知识助手', page_icon='💬', layout='centered')
st.title('IT 知识助手')
st.caption('上传手册，提问并查看有来源的回答。')

library = Library(Path(os.environ.get('LIBRARY_DIR', str(ROOT / 'artifacts/library'))))
try:
    library.initialize(load_config())
    state, docs, retriever = library.current()
except Exception:
    st.error('知识库加载失败，请检查知识文件或索引配置。原数据未被覆盖。')
    st.stop()

st.session_state.setdefault('messages', [])
if st.session_state.get('generation') != state['generation']:
    st.session_state.messages = []
    st.session_state.generation = state['generation']

with st.sidebar:
    if st.button('新对话', use_container_width=True):
        st.session_state.messages = []
    mode = st.radio('回答方式', ['模型问答', '原文检索'])
    debug = st.toggle('调试模式', value=False)
    st.caption('模型问答会向 .env 中配置的接口发送问题、近期会话和检索片段。原文检索不调用模型。')
    st.caption('会话不写入文件。文件解析和索引保存在本机，暂不识别图片文字。')
    if st.button('测试模型连接'):
        try:
            with st.spinner('正在连接…'):
                configured_provider().chat([{'role': 'user', 'content': '你好，请只回复连接成功。'}])
            st.success('模型连接成功。')
        except ProviderError as exc:
            st.error(str(exc))
    st.write(f"{len(state['sources'])} 份资料 · {len(docs)} 个片段")

if st.session_state.get('answer_mode') != mode:
    st.session_state.messages = []
    st.session_state.answer_mode = mode

chat_tab, library_tab = st.tabs(['提问', '知识库'])
with library_tab:
    st.subheader('添加操作手册')
    uploads = st.file_uploader('支持 Word（.docx）、文字版 PDF、TXT、Markdown；每份最多 20 MB',
                               type=['docx', 'pdf', 'txt', 'md'], accept_multiple_files=True)
    st.caption('同名文件重新上传会替换旧版；相同内容自动跳过。无需手工编写 JSON。')
    if st.button('导入所选文件', disabled=not uploads):
        outcomes = []
        for upload in uploads:
            try:
                with st.spinner(f'正在处理 {upload.name}…'):
                    outcomes.append(library.import_file(upload.name, upload.getvalue()))
            except ValueError as exc:
                outcomes.append({'name': upload.name, 'status': '失败', 'warnings': [str(exc)]})
            except Exception:
                outcomes.append({'name': upload.name, 'status': '失败', 'warnings': ['文件解析或索引失败，请检查格式；旧版本仍保留。']})
        st.session_state.import_results = outcomes
        st.rerun()
    for result in st.session_state.get('import_results', []):
        st.write(f"{result['name']}：{result['status']}（{result.get('count', 0)} 个片段）")
        for warning in result.get('warnings', []):
            st.warning(warning)
    st.subheader('已导入资料')
    if not state['sources']:
        st.info('知识库为空，请先上传一份手册。')
    for key, entry in state['sources'].items():
        with st.expander(f"{entry['name']} · {len(entry['doc_ids'])} 个片段"):
            for warning in entry['warnings']:
                st.caption(warning)
            entry_docs = [doc for doc in docs if doc.id in entry['doc_ids']]
            for doc in entry_docs:
                st.write(doc.title)
                st.text(doc.answer)
                st.caption(doc.source)
            if st.button('从知识库移除', key='remove_' + key):
                library.remove(key)
                st.session_state.import_results = []
                st.rerun()


def render(message):
    with st.chat_message(message['role']):
        if message['role'] == 'user':
            st.text(message['content'])
            return
        if message['status'] == 'ERROR':
            st.error(message['content'])
        else:
            if message.get('title'):
                st.subheader(message['title'])
            st.text(message['content'])
        for number, source in enumerate(message.get('sources', []), 1):
            st.caption(f"[{number}] {source['source']}")
        if message.get('sources'):
            st.caption('依据已提取正文；资料中的图片文字可能未包含。')
        if debug:
            with st.expander('检索与引用详情'):
                st.json(message.get('debug', {}))


with chat_tab:
    if mode == '原文检索':
        st.caption('每条问题独立匹配，直接展示最相关原文；不代表资料能回答该问题。')
    if not st.session_state.messages:
        st.info('可以问“如何启动 Hermes Agent”，也可以继续补充问题细节。')
    for message in st.session_state.messages:
        render(message)
    query = st.chat_input('请输入问题，按 Enter 发送', max_chars=4000)
    if query and query.strip():
        user = {'role': 'user', 'content': query.strip()}
        history = [{'role': m['role'], 'content': m['content']} for m in st.session_state.messages
                   if m.get('status') != 'ERROR']
        st.session_state.messages.append(user)
        render(user)
        with st.spinner('正在处理…'):
            try:
                if mode == '模型问答':
                    result = ask(query.strip(), history, docs, retriever, configured_provider())
                else:
                    started = perf_counter()
                    hits = retriever.retrieve(query.strip(), 3)
                    by_id = {d.id: d for d in docs}
                    best = by_id[hits[0].doc_id] if hits else None
                    result = {'status': 'RESULTS' if best else 'NO_MATCH',
                              'title': best.title if best else '',
                              'content': best.answer if best else '没有匹配到相关章节，请换一种问法。',
                              'sources': [{'source': best.source}] if best else [],
                              'debug': {'retrieval': [h.model_dump() for h in hits], 'elapsed_ms': (perf_counter()-started)*1000}}
            except ProviderError as exc:
                result = {'status': 'ERROR', 'content': str(exc), 'sources': []}
            except Exception:
                result = {'status': 'ERROR', 'content': '处理失败，请检查知识库和索引后重试。', 'sources': []}
        message = {'role': 'assistant', **result}
        st.session_state.messages.append(message)
        render(message)
