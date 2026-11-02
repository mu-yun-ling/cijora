"""Validation shared by HTTP endpoints and model-generated drafts."""
from typing import List, Optional
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, field_validator


class AgentDraft(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    tagline: str = Field(default="", max_length=160)
    instructions: str = Field(min_length=1, max_length=16000)
    greeting: str = Field(default="", max_length=1200)
    starters: List[str] = Field(default_factory=list, max_length=4)
    color: str = Field(default="#7165d6", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name", "instructions")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()

    @field_validator("starters")
    @classmethod
    def short_starters(cls, value):
        if any(len(item) > 120 for item in value):
            raise ValueError("开场建议请控制在120字以内")
        return [item.strip() for item in value if item.strip()]


class ModelSettings(BaseModel):
    provider: str = Field(default="custom", max_length=40)
    base_url: str = Field(default="", max_length=2000)
    model: str = Field(default="", max_length=180)
    temperature: float = Field(default=0.7, ge=0, le=2)
    chat_thinking: bool = False
    max_tokens: int = Field(default=2048, ge=128, le=16384)
    auto_diary: bool = True
    offset_minutes: int = Field(default=480, ge=-720, le=840)
    api_key: Optional[str] = Field(default=None, max_length=4096)
    clear_api_key: bool = False

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value):
        value = value.strip().rstrip("/")
        if not value:
            return value
        if value.endswith("/chat/completions"):
            value = value[:-17].rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("请输入不含账号、查询参数的 HTTP 或 HTTPS 接口地址")
        return value


class DiaryDraft(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=400)
    content: str = Field(min_length=1, max_length=16000)
    tags: List[str] = Field(default_factory=list, max_length=6)

    @field_validator("tags")
    @classmethod
    def short_tags(cls, value):
        return [tag.strip()[:20] for tag in value if tag.strip()]


class DiaryMemoryDraft(DiaryDraft):
    title: str = Field(min_length=1, max_length=32)
    summary: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=240)
    source_indices: List[int] = Field(min_length=1, max_length=128)


class DiaryNote(BaseModel):
    note: str = Field(min_length=1, max_length=1600)
    source_indices: List[int] = Field(min_length=1, max_length=32)


class DiaryNotes(BaseModel):
    notes: List[DiaryNote] = Field(default_factory=list, max_length=20)
