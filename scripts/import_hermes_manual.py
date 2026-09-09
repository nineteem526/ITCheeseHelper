"""One-off importer for the supplied Hermes v1.0 manual, not a generic DOCX parser."""
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
manual = ROOT / 'data' / '打造个人AI助理！Hermes Agent+Qwen3.6部署教程.docx'
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
with ZipFile(manual) as archive:
    root = ET.fromstring(archive.read('word/document.xml'))
paragraphs = [''.join(t.text or '' for t in p.findall('.//w:t', ns))
              for p in root.findall('.//w:p', ns)]
# Exact section headers avoid importing the table of contents or cover metadata.
sections = [
    ('准备工作(基于Windows平台)', '部署过程', '3 准备工作', '部署 Hermes Agent 需要什么系统、硬件和运行环境？', ['Windows', '硬件', '内存', '环境', 'Qwen3.6']),
    ('WSL2安装', 'WSL2 安装 Ubuntu', '4.1 WSL2安装', '如何安装和启用 WSL2？', ['WSL2', '虚拟化', '安装']),
    ('WSL2 安装 Ubuntu', '安装Hermes Agent', '4.2 WSL2 安装 Ubuntu', '如何在 WSL2 中安装 Ubuntu？', ['WSL2', 'Ubuntu', '安装']),
    ('安装Hermes Agent', '配置Hermes Agent', '4.3 安装Hermes Agent', '如何安装 Hermes Agent？', ['Hermes', '安装', '终端']),
    ('配置Hermes Agent', '启动Hermes Agent', '4.4 配置Hermes Agent', '如何配置 Hermes Agent 模型接口？', ['Hermes', '模型', '配置', 'API']),
    ('启动Hermes Agent', '启用Hermes WebUI', '4.5 启动Hermes Agent', '如何启动 Hermes Agent？', ['Hermes', '启动', 'gateway']),
    ('启用Hermes WebUI', 'Hermes Agent 钉钉接入', '4.6 启用Hermes WebUI', '如何启用 Hermes WebUI 网页界面？', ['Hermes', 'WebUI', '网页', '启动']),
    ('Hermes Agent 钉钉接入', '核心目录结构', '4.7 Hermes Agent 钉钉接入', 'Hermes Agent 如何接入钉钉机器人？', ['Hermes', '钉钉', '机器人', 'Gateway']),
    ('核心目录结构', 'SOUL.md 人格设定（可选）', '5 核心目录结构', 'Hermes Agent 配置文件、记忆和日志放在哪里？', ['Hermes', '目录', '配置文件', '日志', '记忆']),
    ('SOUL.md 人格设定（可选）', '场景落地：解锁高效协作新体验', '6 SOUL.md 人格设定', '如何通过 SOUL.md 设置 Hermes Agent 人格？', ['Hermes', 'SOUL.md', '人格'])
]
docs = []
for number, (start, end, section, question, tags) in enumerate(sections, 1):
    left = paragraphs.index(start)
    right = paragraphs.index(end, left + 1)
    body = '\n'.join(p for p in paragraphs[left + 1:right] if p.strip())
    # Preserve instructions as source text, never execute them. Mask internal endpoint/key values.
    body = re.sub(r'http://10\.10\.185\.28:18372/v1', '<内网模型地址，请向IT团队获取>', body)
    body = re.sub(r'(?i)(api\s*key\s*[:：])\s*EMPTY', r'\1 <按授权配置填写>', body)
    body = body.replace('wsl --list –online', 'wsl --list --online')
    notice = '以下摘自手册正文，未验证命令与版本兼容性；截图中的补充步骤未导入，请结合原手册核对。\n'
    if number == 3:
        notice += '原文命令中的长横线已规范为两个 ASCII 连字符。\n'
    docs.append(dict(id=f'HERMES{number:03}', category='deployment', system=['Hermes Agent'],
                     title=section, question=question, answer=notice + body,
                     source=f'{manual.name}｜v1.0｜{section}', updated_at='2026-05-09',
                     tags=tags, is_demo=False))
(ROOT / 'data/hermes_knowledge.json').write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding='utf-8')
cases = [dict(query=d['question'], expected_doc_ids=[d['id']]) for d in docs]
(ROOT / 'data/hermes_test_questions.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Imported {len(docs)} text sections; original DOCX unchanged; images not imported.')
