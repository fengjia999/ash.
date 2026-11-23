"""Immutable request-side recall snapshots, excluded from model history."""
from contextvars import ContextVar
from xml.etree import ElementTree

import database as db

active = ContextVar('recall_audit', default=None)
retrieval_query = ContextVar('recall_audit_query', default='')


async def init_tables():
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS recall_injection_audits (
            user_message_id INTEGER PRIMARY KEY REFERENCES context_messages(id) ON DELETE CASCADE,
            query TEXT NOT NULL, injection TEXT NOT NULL)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS recall_injection_messages (
            message_id INTEGER PRIMARY KEY REFERENCES context_messages(id) ON DELETE CASCADE,
            user_message_id INTEGER NOT NULL REFERENCES recall_injection_audits(user_message_id) ON DELETE CASCADE)''')


async def capture(conv_id, user_message_id, query, injection):
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''INSERT INTO recall_injection_audits VALUES ($1,$2,$3)
            ON CONFLICT (user_message_id) DO NOTHING''', user_message_id, query, injection)
        await conn.execute('''INSERT INTO recall_injection_messages VALUES ($1,$1)
            ON CONFLICT DO NOTHING''', user_message_id)
    active.set((conv_id, user_message_id))


async def link(conv_id, message_id):
    state = active.get()
    if not state or state[0] != conv_id:
        return
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''INSERT INTO recall_injection_messages VALUES ($1,$2)
            ON CONFLICT DO NOTHING''', message_id, state[1])


def excerpts(injection):
    if not injection:
        return []
    # Only the gateway-generated XML is parsed, never model output.
    root = ElementTree.fromstring('<audit>' + injection + '</audit>')
    return [{'turn_id': int(turn.attrib['turn_id']),
             'conversation_id': int(turn.attrib['conversation_id']),
             'messages': [{'role': m.attrib.get('role'), 'date': m.attrib.get('date'),
                           'text': m.text or ''} for m in turn.findall('message')]}
            for turn in root.iter('past_turn')]


async def read(message_id):
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('''SELECT a.query,a.injection FROM recall_injection_messages l
            JOIN recall_injection_audits a USING(user_message_id)
            JOIN context_messages m ON m.id=l.message_id
            WHERE l.message_id=$1 AND m.hidden=FALSE''', message_id)
    return ({'recorded': True, 'query': row['query'], 'injection': row['injection'],
             'fragments': [n.text for n in ElementTree.fromstring(row['injection']).findall('fragment')]
             if row['injection'].startswith('<memories>') else [], 'results': excerpts(row['injection'])} if row else {'recorded': False, 'results': []})
