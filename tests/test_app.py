"""Offline integration tests for agent isolation, streaming, settings and diaries."""
import datetime as dt
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.api import create_app
from src.models import AgentDraft, ModelSettings
from src.provider import ProviderError
from src.services import Services, DiaryQueue
from src.store import Store, ConflictError
from src.vault import Vault

OWNER = "a" * 32
OTHER = "b" * 32


class FakeProvider:
    calls = []
    fail = False

    def __init__(self, config, api_key):
        self.config, self.key = config, api_key

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def complete(self, messages, structured=False):
        self.calls.append(messages)
        if self.fail:
            raise ProviderError("测试连接失败")
        prompt = messages[0]["content"]
        if "智能体设计师" in prompt:
            return json.dumps({"name": "星野", "tagline": "一起写故事", "instructions": "你是一名温和的科幻作家。", "greeting": "今天想写什么？", "starters": ["构思一颗星球"], "color": "#7867bf"}, ensure_ascii=False)
        if "摘取有来源的回忆素材" in prompt:
            rows = json.loads(messages[-1]["content"])["messages"]
            return json.dumps({"notes": [{"note": "我们聊过的一件小事", "source_indices": [row["index"] for row in rows]}]}, ensure_ascii=False)
        if "对话日记" in prompt:
            material = json.loads(messages[-1]["content"])
            indices = [row["index"] for row in material["messages"]] if "messages" in material else sorted({i for note in material["notes"] for i in note["source_indices"]})
            return json.dumps({"title": "今天的小小故事", "summary": "我们聊了今天发生的事。", "content": "今天，我们在对话里分享了近况。", "tags": ["日常"], "source_indices": indices}, ensure_ascii=False)
        return "连接成功"

    def stream(self, messages):
        self.calls.append(messages)
        yield "你好，"
        if self.fail:
            raise ProviderError("测试生成中断")
        yield "我在听。"


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "notebook.sqlite3"
        self.store = Store(self.path)
        self.store.ensure_workspace(OWNER)
        self.store.ensure_workspace(OTHER)
        self.aid = self.store.agents(OWNER)[0]["id"]
        self.cid = self.store.create_conversation(OWNER, self.aid)["id"]
        self.services = Services(self.store, Vault(self.tmp.name), FakeProvider)
        self.services.import_environment = False
        self.services.save_settings(OWNER, ModelSettings(base_url="https://model.test/v1", model="test-model", api_key="private-key", auto_diary=False))
        FakeProvider.calls = []
        FakeProvider.fail = False

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, text, cid=None):
        cid = cid or self.cid
        mid = self.store.begin_turn(OWNER, cid, text)
        events = list(self.services.chat_events(OWNER, cid, mid))
        return mid, events

    def test_custom_agent_is_used_and_other_agents_are_isolated(self):
        agent = AgentDraft(name="海边作家", instructions="你说话像一位科幻作家。")
        second = self.store.save_agent(OWNER, agent.model_dump())
        cid = self.store.create_conversation(OWNER, second["id"])["id"]
        self.send("只属于第一个智能体的消息")
        self.send("你好", cid)
        context = FakeProvider.calls[-1]
        self.assertIn("科幻作家", context[0]["content"])
        self.assertNotIn("只属于第一个智能体", str(context))

    def test_workspace_reads_and_updates_are_scoped(self):
        self.send("私人内容")
        with self.assertRaises(LookupError):
            self.store.messages(OTHER, self.cid)
        with self.assertRaises(LookupError):
            self.store.agent(OTHER, self.aid)
        with self.assertRaises(LookupError):
            self.store.rename_conversation(OTHER, self.cid, "偷改")

    def test_single_call_stream_and_context_restore(self):
        self.send("我叫小林")
        _, events = self.send("我刚才说了什么？")
        self.assertEqual(2, len(FakeProvider.calls))
        self.assertIn("我叫小林", str(FakeProvider.calls[-1]))
        self.assertEqual(["meta", "token", "token", "done"], [e[0] for e in events])
        self.assertEqual("你好，我在听。", self.store.messages(OWNER, self.cid)[-1]["content"])

    def test_interrupted_generation_retries_without_duplicate_user(self):
        FakeProvider.fail = True
        mid, events = self.send("今天想聊聊")
        self.assertEqual("error", events[-1][0])
        self.assertEqual("failed", self.store.messages(OWNER, self.cid)[-1]["status"])
        FakeProvider.fail = False
        list(self.services.chat_events(OWNER, self.cid, mid))
        self.assertEqual(1, sum(m["role"] == "user" for m in self.store.messages(OWNER, self.cid)))

    def test_regeneration_preserves_old_reply_on_failure_and_versions_on_success(self):
        mid, _ = self.send("你好")
        FakeProvider.fail = True
        list(self.services.chat_events(OWNER, self.cid, mid, True))
        self.assertEqual("你好，我在听。", self.store.messages(OWNER, self.cid)[-1]["content"])
        FakeProvider.fail = False
        list(self.services.chat_events(OWNER, self.cid, mid, True))
        with self.store.db() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM revisions").fetchone()[0])

    def test_expired_request_cannot_overwrite_a_new_attempt(self):
        mid = self.store.begin_turn(OWNER, self.cid, "你好")
        old = self.store.claim_turn(OWNER, self.cid, mid)
        self.store.fail_turn(OWNER, self.cid, mid, old["request_token"], "旧请求失败")
        fresh = self.store.claim_turn(OWNER, self.cid, mid)
        with self.assertRaises(ConflictError):
            self.store.finish_turn(OWNER, self.cid, mid, old["request_token"], "过时回复", {})
        self.store.fail_turn(OWNER, self.cid, mid, old["request_token"], "不能覆盖新请求")
        self.store.finish_turn(OWNER, self.cid, mid, fresh["request_token"], "新回复", {})
        self.assertEqual("新回复", self.store.messages(OWNER, self.cid)[-1]["content"])

    def test_settings_are_encrypted_redacted_and_keep_blank_key(self):
        saved = self.store.settings(OWNER)
        self.assertNotIn("private-key", str(saved))
        self.assertNotIn("secret", self.services.public_settings(OWNER))
        self.assertNotIn("api_key", self.services.public_settings(OWNER))
        self.services.save_settings(OWNER, ModelSettings(base_url="https://model.test/v1", model="another"))
        self.assertEqual("private-key", self.services.resolve_settings(OWNER)[1])
        self.services.save_settings(OWNER, ModelSettings(clear_api_key=True))
        self.assertFalse(self.services.public_settings(OWNER)["has_api_key"])

    def test_stopped_generation_is_immediately_retryable_and_cannot_save_late_output(self):
        mid = self.store.begin_turn(OWNER, self.cid, "你好")
        attempt = self.store.claim_turn(OWNER, self.cid, mid)
        with self.assertRaises(LookupError):
            self.store.stop_turn(OTHER, self.cid)
        self.store.stop_turn(OWNER, self.cid)
        with self.assertRaises(ConflictError):
            self.store.finish_turn(OWNER, self.cid, mid, attempt["request_token"], "迟到的回复", {})
        list(self.services.chat_events(OWNER, self.cid, mid))
        self.assertEqual(2, len(self.store.messages(OWNER, self.cid)))

    def test_model_config_does_not_leak_into_agent_prompt(self):
        self.send("你好")
        self.assertNotIn("private-key", str(FakeProvider.calls))

    def test_diary_has_sources_date_and_agent_scope(self):
        self.send("今天我完成了一幅画")
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        entry = self.services.generate_diary(OWNER, self.aid, day)
        self.assertEqual(2, len(entry["sources"]))
        self.assertEqual(2, len(self.store.diary_sources(OWNER, entry["id"])))
        self.assertIn("今天我完成了一幅画", str(FakeProvider.calls[-1]))
        self.assertIn("不得冒充现实", FakeProvider.calls[-1][0]["content"])
        with self.assertRaises(LookupError):
            self.store.diary(OTHER, entry["id"])

    def test_unchanged_diary_is_not_generated_twice(self):
        self.send("今天画画了")
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        self.services.generate_diary(OWNER, self.aid, day)
        calls = len(FakeProvider.calls)
        self.services.generate_diary(OWNER, self.aid, day)
        self.assertEqual(calls, len(FakeProvider.calls))
        self.send("后来还读了书")
        entry = self.services.generate_diary(OWNER, self.aid, day)
        self.assertEqual(4, len(entry["sources"]))

    def test_empty_day_never_invents_a_story(self):
        with self.assertRaises(ValueError):
            self.services.generate_diary(OWNER, self.aid, "2020-01-01")
        self.assertEqual([], FakeProvider.calls)

    def test_ai_agent_design_is_a_draft_not_an_automatic_save(self):
        count = len(self.store.agents(OWNER))
        draft = self.services.design_agent(OWNER, "一个陪我写科幻故事的朋友")
        self.assertEqual("星野", draft["name"])
        self.assertEqual(count, len(self.store.agents(OWNER)))

    def test_local_timezone_boundaries(self):
        mid, _ = self.send("跨日的故事")
        with self.store.db() as db:
            db.execute("UPDATE messages SET created_at='2026-10-29T16:00:00+00:00' WHERE conversation_id=?", (self.cid,))
        self.assertEqual(2, len(self.store.daily_messages(OWNER, self.aid, "2026-10-30", 480)))
        self.assertEqual([], self.store.daily_messages(OWNER, self.aid, "2026-10-29", 480))

    def test_automatic_diary_coalesces_messages_arriving_during_generation(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = self.services.generate_diary
        calls = []

        def generate(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Test worker timed out")
            result = original(*args, **kwargs)
            if len(calls) == 2:
                finished.set()
            return result

        self.services.generate_diary = generate
        self.services.save_settings(OWNER, ModelSettings(base_url="https://model.test/v1", model="test", auto_diary=True))
        queue = DiaryQueue(self.services, idle_seconds=0, min_interval_seconds=0)
        self.services.diary_queue = queue
        try:
            self.send("今天开始画画")
            self.assertTrue(started.wait(3))
            self.send("我画了一座灯塔")
            self.send("然后又读了一本书")
            release.set()
            self.assertTrue(finished.wait(5))
        finally:
            release.set()
            queue.close()
            queue.pool.shutdown(wait=True)
        self.assertEqual(2, len(calls))
        diary = self.store.diaries(OWNER)[0]
        self.assertEqual(6, len(diary["sources"]))
        self.assertEqual("complete", self.store.diary_runs(OWNER)[0]["status"])

    def test_failed_background_diary_exposes_retryable_status(self):
        self.send("今天完成了一幅画")
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        FakeProvider.fail = True
        queue = DiaryQueue(self.services, idle_seconds=0, min_interval_seconds=0)
        queue.submit(OWNER, self.aid, day, force=True)
        queue.pool.shutdown(wait=True)
        queue.close()
        self.assertEqual("failed", self.store.diary_runs(OWNER)[0]["status"])
        self.assertEqual([], self.store.diaries(OWNER))



class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name, provider_factory=FakeProvider, jobs_enabled=False, import_environment=False)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.client.post("/api/session", json={"book": OWNER})
        data = self.client.get("/api/bootstrap").json()
        self.aid = data["agents"][0]["id"]
        self.client.put("/api/settings", json={"base_url": "https://model.test/v1", "model": "test", "api_key": "private-test-key", "auto_diary": False})
        FakeProvider.calls, FakeProvider.fail = [], False

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_streaming_api_and_saved_messages(self):
        cid = self.client.post("/api/conversations", json={"agent_id": self.aid}).json()["id"]
        response = self.client.post("/api/conversations/%s/messages/stream" % cid, json={"content": "你好"})
        self.assertEqual(200, response.status_code)
        self.assertIn("event: done", response.text)
        data = self.client.get("/api/conversations/" + cid).json()
        self.assertEqual(2, len(data["messages"]))
        self.assertNotIn("request_token", str(data))

    def test_role_builder_and_settings_connection(self):
        role = self.client.post("/api/agents/design", json={"description": "一个科幻作家朋友"})
        self.assertEqual(200, role.status_code)
        self.assertEqual("星野", role.json()["name"])
        saved = self.client.post("/api/agents", json=role.json())
        self.assertEqual(200, saved.status_code)
        self.assertTrue(self.client.post("/api/settings/test", json={"base_url": "https://model.test/v1", "model": "test"}).json()["ok"])

    def test_credentials_are_never_returned_in_settings_or_validation(self):
        self.assertNotIn("private-test-key", self.client.get("/api/settings").text)
        key = "secret-" * 1000
        response = self.client.put("/api/settings", json={"api_key": key})
        self.assertEqual(422, response.status_code)
        self.assertNotIn(key, response.text)

    def test_chat_thinking_preference_is_saved_and_returned(self):
        settings = self.client.get('/api/settings').json()
        settings.update(chat_thinking=True)
        self.assertEqual(200, self.client.put('/api/settings', json=settings).status_code)
        self.assertTrue(self.client.get('/api/settings').json()['chat_thinking'])

    def test_other_workspace_has_no_history_or_secrets(self):
        cid = self.client.post("/api/conversations", json={"agent_id": self.aid}).json()["id"]
        self.client.post("/api/session", json={"book": OTHER})
        self.assertEqual(404, self.client.get("/api/conversations/" + cid).status_code)
        self.assertFalse(self.client.get("/api/settings").json()["has_api_key"])

    def test_cross_origin_mutations_and_path_traversal_are_rejected(self):
        self.assertEqual(403, self.client.post("/api/session", json={}, headers={"Origin": "https://unrelated.test"}).status_code)
        self.assertEqual(404, self.client.get("/assets/../.env").status_code)
        self.assertNotEqual(200, self.client.get("/assets/%2e%2e/%2e%2e/.env").status_code)

    def test_model_urls_reject_embedded_credentials_and_queries(self):
        for url in ("file:///etc/passwd", "https://name:secret@host.test/v1", "https://host.test/v1?key=private"):
            self.assertEqual(422, self.client.put("/api/settings", json={"base_url": url}).status_code)

    def test_diary_api_export_and_source_html_safety(self):
        cid = self.client.post("/api/conversations", json={"agent_id": self.aid}).json()["id"]
        self.client.post("/api/conversations/%s/messages/stream" % cid, json={"content": "今天完成了一个项目"})
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        response = self.client.post("/api/diaries/generate", json={"agent_id": self.aid, "day": day})
        self.assertEqual(202, response.status_code)
        diary = self.client.get("/api/diaries").json()["entries"][0]
        self.assertEqual(2, len(self.client.get("/api/diaries/" + diary["id"] + "/sources").json()))
        self.assertIn("今天的小小故事", self.client.get("/api/diaries/" + diary["id"] + "/export").text)

    def test_diary_can_be_deleted_after_its_source_chat_is_removed(self):
        cid = self.client.post('/api/conversations', json={'agent_id': self.aid}).json()['id']
        self.client.post('/api/conversations/%s/messages/stream' % cid, json={'content': '今天聊过的一件小事'})
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        self.client.post('/api/diaries/generate', json={'agent_id': self.aid, 'day': day})
        did = self.client.get('/api/diaries').json()['entries'][0]['id']
        self.client.delete('/api/conversations/' + cid)
        self.assertEqual([], self.client.get('/api/diaries/' + did + '/sources').json())
        self.assertEqual(200, self.client.delete('/api/diaries/' + did).status_code)
        self.assertEqual([], self.client.get('/api/diaries').json()['entries'])
        self.assertEqual(404, self.client.get('/api/diaries/' + did + '/export').status_code)

    def test_diary_delete_cannot_cross_workspace_boundary(self):
        cid = self.client.post('/api/conversations', json={'agent_id': self.aid}).json()['id']
        self.client.post('/api/conversations/%s/messages/stream' % cid, json={'content': '私人聊天'})
        day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        self.client.post('/api/diaries/generate', json={'agent_id': self.aid, 'day': day})
        did = self.client.get('/api/diaries').json()['entries'][0]['id']
        self.client.post('/api/session', json={'book': OTHER})
        self.assertEqual(404, self.client.delete('/api/diaries/' + did).status_code)


if __name__ == "__main__":
    unittest.main()
