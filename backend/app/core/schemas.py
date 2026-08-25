from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    applicant = "applicant"   # по умолчанию (гость, без входа)
    staff = "staff"           # после входа на фронте (фейк-логин, пароль не уходит)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    role: Role = Role.applicant
    session_id: str = Field(default="", max_length=64)
    max_rows: int = Field(default=50, ge=1, le=1000)
    explain: bool = True


class ResultBlock(BaseModel):
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    truncated: bool = False
    warning: Optional[str] = None
    suggested_filters: Optional[list[dict[str, str]]] = None


class ExplanationBlock(BaseModel):
    tables: list[str] = []
    joins: list[str] = []
    filters: list[str] = []
    aggregates: list[str] = []
    constraints: list[str] = []


class Meta(BaseModel):
    latency_ms: int = 0
    query_id: str = ""
    judge: Optional[dict] = None


class ErrorBlock(BaseModel):
    code: str
    message: str


class ChatResponse(BaseModel):
    status: Literal["success", "error"]
    text: str = ""
    sql: str = ""
    result: ResultBlock = ResultBlock()
    explanation: ExplanationBlock = ExplanationBlock()
    meta: Meta = Meta()
    error: Optional[ErrorBlock] = None


class HealthResponse(BaseModel):
    status: Literal["ok", "error"]
    database: bool = False
