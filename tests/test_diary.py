"""Real scheduling behavior and diary evidence checks with a controllable clock."""
import datetime as dt
import json
import time
import unittest
from unittest.mock import Mock, patch
import test_app
from test_app import FakeProvider, OWNER
from src.diary_queue import DiaryQueue
from src.models import ModelSettings
from src.provider import ProviderError


class ManualTime:
    def __init__(self):
        self.now, self.timers = 0, []
        self.wall_start = time.time()

    def clock(self):
        return self.now

    def wall_clock(self):
        return self.wall_start + self.now

    def timer(self, delay, callback):
        timer = Mock()
        timer.due, timer.callback, timer.cancelled, timer.fired = self.now + delay, callback, False, False
        timer.cancel.side_effect = lambda: setattr(timer, "cancelled", True)
        self.timers.append(timer)
        return timer

    def advance(self, seconds):
        self.now += seconds
        while True:
            due = next((t for t in self.timers if not t.cancelled and not t.fired and t.due <= self.now), None)
            if due is None:
                return
            due.fired = True
            due.callback()


class DiaryTests(unittest.TestCase):
    setUp = test_app.CoreTests.setUp
    send = test_app.CoreTests.send

    def tearDown(self):
        if self.services.diary_queue:
            self.services.diary_queue.close()
            self.services.diary_queue.pool.shutdown(wait=True)
        test_app.CoreTests.tearDown(self)

    def day(self):
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()

    def scheduler(self):
        self.services.save_settings(OWNER, ModelSettings(base_url="https://model.test/v1", model="test", auto_diary=True))
        self.time = ManualTime()
        queue = DiaryQueue(self.services, clock=self.time.clock, wall_clock=self.time.wall_clock, timer_factory=self.time.timer)
        self.services.diary_queue = queue
        self.generate = Mock(wraps=self.services.generate_diary)
        self.services.generate_diary = self.generate
        return queue

    def wait_complete(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            queue = self.services.diary_queue
            with queue.lock:
                active = any(state["running"] for state in queue.jobs.values())
            if not active:
                return
            time.sleep(0.005)
        self.fail("Background diary did not complete")

    def test_continuous_chat_costs_nothing_until_ten_minutes_idle(self):
        self.scheduler()
        self.send("先聊一件事")
        self.time.advance(300)
        self.send("再补一点")
        self.time.advance(599)
        self.assertEqual(0, self.generate.call_count)
        self.assertEqual("scheduled", self.store.diary_runs(OWNER)[0]["status"])
        self.time.advance(1)
        self.wait_complete()
        self.assertEqual(1, self.generate.call_count)
        self.assertEqual(4, len(self.store.diaries(OWNER)[0]["sources"]))

    def test_hourly_limit_survives_more_messages(self):
        self.scheduler()
        self.send("第一段")
        self.time.advance(600)
        self.wait_complete()
        self.send("后面又聊了一些")
        self.time.advance(600)
        self.assertEqual(1, self.generate.call_count)
        self.time.advance(3000)
        self.wait_complete()
        self.assertEqual(2, self.generate.call_count)

    def test_manual_request_bypasses_delay_and_cancels_duplicate_timer(self):
        queue = self.scheduler()
        self.send("值得记下的一句")
        queue.submit(OWNER, self.aid, self.day(), force=True)
        self.wait_complete()
        self.assertEqual(1, self.generate.call_count)
        self.time.advance(600)
        self.assertEqual(1, self.generate.call_count)
        queue.submit(OWNER, self.aid, self.day(), force=True)
        self.wait_complete()
        self.assertEqual(2, self.generate.call_count)

    def test_disabling_auto_diary_cancels_pending_model_call(self):
        self.scheduler()
        self.send("先不要自动整理")
        self.services.save_settings(OWNER, ModelSettings(base_url="https://model.test/v1", model="test", auto_diary=False))
        self.time.advance(3600)
        self.assertEqual(0, self.generate.call_count)
        self.assertEqual("cancelled", self.store.diary_runs(OWNER)[0]["status"])

    def test_shutdown_cancels_pending_work(self):
        queue = self.scheduler()
        self.send("稍后再整理")
        queue.close()
        self.time.advance(3600)
        self.assertEqual(0, self.generate.call_count)

    def test_deleted_diary_stays_deleted_after_new_chat_and_restart(self):
        self.send('今天聊过的事')
        entry = self.services.generate_diary(OWNER, self.aid, self.day())
        self.store.delete_diary(OWNER, entry['id'])
        self.scheduler()
        self.send('又聊了一句')
        self.time.advance(7200)
        self.assertEqual(0, self.generate.call_count)
        self.assertEqual([], self.store.diaries(OWNER))
        # Explicit regeneration is still available while source messages exist.
        restored = self.services.generate_diary(OWNER, self.aid, self.day(), force=True)
        self.assertIsNotNone(restored)
        self.assertFalse(self.store.diary_generation_state(OWNER, self.aid, self.day())['deleted'])

    def test_deleting_during_generation_discards_late_result(self):
        self.send('留在日记里的事')
        entry = self.services.generate_diary(OWNER, self.aid, self.day())
        original = FakeProvider.complete

        def delete_while_generating(provider, messages, structured=False):
            self.store.delete_diary(OWNER, entry['id'])
            return original(provider, messages, structured)

        with patch.object(FakeProvider, 'complete', delete_while_generating):
            with self.assertRaisesRegex(ValueError, '日记已删除'):
                self.services.generate_diary(OWNER, self.aid, self.day(), force=True)
        self.assertEqual([], self.store.diaries(OWNER))

    def test_old_queued_manual_job_cannot_recreate_deleted_diary(self):
        self.send('曾经说过')
        entry = self.services.generate_diary(OWNER, self.aid, self.day())
        revision = self.store.diary_generation_state(OWNER, self.aid, self.day())['revision']
        self.store.delete_diary(OWNER, entry['id'])
        calls = len(FakeProvider.calls)
        self.assertIsNone(self.services.generate_diary(OWNER, self.aid, self.day(), force=True, expected_revision=revision))
        self.assertEqual(calls, len(FakeProvider.calls))
        self.assertEqual([], self.store.diaries(OWNER))

    def test_restart_does_not_ignore_persisted_hourly_limit(self):
        self.send("先前聊过")
        self.services.generate_diary(OWNER, self.aid, self.day())
        self.scheduler()
        self.send("重启以后又说了一句")
        self.time.advance(600)
        self.assertEqual(0, self.generate.call_count)
        self.time.advance(3001)
        self.wait_complete()
        self.assertEqual(1, self.generate.call_count)

    def test_role_lore_is_not_a_diary_source(self):
        agent = self.store.agent(OWNER, self.aid)
        self.store.save_agent(OWNER, dict(agent, instructions="角色背景：LORE_ONLY_SENTINEL，曾去月球开咖啡店。"), self.aid)
        self.send("记住我说的：我不喜欢被叫老师")
        self.services.generate_diary(OWNER, self.aid, self.day())
        context = FakeProvider.calls[-1]
        material = json.loads(context[-1]["content"])
        self.assertIn("LORE_ONLY_SENTINEL", material["character_reference"]["instructions"])
        self.assertNotIn("LORE_ONLY_SENTINEL", str(material["messages"]))
        self.assertIn("我不喜欢被叫老师", str(material["messages"]))
        self.assertIn("事件证据只在messages或notes里", context[0]["content"])

    def test_failed_attempt_still_limits_automatic_retries_after_restart(self):
        queue = self.scheduler()
        self.send("有一句想记下来")
        FakeProvider.fail = True
        queue.submit(OWNER, self.aid, self.day(), force=True)
        self.wait_complete()
        self.assertEqual("failed", self.store.diary_runs(OWNER)[0]["status"])
        queue.close()
        queue.pool.shutdown(wait=True)
        self.services.diary_queue = None
        self.services.generate_diary = self.generate._mock_wraps
        FakeProvider.fail = False
        self.scheduler()
        self.send("重启后继续说")
        self.time.advance(600)
        self.assertEqual(0, self.generate.call_count)
        self.time.advance(3001)
        self.wait_complete()
        self.assertEqual(1, self.generate.call_count)

    def test_invalid_or_assistant_only_evidence_does_not_overwrite_old_diary(self):
        self.send("我们聊过一句话")
        previous = self.services.generate_diary(OWNER, self.aid, self.day())
        original = FakeProvider.complete
        for evidence in ([999], [2]):
            def invalid(provider, messages, structured=False):
                draft = json.loads(original(provider, messages, structured))
                draft["source_indices"] = evidence
                return json.dumps(draft)
            with self.subTest(evidence=evidence), patch.object(FakeProvider, "complete", invalid):
                with self.assertRaises(ProviderError):
                    self.services.generate_diary(OWNER, self.aid, self.day(), force=True)
            self.assertEqual(previous["updated_at"], self.store.diary_for_day(OWNER, self.aid, self.day())["updated_at"])

    def test_selected_sources_keep_full_hash_to_avoid_repeated_generation(self):
        self.send("第一件小事")
        self.send("第二件小事")
        original = FakeProvider.complete
        def selected(provider, messages, structured=False):
            draft = json.loads(original(provider, messages, structured))
            draft["source_indices"] = [1, 2]
            return json.dumps(draft)
        with patch.object(FakeProvider, "complete", selected):
            diary = self.services.generate_diary(OWNER, self.aid, self.day())
        self.assertEqual(2, len(diary["sources"]))
        count = len(FakeProvider.calls)
        self.services.generate_diary(OWNER, self.aid, self.day())
        self.assertEqual(count, len(FakeProvider.calls))

    def test_long_chat_preserves_source_indices_through_notes(self):
        self.send("你先记下第一件事。" + "甲" * 6000)
        self.send("还有第二件事。" + "乙" * 6000)
        diary = self.services.generate_diary(OWNER, self.aid, self.day())
        self.assertEqual(4, len(diary["sources"]))
        self.assertEqual(3, sum("摘取有来源的回忆素材" in call[0]["content"] or "对话日记" in call[0]["content"] for call in FakeProvider.calls))

    def test_overlong_generation_preserves_previous_entry_without_truncating(self):
        self.send("记下一件小事")
        previous = self.services.generate_diary(OWNER, self.aid, self.day())
        original = FakeProvider.complete
        def too_long(provider, messages, structured=False):
            draft = json.loads(original(provider, messages, structured))
            draft["content"] = "长" * 241
            return json.dumps(draft)
        with patch.object(FakeProvider, "complete", too_long):
            with self.assertRaises(ValueError):
                self.services.generate_diary(OWNER, self.aid, self.day(), force=True)
        self.assertEqual(previous["content"], self.store.diary_for_day(OWNER, self.aid, self.day())["content"])
