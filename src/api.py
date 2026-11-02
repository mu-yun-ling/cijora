"""Local-first HTTP API and static web application."""
import datetime as dt
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field, ValidationError
from typing import Optional

from .models import AgentDraft, ModelSettings
from .provider import Provider, ProviderError
from .services import Services, DiaryQueue
from .store import Store, ConflictError
from .vault import Vault

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).parent / "web"
markdown = MarkdownIt("commonmark", {"html": False}).disable("image").enable("table")


class SessionInput(BaseModel):
    book: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ConversationInput(BaseModel):
    agent_id: str = Field(min_length=1, max_length=40)


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=16000)


class DesignInput(BaseModel):
    description: str = Field(min_length=5, max_length=6000)


class RenameInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class DiaryInput(BaseModel):
    agent_id: str
    day: dt.date


def public_message(row):
    item = {k: row.get(k) for k in ("id", "role", "content", "status", "error", "reply_to", "created_at", "updated_at")}
    item["html"] = markdown.render(row["content"]) if row["role"] == "assistant" else ""
    return item


def public_diary(row):
    result = dict(row)
    result["html"] = markdown.render(row["content"])
    result["source_count"] = len(row["sources"])
    return result


def create_app(data_dir=None, provider_factory=Provider, jobs_enabled=True, import_environment=True):
    directory = Path(data_dir or os.getenv("MORROW_DATA_DIR", str(ROOT / "data/private")))
    store = Store(directory / "notebook.sqlite3")
    services = Services(store, Vault(directory), provider_factory)
    services.import_environment = import_environment
    queue = DiaryQueue(services) if jobs_enabled else None
    services.diary_queue = queue

    @asynccontextmanager
    async def lifespan(app):
        # Recover only this app's old leases; never replace active requests.
        with store.db() as db:
            owners = [row[0] for row in db.execute("SELECT id FROM notebooks")]
        for owner in owners:
            store.ensure_workspace(owner)
            store.recover(owner)
            config = services.public_settings(owner)
            if queue and config["auto_diary"] and config["configured"]:
                tz = dt.timezone(dt.timedelta(minutes=config["offset_minutes"]))
                today = dt.datetime.now(tz).date()
                for agent in store.agents(owner):
                    for date in (today - dt.timedelta(days=1), today):
                        if store.daily_messages(owner, agent["id"], date.isoformat(), config["offset_minutes"]):
                            queue.submit(owner, agent["id"], date.isoformat())
        yield
        if queue:
            queue.close()

    app = FastAPI(title="Cijora · 此间絮语", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.services = store, services
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def same_origin(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "不允许跨站修改本地数据"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        return response

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        return JSONResponse({"detail": "内容不存在或不属于当前空间"}, status_code=404)

    @app.exception_handler(ConflictError)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "生成的内容不符合格式，请重试" if isinstance(exc, ValidationError) else str(exc)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, status_code=422)

    def owner(request: Request):
        value = request.cookies.get("morrow_workspace", "")
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise HTTPException(401, "请刷新页面建立本地空间")
        with store.db() as db:
            if not db.execute("SELECT 1 FROM notebooks WHERE id=?", (value,)).fetchone():
                raise HTTPException(401, "本地空间不存在，请刷新页面")
        return value

    @app.post("/api/session")
    def session(body: SessionInput, request: Request, response: Response):
        workspace = body.book or request.cookies.get("morrow_workspace", "")
        if not re.fullmatch(r"[a-f0-9]{32}", workspace):
            workspace = secrets.token_hex(16)
        store.ensure_workspace(workspace)
        services.ensure_settings(workspace)
        response.set_cookie("morrow_workspace", workspace, httponly=True, samesite="strict", max_age=31536000)
        return {"book": workspace}

    @app.get("/api/bootstrap")
    def bootstrap(workspace=Depends(owner)):
        store.recover(workspace)
        return {"agents": store.agents(workspace), "conversations": store.conversations(workspace),
                "settings": services.public_settings(workspace), "diary_runs": store.diary_runs(workspace)}

    @app.get("/api/agents")
    def agents(workspace=Depends(owner)):
        return store.agents(workspace)

    @app.post("/api/agents")
    def new_agent(body: AgentDraft, workspace=Depends(owner)):
        return store.save_agent(workspace, body.model_dump())

    @app.post("/api/agents/design")
    def design_agent(body: DesignInput, workspace=Depends(owner)):
        return services.design_agent(workspace, body.description)

    @app.put("/api/agents/{aid}")
    def edit_agent(aid: str, body: AgentDraft, workspace=Depends(owner)):
        return store.save_agent(workspace, body.model_dump(), aid)

    @app.delete("/api/agents/{aid}")
    def archive_agent(aid: str, workspace=Depends(owner)):
        store.archive_agent(workspace, aid)
        return {"ok": True}

    @app.get("/api/settings")
    def settings(workspace=Depends(owner)):
        return services.public_settings(workspace)

    @app.put("/api/settings")
    def save_settings(body: ModelSettings, workspace=Depends(owner)):
        return services.save_settings(workspace, body)

    @app.post("/api/settings/test")
    def test_settings(body: ModelSettings, workspace=Depends(owner)):
        return services.test_connection(workspace, body)

    @app.get("/api/conversations")
    def conversations(q: str = "", workspace=Depends(owner)):
        return store.conversations(workspace, q[:200])

    @app.post("/api/conversations")
    def new_conversation(body: ConversationInput, workspace=Depends(owner)):
        return store.create_conversation(workspace, body.agent_id)

    @app.get("/api/conversations/{cid}")
    def conversation(cid: str, workspace=Depends(owner)):
        store.recover(workspace)
        return {"conversation": store.conversation(workspace, cid), "messages": [public_message(m) for m in store.messages(workspace, cid)]}

    @app.patch("/api/conversations/{cid}")
    def rename_conversation(cid: str, body: RenameInput, workspace=Depends(owner)):
        if not body.title.strip():
            raise ValueError("标题不能为空")
        store.rename_conversation(workspace, cid, body.title.strip())
        return {"ok": True}

    @app.delete("/api/conversations/{cid}")
    def delete_conversation(cid: str, workspace=Depends(owner)):
        store.delete_conversation(workspace, cid)
        return {"ok": True}

    def stream_response(workspace, cid, mid, regenerate=False):
        iterator = services.chat_events(workspace, cid, mid, regenerate)
        first = next(iterator)
        def generate():
            try:
                kind, value = first
                yield "event: %s\ndata: %s\n\n" % (kind, json.dumps(value, ensure_ascii=False))
                for kind, value in iterator:
                    yield "event: %s\ndata: %s\n\n" % (kind, json.dumps(value, ensure_ascii=False))
            finally:
                iterator.close()
        return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/conversations/{cid}/messages/stream")
    def send(cid: str, body: MessageInput, workspace=Depends(owner)):
        if not body.content.strip():
            raise ValueError("消息不能为空")
        mid = store.begin_turn(workspace, cid, body.content.strip())
        return stream_response(workspace, cid, mid)

    @app.post("/api/conversations/{cid}/messages/{mid}/retry")
    def retry(cid: str, mid: str, workspace=Depends(owner)):
        return stream_response(workspace, cid, mid)

    @app.post("/api/conversations/{cid}/stop")
    def stop(cid: str, workspace=Depends(owner)):
        store.stop_turn(workspace, cid)
        return {"ok": True}

    @app.post("/api/conversations/{cid}/messages/{mid}/regenerate")
    def regenerate(cid: str, mid: str, workspace=Depends(owner)):
        return stream_response(workspace, cid, mid, True)

    @app.get("/api/diaries")
    def diaries(agent_id: Optional[str] = None, workspace=Depends(owner)):
        return {"entries": [public_diary(d) for d in store.diaries(workspace, agent_id)], "runs": store.diary_runs(workspace)}

    @app.post("/api/diaries/generate", status_code=202)
    def generate_diary(body: DiaryInput, workspace=Depends(owner)):
        store.agent(workspace, body.agent_id)
        if not services.public_settings(workspace)["configured"]:
            raise ValueError("请先在设置中连接模型")
        if not store.daily_messages(workspace, body.agent_id, body.day.isoformat(), services.public_settings(workspace)["offset_minutes"]):
            raise ValueError("这一天还没有可整理的对话")
        if queue:
            queue.submit(workspace, body.agent_id, body.day.isoformat(), force=True)
            return {"status": "queued"}
        return public_diary(services.generate_diary(workspace, body.agent_id, body.day.isoformat(), force=True))

    @app.delete("/api/diaries/{did}")
    def delete_diary(did: str, workspace=Depends(owner)):
        entry = store.diary(workspace, did)
        store.delete_diary(workspace, did)
        if queue:
            queue.cancel_day(workspace, entry['agent_id'], entry['day'])
        return {"ok": True}

    @app.get("/api/diaries/{did}/sources")
    def diary_sources(did: str, workspace=Depends(owner)):
        return [dict(public_message(m), conversation_id=m["conversation_id"], conversation_title=m["conversation_title"]) for m in store.diary_sources(workspace, did)]

    @app.get("/api/diaries/{did}/export")
    def export_diary(did: str, workspace=Depends(owner)):
        diary = store.diary(workspace, did)
        text = "# %s\n\n%s · %s\n\n%s\n" % (diary["title"], diary["day"], diary["agent_name"], diary["content"])
        return Response(text, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="diary-%s.md"' % diary["day"]})

    @app.get("/health")
    def health():
        return {"ok": True, "chat_voice_version": 4, "diary_memory_version": 4, "diary_delete_version": 1}

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/assets", StaticFiles(directory=str(WEB)), name="assets")
    return app
