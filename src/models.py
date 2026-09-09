from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FAQ(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    system: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    source: str = Field(min_length=1)
    updated_at: date
    tags: list[str] = Field(default_factory=list)
    is_demo: bool = False

    @field_validator("system", mode="before")
    @classmethod
    def normalize_system(cls, value):
        return [value] if isinstance(value, str) else value

    @field_validator("system", "tags")
    @classmethod
    def clean_items(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("系统名及标签不能留空")
        return list(dict.fromkeys(item.strip() for item in value))


class RetrievalResult(BaseModel):
    doc_id: str
    bm25_rank: int | None = None
    vector_rank: int | None = None
    fusion_rank: int | None = None
    rerank_rank: int | None = None
    bm25_score: float | None = None
    vector_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None


class TestQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    expected_doc_ids: list[str] = Field(default_factory=list)
    expected_intent: str | None = None
    should_clarify: bool = False
    should_no_answer: bool = False

    @model_validator(mode="after")
    def valid_labels(self):
        if self.should_clarify and self.should_no_answer:
            raise ValueError("澄清和无答案标签不能同时为 true")
        if (self.should_clarify or self.should_no_answer) and self.expected_doc_ids:
            raise ValueError("澄清/无答案题不应标注相关文档")
        if not self.should_clarify and not self.should_no_answer and not self.expected_doc_ids:
            raise ValueError("可回答问题必须有相关文档标注")
        return self
