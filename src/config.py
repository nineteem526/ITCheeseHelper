"""Resolve project paths consistently, independently of the current directory."""
import os
from pathlib import Path

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_path: Path = Path("data/knowledge.json")
    index_dir: Path = Path("artifacts/bm25")
    test_questions_path: Path = Path("data/test_questions.json")
    report_dir: Path = Path("reports")
    top_k: int = Field(default=10, ge=1)
    max_document_chars: int = Field(default=6000, ge=1)


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.yaml"
    values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    for name in Config.model_fields:
        if env.get(name.upper()) is not None:
            values[name] = env[name.upper()]
    cfg = Config.model_validate(values)
    for name in ("knowledge_path", "index_dir", "test_questions_path", "report_dir"):
        value = getattr(cfg, name)
        if not value.is_absolute():
            setattr(cfg, name, ROOT / value)
    return cfg
