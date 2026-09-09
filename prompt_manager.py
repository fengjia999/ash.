"""
Prompt 热更新管理器（数据库版）

- system_prompt.txt 是种子文件，首次启动写入数据库
- 运行时全部从数据库读写，重部署不丢失
- locked 段只有 manual 能改，editable 段可由主聊天模型通过工具修改
"""

import json
import re
import os
from datetime import datetime

_PROMPT_DIR = os.path.dirname(__file__)
_PRIVATE_PROMPT_FILE = os.path.join(_PROMPT_DIR, "system_prompt.txt")
_EXAMPLE_PROMPT_FILE = os.path.join(_PROMPT_DIR, "system_prompt.example.txt")
PROMPT_FILE = (
    _PRIVATE_PROMPT_FILE
    if os.path.exists(_PRIVATE_PROMPT_FILE)
    else _EXAMPLE_PROMPT_FILE
)
EDIT_LOG_FILE = os.path.join(os.path.dirname(__file__), "prompt_edit_log.jsonl")


# ═══════════════════════════════════════
# 解析种子文件（仅初始化用）
# ═══════════════════════════════════════
def parse_seed_file(filepath=PROMPT_FILE):
    """解析 system_prompt.txt 里的标记段落，返回 dict"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        print(f"[prompt] seed file not found: {filepath}")
        return {}

    pattern = re.compile(
        r'<!--\s*section:(\S+)\s+(locked|editable)(?:\s+priority:(\d+))?\s*-->\n'
        r'(.*?)'
        r'<!--\s*end\s*-->',
        re.DOTALL
    )
    sections = {}
    for m in pattern.finditer(raw):
        key = m.group(1)
        sections[key] = {
            "key": key,
            "mode": m.group(2),
            "priority": int(m.group(3)) if m.group(3) else 50,
            "content": m.group(4).strip(),
        }
    return sections


# ═══════════════════════════════════════
# 种子导入（启动时调用）
# ═══════════════════════════════════════
async def seed_prompt_to_db():
    """
    首次启动 / 新增段落时，把 system_prompt.txt 的内容写入数据库。
    已存在的段落不覆盖（保护运行时修改过的内容）。
    """
    from database import get_pool

    sections = parse_seed_file()
    if not sections:
        print("[prompt] no sections found in seed file")
        return

    pool = await get_pool()
    seeded = 0
    skipped = 0

    async with pool.acquire() as conn:
        for s in sections.values():
            exists = await conn.fetchval(
                "SELECT 1 FROM prompt_sections WHERE section_key = $1",
                s["key"]
            )
            if exists:
                skipped += 1
                continue

            await conn.execute("""
                INSERT INTO prompt_sections (section_key, mode, priority, content, updated_by)
                VALUES ($1, $2, $3, $4, 'seed')
            """, s["key"], s["mode"], s["priority"], s["content"])
            seeded += 1
            print(f"[prompt] seeded: {s['key']} ({s['mode']}, P{s['priority']})")

    print(f"[prompt] seed done: {seeded} new, {skipped} existing")


# ═══════════════════════════════════════
# 重新种子（手动强制覆盖用）
# ═══════════════════════════════════════
async def reseed_section(section_key: str):
    """
    强制用 system_prompt.txt 里的内容覆盖数据库中某个段落。
    用于：你改了 txt 文件，想让某段同步到数据库。
    """
    from database import get_pool

    sections = parse_seed_file()
    if section_key not in sections:
        return {"error": f"'{section_key}' not found in seed file"}

    s = sections[section_key]
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO prompt_sections (section_key, mode, priority, content, updated_by)
            VALUES ($1, $2, $3, $4, 'reseed')
            ON CONFLICT (section_key) DO UPDATE
            SET mode = $2, priority = $3, content = $4, updated_at = NOW(), updated_by = 'reseed'
        """, s["key"], s["mode"], s["priority"], s["content"])

    return {"ok": True, "section": section_key, "chars": len(s["content"])}


