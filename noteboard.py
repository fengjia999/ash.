"""Cover notes: plain saved text, independent of memory recall and summaries."""
import json
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from database import get_pool

router = APIRouter(prefix="/api/noteboard")
TOOLS = [{
    "name": "create_note",
    "description": "Write a short note to the shared Cover note wall. Use for a message the user wants to keep or a deliberate note to them; do not automatically summarize conversations or write on every turn. This saves text only and does not add it to memory recall.",
    "input_schema": {
        "type": "object", "properties": {
            "title": {"type": "string", "maxLength": 80, "description": "Optional short title"},
            "content": {"type": "string", "minLength": 1, "maxLength": 12000},
        }, "required": ["content"], "additionalProperties": False,
    },
}]


class NoteText(BaseModel):
    title: str = Field(default="", max_length=80)
    content: str = Field(min_length=1, max_length=12000)

    @model_validator(mode="after")
    def clean(self):
        self.title = self.title.strip()
        self.content = self.content.strip()
        if not self.content:
            raise ValueError("请输入便签正文")
        return self


class NoteEdit(NoteText):
    revision: int = Field(ge=1)


def public_note(row):
    result = dict(row)
    for key in ("created_at", "updated_at"):
        if hasattr(result.get(key), "isoformat"):
            result[key] = result[key].isoformat()
    return result


async def create_note(text: NoteText, author: Literal["user", "assistant"]):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO cover_notes (title, content, author) VALUES ($1, $2, $3)
            RETURNING *
        """, text.title, text.content, author)
    return public_note(row)


async def dispatch_create_note(arguments):
    try:
        text = NoteText.model_validate(arguments)
    except ValueError:
        return "Error: content must contain 1–12000 characters; title must be at most 80 characters."
    note = await create_note(text, "assistant")
    return json.dumps({"id": note["id"], "title": note["title"], "saved": True}, ensure_ascii=False)


@router.get("")
async def list_notes():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM cover_notes ORDER BY created_at DESC, id DESC")
    return {"notes": [public_note(row) for row in rows]}


@router.post("")
async def add_note(text: NoteText):
    return {"note": await create_note(text, "user")}


@router.put("/{note_id}")
async def edit_note(note_id: int, text: NoteEdit):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE cover_notes SET title=$2, content=$3, revision=revision+1, updated_at=NOW()
            WHERE id=$1 AND revision=$4 RETURNING *
        """, note_id, text.title, text.content, text.revision)
    if not row:
        return JSONResponse(status_code=409, content={"error": "便签已更改或删除，请重新打开后编辑"})
    return {"note": public_note(row)}


@router.delete("/{note_id}")
async def delete_note(note_id: int, revision: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("DELETE FROM cover_notes WHERE id=$1 AND revision=$2 RETURNING id", note_id, revision)
    if not row:
        return JSONResponse(status_code=409, content={"error": "便签已更改或删除，请刷新后重试"})
    return {"deleted": True}
