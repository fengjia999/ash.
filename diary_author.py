"""Diary perspective is stored as a role; names resolve from identity presets."""
import json


def validate_author_role(value):
    if value not in ("user", "assistant"):
        raise ValueError("author_role must be user or assistant")
    return value


def diary_author_role(memory):
    metadata = memory.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    role = metadata.get("author_role") if isinstance(metadata, dict) else None
    role = role or memory.get("author_role")
    return role if role in ("user", "assistant") else "assistant"


def diary_author_fields(memory, identity_presets=None):
    role = diary_author_role(memory)
    parameter = role + "_name"
    name = str((identity_presets or {}).get(parameter) or "").strip()
    return {"author_role": role, "author_name": name or "{{" + parameter + "}}"}
