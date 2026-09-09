"""Local document extraction, heading-aware chunks, and explicit coverage warnings."""
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath
from zipfile import ZipFile

from docx import Document
from docx.table import Table
from docx.oxml.ns import qn
from pypdf import PdfReader
from .models import FAQ

PARSER_VERSION = 'manual-v1'
MAX_BYTES = 20 * 1024 * 1024
CHUNK_CHARS = 1800


@dataclass
class Parsed:
    documents: list[FAQ]
    warnings: list[str]


def redact(text):
    # Minimize accidental indexing of explicitly labelled credentials/internal IP endpoints.
    text = re.sub(r'(?im)((?:api[_ ]?key|appsecret|access[_ ]?token|authorization)\s*[:：=]\s*)[^\n]+', r'\1[已隐藏凭据]', text)
    return re.sub(r'https?://(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)(?::\d+)?[^\s<>]*', '[已隐藏内网地址]', text)


def parse_document(name: str, data: bytes) -> Parsed:
    name = name.replace('\\', '/').rsplit('/', 1)[-1]
    if not name or len(name) > 180:
        raise ValueError('文件名为空或过长。')
    if not data or len(data) > MAX_BYTES:
        raise ValueError('文件为空或超过 20 MB 限制。')
    suffix = PurePath(name).suffix.lower()
    blocks = []  # (heading, source locator, text)
    warnings = []
    heading = PurePath(name).stem
    if suffix == '.docx':
        with ZipFile(io.BytesIO(data)) as archive:
            if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Word 解压后超过 100 MB 限制。')
            image_count = sum(n.startswith('word/media/') for n in archive.namelist())
        doc = Document(io.BytesIO(data))
        if image_count:
            warnings.append(f'包含 {image_count} 个嵌入媒体，图片文字未识别；请核对原手册中的截图。')
        if doc.element.xpath('.//w:txbxContent'):
            warnings.append('包含文本框，文本框内容尚未解析。')
        for number, block in enumerate(doc.iter_inner_content(), 1):
            if isinstance(block, Table):
                text = '\n'.join(' | '.join(dict.fromkeys(c.text for c in row.cells)) for row in block.rows)
                blocks.append((heading, f'正文块 {number}（表格）', text))
                continue
            text = block.text.strip()
            if not text:
                continue
            style = block.style.name.lower() if block.style else ''
            if style.startswith('toc') or style.startswith('目录'):
                continue
            outline = block._p.find('.//' + qn('w:outlineLvl'))
            style_outline = block.style.element.find('.//' + qn('w:outlineLvl')) if block.style else None
            if ('heading' in style or '标题' in style or
                (outline is not None and outline.get(qn('w:val')) != '9') or
                (style_outline is not None and style_outline.get(qn('w:val')) != '9')):
                heading = text
            blocks.append((heading, f'正文块 {number}', text))
    elif suffix == '.pdf':
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError('暂不支持加密 PDF，请使用允许导出的未加密副本。')
        if len(reader.pages) > 300:
            raise ValueError('PDF 超过 300 页，请按章节拆分后上传。')
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ''
            if not text.strip():
                warnings.append(f'第 {number} 页没有可提取正文，可能是扫描页或空白页，未导入。')
            else:
                blocks.append((f'{heading} · 第 {number} 页', f'第 {number} 页', text))
        warnings.append('PDF 按页提取正文；图片未识别，复杂表格和多栏阅读顺序需核对。')
    elif suffix in ('.txt', '.md'):
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:
                text = data.decode('gb18030')
                warnings.append('文件按 GB18030 编码读取，请预览确认文字。')
            except UnicodeDecodeError:
                raise ValueError('无法识别文本编码，请另存为 UTF-8。') from None
        for number, line in enumerate(text.splitlines(), 1):
            if suffix == '.md' and re.match(r'^#{1,6}\s+', line):
                heading = re.sub(r'^#{1,6}\s+', '', line).strip()
            if line.strip():
                blocks.append((heading, f'行 {number}', line))
    else:
        raise ValueError('仅支持 .docx、文字版 .pdf、.txt、.md；旧版 .doc 请另存为 .docx。')
    if not blocks:
        raise ValueError('没有提取到正文，可能只有扫描图片；本版不含 OCR。')
    if sum(len(b[2]) for b in blocks) > 500_000:
        raise ValueError('正文超过 50 万字符，请拆分文件。')
    chunks = []
    current, locations, current_heading = [], [], None
    def flush():
        nonlocal current, locations
        if current:
            chunks.append((current_heading, locations[0], locations[-1], '\n'.join(current)))
        current, locations = [], []
    for title, locator, text in blocks:
        clean = redact(text)
        if clean != text and '已自动隐藏明确标注的凭据或内网 IP 地址，请预览核对。' not in warnings:
            warnings.append('已自动隐藏明确标注的凭据或内网 IP 地址，请预览核对。')
        if len(clean) > CHUNK_CHARS:
            warnings.append(f'{locator} 过长，已拆成多个片段；完整步骤请核对原文。')
        # Never silently truncate long paragraphs/tables; retain every character.
        for offset in range(0, len(clean), CHUNK_CHARS):
            piece = clean[offset:offset + CHUNK_CHARS]
            if title != current_heading or sum(len(x) + 1 for x in current) + len(piece) > CHUNK_CHARS:
                flush()
            current_heading = title
            current.append(piece)
            locations.append(locator)
    flush()
    doc_hash = hashlib.sha256(data).hexdigest()[:12]
    name_hash = hashlib.sha256(name.casefold().encode()).hexdigest()[:8]
    documents = []
    for number, (title, first, last, content) in enumerate(chunks, 1):
        location = first if first == last else f'{first} 至 {last}'
        documents.append(FAQ(id=f'DOC-{name_hash}-{doc_hash}-{number:03}', category='manual',
                            system=[PurePath(name).stem], title=title, question=title,
                            answer=content, source=f'{name}｜{title}｜{location}',
                            updated_at=date.today(), tags=[title], is_demo=False))
    return Parsed(documents, list(dict.fromkeys(warnings)))
