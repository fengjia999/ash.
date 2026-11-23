/* PGLITE_MODULE=/path/to/@electric-sql/pglite node tests/memory_retrieval.postgres.cjs
 * Executes the production SQL in an isolated PostgreSQL WASM engine, no live DB.
 */
const {PGlite}=require(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'memory_retrieval.py'),'utf8');
const statements=[...source.matchAll(/r?"""([\s\S]*?)"""/g)].map(match=>match[1]);
const sql={init_index:statements.filter(s=>s.trim().startsWith('CREATE')),lexical_search:statements};
(async()=>{
 const db=new PGlite();
 try{
  await db.waitReady;
  console.log('PostgreSQL test engine ready.');
  await db.exec(`CREATE TABLE context_messages(id integer primary key, conversation_id integer,
   role text, content text, content_json jsonb, created_at timestamptz default now(),
   hidden boolean default false, kind text default 'chat');`);
  // PGlite is single-process: validate index SQL without PostgreSQL's separate
  // concurrent-build scheduling, which requires a full server.
  for(const statement of sql.init_index)await db.exec(statement.replace('INDEX CONCURRENTLY', 'INDEX'));
  console.log('Search function and GIN index created.');
  const tokens=await db.query('SELECT ash_memory_terms($1) terms',['海边旅行 OpenAI GPT5']);
  assert.deepEqual(tokens.rows[0].terms.sort(),['海边','边旅','旅行','openai','gpt5'].sort());
  await db.exec(`INSERT INTO context_messages(id,conversation_id,role,content,created_at)
   VALUES(1,1,'user','我们约定去海边旅行。','2020-01-01'),(2,1,'assistant','海边旅行的约定。','2020-01-01');
   INSERT INTO context_messages(id,conversation_id,role,content)
   SELECT n,n,'user','今天聊聊天' FROM generate_series(3,3005) n;`);
  const query=sql.lexical_search.find(s=>s.includes('WITH hits'));
  const find=()=>db.query(query,[['海边','旅行']]);
  assert.deepEqual((await find()).rows.map(r=>r.id),[1,2], 'old original survives 3000 newer messages');
  await db.exec("UPDATE context_messages SET content='改成去山上看雪' WHERE id IN (1,2)");
  assert.equal((await find()).rows.length,0,'edited content cannot be recalled from stale index');
  await db.exec("INSERT INTO context_messages(id,conversation_id,role,content) VALUES(4000,3,'user','海边旅行')");
  assert.equal((await find()).rows.length,1);
  await db.exec('UPDATE context_messages SET hidden=true WHERE id=4000');
  assert.equal((await find()).rows.length,0);
  await db.exec('DELETE FROM context_messages WHERE id=4000');
  assert.equal((await find()).rows.length,0);
  await db.exec('SET enable_seqscan=off');
  const plan=await db.query("EXPLAIN SELECT id FROM context_messages WHERE hidden=FALSE AND kind='chat' AND role IN ('user','assistant') AND ash_memory_terms(content) && $1::text[]",[['海边']]);
  assert.match(JSON.stringify(plan.rows),/idx_context_memory_terms/);
  console.log('Passed production PostgreSQL Chinese index, old history, edit/hide/delete consistency and index query plan.');
 }finally{await db.close();}
})().catch(error=>{console.error(error);process.exit(1);});