# ═══════════════════════════════════════
# 读取
# ═══════════════════════════════════════
async def get_all_sections() -> list:
    from database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT section_key, mode, priority, content, updated_at, updated_by "
            "FROM prompt_sections ORDER BY priority DESC"
        )
    return [
        {
            "key": r["section_key"],
            "mode": r["mode"],
            "priority": r["priority"],
            "content": r["content"],
            "updated_at": r["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if r["updated_at"] else "",
            "updated_by": r["updated_by"] or "",
        }
        for r in rows
    ]


async def build_system_prompt(
    exclude_sections: list[str] | None = None,
    include_sections: list[str] | None = None,
) -> str:
    """组装 system prompt，按 priority 降序拼接，可按 section key 过滤"""
    sections = await get_all_sections()
    exclude = set(exclude_sections or [])
    include = set(include_sections or []) if include_sections is not None else None
    sections = [
        s for s in sections
        if s["key"] not in exclude and (include is None or s["key"] in include)
    ]
    parts = [s["content"] for s in sections if s["content"]]
    return "\n\n".join(parts)


async def read_section(section_key: str) -> dict | list:
    """
    读取某段 prompt 详情。
    传 'list' 返回所有段落概览。
    """
    if section_key == "list":
        sections = await get_all_sections()
        return [
            {
                "key": s["key"],
                "mode": s["mode"],
                "priority": s["priority"],
                "chars": len(s["content"]),
                "updated_by": s["updated_by"],
            }
            for s in sections
        ]

    from database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT section_key, mode, priority, content, updated_at, updated_by "
            "FROM prompt_sections WHERE section_key = $1",
            section_key
        )

    if not row:
        sections = await get_all_sections()
        return {
            "error": f"'{section_key}' not found",
            "available": [s["key"] for s in sections],
        }

    return {
        "key": row["section_key"],
        "mode": row["mode"],
        "priority": row["priority"],
        "content": row["content"],
        "char_count": len(row["content"]),
        "updated_at": row["updated_at"].strftime("%Y-%m-%d %H:%M:%S") if row["updated_at"] else "",
        "updated_by": row["updated_by"] or "",
    }


# ═══════════════════════════════════════
# 更新
# ═══════════════════════════════════════
async def update_section(section_key: str, new_content: str,
                         reason: str = "", edited_by: str = "assistant") -> dict:
    """
    更新某段 prompt 内容。
    - locked 段只有 edited_by='manual' 时才能改
    - editable 段谁都能改
    - 每次修改自动记日志
    """
    from database import get_pool
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT mode, content FROM prompt_sections WHERE section_key = $1",
            section_key
        )

    if not row:
        sections = await get_all_sections()
        return {
            "error": f"'{section_key}' not found",
            "available": [s["key"] for s in sections],
        }

    # locked 段只有手动编辑能改
    if row["mode"] == "locked" and edited_by != "manual":
        return {"error": f"'{section_key}' is locked — only manual edit allowed"}

    old_content = row["content"]

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE prompt_sections
            SET content = $1, updated_at = NOW(), updated_by = $2
            WHERE section_key = $3
        """, new_content, edited_by, section_key)

    # 写日志
    _log_edit(section_key, old_content, new_content, reason, edited_by)

    return {
        "ok": True,
        "section": section_key,
        "edited_by": edited_by,
        "reason": reason,
        "old_char_count": len(old_content),
        "new_char_count": len(new_content),
    }


# ═══════════════════════════════════════
# 修改日志（jsonl 文件）
# ═══════════════════════════════════════
def _log_edit(section_key, old_content, new_content, reason, edited_by):
    log_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "section": section_key,
        "edited_by": edited_by,
        "reason": reason,
        "old": old_content[:300],
        "new": new_content[:300],
    }
    try:
        with open(EDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[prompt-log] write failed: {e}")
