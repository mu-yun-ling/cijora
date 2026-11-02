"""Opt-in live test of agent design, streaming and grounded diary generation."""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from src.services import Services
from src.store import Store
from src.vault import Vault

with tempfile.TemporaryDirectory() as directory:
    store = Store(Path(directory) / "smoke.sqlite3")
    owner = "c" * 32
    store.ensure_workspace(owner)
    service = Services(store, Vault(directory))
    try:
        draft = service.design_agent(owner, "一个说话简洁、温和的阅读伙伴，喜欢科幻，也会认真倾听生活里的小事。")
        agent = store.save_agent(owner, draft)
        conv = store.create_conversation(owner, agent["id"])
        mid = store.begin_turn(owner, conv["id"], "今天读了一篇关于宇宙的短篇故事，想和你聊聊想象力。")
        events = list(service.chat_events(owner, conv["id"], mid))
        if events[-1][0] != "done":
            raise RuntimeError(events[-1][1].get("message", "聊天未完成"))
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        diary = service.generate_diary(owner, agent["id"], day)
        print(json.dumps({"ok": True, "agent_design": draft["name"], "streamed_reply": store.messages(owner, conv["id"])[-1]["content"], "diary_title": diary["title"], "source_count": len(diary["sources"])}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "message": str(exc)[:250]}, ensure_ascii=False))
        sys.exit(1)
