"""Shared Chinese tokenization. No network or model downloads."""
import logging
import re
import unicodedata

import jieba

TEXT_VERSION = "faq-fields-v1-jieba-alias-v1"
TOKENIZER = jieba.Tokenizer()
jieba.setLogLevel(logging.WARNING)
for term in ("鲸加", "zmp", "vpn", "teams", "outlook", "密码重置", "新员工"):
    TOKENIZER.add_word(term)


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower().replace("鲸加", "zmp")
    return [token for token in TOKENIZER.cut(text) if re.search(r"[\w]", token)]


def document_text(doc) -> str:
    return "\n".join([" ".join(doc.system), doc.title, doc.question, doc.answer, " ".join(doc.tags)])
