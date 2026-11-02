"""Workspace-scoped SQLite persistence."""
import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .prompts import DEFAULT_PROMPT

_UNGUARDED = object()


def uid():
    return uuid.uuid4().hex


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE IF NOT EXISTS notebooks(id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,notebook_id TEXT NOT NULL REFERENCES notebooks(id),
                name TEXT NOT NULL,tagline TEXT NOT NULL,instructions TEXT NOT NULL,greeting TEXT NOT NULL,
                starters TEXT NOT NULL,color TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,archived_at TEXT);
              CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,notebook_id TEXT NOT NULL REFERENCES notebooks(id),
                title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,deleted_at TEXT,agent_id TEXT);
              CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL,content TEXT NOT NULL,status TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,reply_to TEXT UNIQUE,request_token TEXT);
              CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,message_id TEXT NOT NULL REFERENCES messages(id),
                content TEXT NOT NULL,metadata TEXT NOT NULL,created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS settings(notebook_id TEXT PRIMARY KEY REFERENCES notebooks(id),value TEXT NOT NULL,secret TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS diaries(id TEXT PRIMARY KEY,notebook_id TEXT NOT NULL REFERENCES notebooks(id),agent_id TEXT NOT NULL REFERENCES agents(id),
                day TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,content TEXT NOT NULL,tags TEXT NOT NULL,
                source_hash TEXT NOT NULL,sources TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                UNIQUE(notebook_id,agent_id,day));
              CREATE TABLE IF NOT EXISTS diary_runs(notebook_id TEXT NOT NULL,agent_id TEXT NOT NULL,day TEXT NOT NULL,
                status TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,PRIMARY KEY(notebook_id,agent_id,day));
              CREATE INDEX IF NOT EXISTS conv_owner ON conversations(notebook_id,updated_at);
              CREATE INDEX IF NOT EXISTS msg_parent ON messages(conversation_id,created_at);
              CREATE INDEX IF NOT EXISTS diary_owner ON diaries(notebook_id,day);
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def unpack(row):
        if row is None:
            raise LookupError("内容不存在或不属于当前空间")
        item = dict(row)
        for field in ("starters", "metadata", "tags", "sources"):
            if field in item:
                item[field] = json.loads(item[field])
        return item

    def ensure_workspace(self, owner):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO notebooks(id,created_at) VALUES (?,?)", (owner, now()))
            db.execute("INSERT OR IGNORE INTO app_meta VALUES ('primary_workspace',?)", (owner,))
            if not db.execute("SELECT 1 FROM agents WHERE notebook_id=?", (owner,)).fetchone():
                aid, stamp = uid(), now()
                db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                           (aid, owner, "默认助手", "闲聊、吐槽，或者一起琢磨点事。", DEFAULT_PROMPT, "", json.dumps(["今天终于忙完了", "有件小事想跟你吐槽", "突然有个挺离谱的脑洞"], ensure_ascii=False), "#71806a", stamp, stamp))
        return self.agents(owner)

    def primary_workspace(self):
        with self.db() as db:
            return db.execute("SELECT value FROM app_meta WHERE key='primary_workspace'").fetchone()[0]

    def agents(self, owner):
        with self.db() as db:
            return [self.unpack(r) for r in db.execute("SELECT * FROM agents WHERE notebook_id=? AND archived_at IS NULL ORDER BY created_at,id", (owner,))]

    def agent(self, owner, aid, include_archived=False):
        with self.db() as db:
            query = "SELECT * FROM agents WHERE notebook_id=? AND id=?" + ("" if include_archived else " AND archived_at IS NULL")
            return self.unpack(db.execute(query, (owner, aid)).fetchone())

    def save_agent(self, owner, value, aid=None):
        stamp = now()
        with self.db() as db:
            if aid:
                self.unpack(db.execute("SELECT * FROM agents WHERE notebook_id=? AND id=? AND archived_at IS NULL", (owner, aid)).fetchone())
                db.execute("UPDATE agents SET name=?,tagline=?,instructions=?,greeting=?,starters=?,color=?,updated_at=? WHERE id=?",
                           (value["name"], value["tagline"], value["instructions"], value["greeting"], json.dumps(value["starters"], ensure_ascii=False), value["color"], stamp, aid))
            else:
                aid = uid()
                db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,NULL)", (aid, owner, value["name"], value["tagline"], value["instructions"], value["greeting"], json.dumps(value["starters"], ensure_ascii=False), value["color"], stamp, stamp))
        return self.agent(owner, aid)

    def archive_agent(self, owner, aid):
        self.agent(owner, aid)
        if len(self.agents(owner)) <= 1:
            raise ValueError("请至少保留一个智能体")
        with self.db() as db:
            db.execute("UPDATE agents SET archived_at=? WHERE notebook_id=? AND id=?", (now(), owner, aid))

    def settings(self, owner):
        with self.db() as db:
            row = db.execute("SELECT * FROM settings WHERE notebook_id=?", (owner,)).fetchone()
            return {"value": json.loads(row["value"]), "secret": row["secret"]} if row else None

    def save_settings(self, owner, value, secret):
        with self.db() as db:
            db.execute("INSERT INTO settings VALUES (?,?,?,?) ON CONFLICT(notebook_id) DO UPDATE SET value=excluded.value,secret=excluded.secret,updated_at=excluded.updated_at", (owner, json.dumps(value, ensure_ascii=False), secret, now()))

    def conversations(self, owner, query=""):
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self.db() as db:
            return [self.unpack(r) for r in db.execute("""SELECT c.*,a.name AS agent_name,a.color FROM conversations c JOIN agents a ON a.id=c.agent_id
              WHERE c.notebook_id=? AND c.deleted_at IS NULL AND a.archived_at IS NULL AND
              (c.title LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND m.content LIKE ? ESCAPE '\\'))
              ORDER BY c.updated_at DESC,c.id DESC""", (owner, pattern, pattern))]

    def conversation(self, owner, cid):
        with self.db() as db:
            return self.unpack(db.execute("SELECT * FROM conversations WHERE notebook_id=? AND id=? AND deleted_at IS NULL", (owner, cid)).fetchone())

    def create_conversation(self, owner, aid):
        agent = self.agent(owner, aid)
        cid, stamp = uid(), now()
        with self.db() as db:
            db.execute("INSERT INTO conversations(id,notebook_id,title,created_at,updated_at,agent_id) VALUES (?,?,'新对话',?,?,?)", (cid, owner, stamp, stamp, aid))
            if agent["greeting"]:
                db.execute("INSERT INTO messages(id,conversation_id,role,content,status,created_at,updated_at) VALUES (?,?,'assistant',?,'complete',?,?)", (uid(), cid, agent["greeting"], stamp, stamp))
        return self.conversation(owner, cid)

    def rename_conversation(self, owner, cid, title):
        self.conversation(owner, cid)
        with self.db() as db:
            db.execute("UPDATE conversations SET title=? WHERE id=?", (title, cid))

    def delete_conversation(self, owner, cid):
        self.conversation(owner, cid)
        with self.db() as db:
            db.execute("UPDATE conversations SET deleted_at=? WHERE id=?", (now(), cid))

    def messages(self, owner, cid):
        self.conversation(owner, cid)
        with self.db() as db:
            return [self.unpack(r) for r in db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,id", (cid,))]

    def begin_turn(self, owner, cid, content):
        conv = self.conversation(owner, cid)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM messages WHERE conversation_id=? AND status IN ('pending','processing')", (cid,)).fetchone():
                raise ConflictError("上一条回复还在生成中")
            mid, stamp = uid(), now()
            db.execute("INSERT INTO messages(id,conversation_id,role,content,status,created_at,updated_at) VALUES (?,?,'user',?,'pending',?,?)", (mid, cid, content, stamp, stamp))
            db.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?", (content[:30] if conv["title"] == "新对话" else conv["title"], stamp, cid))
        return mid

    def claim_turn(self, owner, cid, mid, regenerate=False):
        self.conversation(owner, cid)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            user = self.unpack(db.execute("SELECT * FROM messages WHERE id=? AND conversation_id=? AND role='user'", (mid, cid)).fetchone())
            latest = db.execute("SELECT id FROM messages WHERE conversation_id=? AND role='user' ORDER BY created_at DESC LIMIT 1", (cid,)).fetchone()
            allowed = ("complete",) if regenerate else ("pending", "failed")
            if user["status"] not in allowed or latest["id"] != mid:
                raise ConflictError("请在最近一条消息上重试或重新生成")
            token = uid()
            db.execute("UPDATE messages SET status='processing',error='',request_token=?,updated_at=? WHERE id=?", (token, now(), mid))
            user["request_token"] = token
            return user

    def finish_turn(self, owner, cid, mid, token, text, metadata):
        self.conversation(owner, cid)
        stamp = now()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            user = self.unpack(db.execute("SELECT * FROM messages WHERE id=? AND conversation_id=?", (mid, cid)).fetchone())
            if user["status"] != "processing" or user["request_token"] != token:
                raise ConflictError("消息状态已改变，请刷新后重试")
            old = db.execute("SELECT * FROM messages WHERE reply_to=?", (mid,)).fetchone()
            if old:
                assistant_id = old["id"]
                db.execute("INSERT INTO revisions VALUES (?,?,?,?,?)", (uid(), assistant_id, old["content"], old["metadata"], stamp))
                db.execute("UPDATE messages SET content=?,metadata=?,updated_at=? WHERE id=?", (text, json.dumps(metadata), stamp, assistant_id))
            else:
                assistant_id = uid()
                db.execute("INSERT INTO messages(id,conversation_id,role,content,status,metadata,created_at,updated_at,reply_to) VALUES (?,?,'assistant',?,'complete',?,?,?,?)", (assistant_id, cid, text, json.dumps(metadata), stamp, stamp, mid))
            db.execute("UPDATE messages SET status='complete',error='',request_token=NULL,updated_at=? WHERE id=?", (stamp, mid))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (stamp, cid))
        return assistant_id

    def fail_turn(self, owner, cid, mid, token, error):
        self.conversation(owner, cid)
        with self.db() as db:
            old = db.execute("SELECT 1 FROM messages WHERE reply_to=?", (mid,)).fetchone()
            db.execute("UPDATE messages SET status=?,error=?,request_token=NULL,updated_at=? WHERE id=? AND conversation_id=? AND request_token=? AND status='processing'", ("complete" if old else "failed", error[:250], now(), mid, cid, token))

    def recover(self, owner):
        threshold = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)).isoformat()
        with self.db() as db:
            db.execute("""UPDATE messages SET status=CASE WHEN EXISTS(SELECT 1 FROM messages a WHERE a.reply_to=messages.id) THEN 'complete' ELSE 'failed' END,
              error='上一次生成已中断，可以重试',request_token=NULL WHERE status IN ('pending','processing') AND updated_at<? AND
              conversation_id IN (SELECT id FROM conversations WHERE notebook_id=?)""", (threshold, owner))

    def stop_turn(self, owner, cid):
        self.conversation(owner, cid)
        with self.db() as db:
            db.execute("""UPDATE messages SET status=CASE WHEN EXISTS(SELECT 1 FROM messages a WHERE a.reply_to=messages.id) THEN 'complete' ELSE 'failed' END,
              error='已停止生成，可以重试',request_token=NULL,updated_at=?
              WHERE conversation_id=? AND role='user' AND status IN ('pending','processing')""", (now(), cid))

    def daily_messages(self, owner, aid, day, offset=480):
        self.agent(owner, aid, include_archived=True)
        start = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), dt.timezone(dt.timedelta(minutes=offset)))
        end = start + dt.timedelta(days=1)
        with self.db() as db:
            rows = db.execute("""SELECT m.*,c.title AS conversation_title,c.agent_id FROM messages m JOIN conversations c ON c.id=m.conversation_id
              LEFT JOIN messages parent ON parent.id=m.reply_to
              WHERE c.notebook_id=? AND c.agent_id=? AND c.deleted_at IS NULL AND m.status='complete' AND
              COALESCE(parent.created_at,m.created_at)>=? AND COALESCE(parent.created_at,m.created_at)<? AND (m.role='user' OR m.reply_to IS NOT NULL)
              ORDER BY m.created_at,m.id""", (owner, aid, start.astimezone(dt.timezone.utc).isoformat(), end.astimezone(dt.timezone.utc).isoformat()))
            return [self.unpack(r) for r in rows]

    @staticmethod
    def source_hash(messages):
        return hashlib.sha256(json.dumps([(m["id"], m["content"], m["updated_at"]) for m in messages], ensure_ascii=False).encode()).hexdigest()

    def diaries(self, owner, aid=None):
        with self.db() as db:
            query = "SELECT d.*,a.name AS agent_name,a.color FROM diaries d JOIN agents a ON a.id=d.agent_id WHERE d.notebook_id=?"
            args = [owner]
            if aid:
                query += " AND d.agent_id=?"
                args.append(aid)
            return [self.unpack(r) for r in db.execute(query + " ORDER BY d.day DESC,d.updated_at DESC", args)]

    def diary(self, owner, did):
        with self.db() as db:
            return self.unpack(db.execute("SELECT d.*,a.name AS agent_name,a.color FROM diaries d JOIN agents a ON a.id=d.agent_id WHERE d.notebook_id=? AND d.id=?", (owner, did)).fetchone())

    def diary_for_day(self, owner, aid, day):
        return next((d for d in self.diaries(owner, aid) if d["day"] == day), None)

    @staticmethod
    def diary_state_key(owner, aid, day):
        return 'diary-state:' + owner + ':' + aid + ':' + day

    def diary_generation_state(self, owner, aid, day):
        with self.db() as db:
            row = db.execute('SELECT value FROM app_meta WHERE key=?', (self.diary_state_key(owner, aid, day),)).fetchone()
            return json.loads(row[0]) if row else {"revision": None, "deleted": False}

    def delete_diary(self, owner, did):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            entry = self.unpack(db.execute('SELECT * FROM diaries WHERE notebook_id=? AND id=?', (owner, did)).fetchone())
            key = self.diary_state_key(owner, entry['agent_id'], entry['day'])
            db.execute('INSERT OR REPLACE INTO app_meta VALUES (?,?)',
                       (key, json.dumps({"revision": uid(), "deleted": True})))
            db.execute('DELETE FROM diaries WHERE notebook_id=? AND id=?', (owner, did))
            db.execute('DELETE FROM diary_runs WHERE notebook_id=? AND agent_id=? AND day=?',
                       (owner, entry['agent_id'], entry['day']))

    def save_diary(self, owner, aid, day, draft, sources, evidence_ids=None, expected_revision=_UNGUARDED):
        self.agent(owner, aid, include_archived=True)
        stamp, did = now(), uid()
        fingerprint = self.source_hash(sources)
        source_ids = [m["id"] for m in sources if evidence_ids is None or m["id"] in evidence_ids]
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            key = self.diary_state_key(owner, aid, day)
            row = db.execute('SELECT value FROM app_meta WHERE key=?', (key,)).fetchone()
            state = json.loads(row[0]) if row else {"revision": None, "deleted": False}
            if expected_revision is not _UNGUARDED and state['revision'] != expected_revision:
                raise ValueError('日记已删除，已丢弃此前的整理结果')
            if state['deleted']:
                state['deleted'] = False
                db.execute('UPDATE app_meta SET value=? WHERE key=?', (json.dumps(state), key))
            db.execute("""INSERT INTO diaries VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(notebook_id,agent_id,day) DO UPDATE SET
              title=excluded.title,summary=excluded.summary,content=excluded.content,tags=excluded.tags,
              source_hash=excluded.source_hash,sources=excluded.sources,updated_at=excluded.updated_at""",
                       (did, owner, aid, day, draft["title"], draft["summary"], draft["content"], json.dumps(draft["tags"], ensure_ascii=False), fingerprint, json.dumps(source_ids), stamp, stamp))
        return self.diary_for_day(owner, aid, day)

    def diary_last_attempt(self, owner, aid, day):
        key = "diary-attempt:" + owner + ":" + aid + ":" + day
        with self.db() as db:
            row = db.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def record_diary_attempt(self, owner, aid, day, started_at):
        key = "diary-attempt:" + owner + ":" + aid + ":" + day
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES (?,?)", (key, started_at))

    def diary_status(self, owner, aid, day, status, error=""):
        with self.db() as db:
            db.execute("INSERT INTO diary_runs VALUES (?,?,?,?,?,?) ON CONFLICT(notebook_id,agent_id,day) DO UPDATE SET status=excluded.status,error=excluded.error,updated_at=excluded.updated_at", (owner, aid, day, status, error[:250], now()))

    def diary_runs(self, owner):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM diary_runs WHERE notebook_id=? ORDER BY updated_at DESC", (owner,))]

    def diary_sources(self, owner, did):
        diary = self.diary(owner, did)
        with self.db() as db:
            rows = db.execute("SELECT m.*,c.title AS conversation_title FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.notebook_id=? AND c.agent_id=? AND c.deleted_at IS NULL ORDER BY m.created_at", (owner, diary["agent_id"]))
            return [self.unpack(r) for r in rows if r["id"] in set(diary["sources"])]
