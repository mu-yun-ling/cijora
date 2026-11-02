"""Check the prompt path for existing characters, editing and regeneration."""
from src.prompts import DEFAULT_PROMPT, LEGACY_DEFAULT_PROMPT, PREVIOUS_DEFAULT_PROMPT
import unittest
import json
import test_app
from test_app import FakeProvider, OWNER


class VoiceTests(unittest.TestCase):
    setUp = test_app.CoreTests.setUp
    tearDown = test_app.CoreTests.tearDown
    send = test_app.CoreTests.send

    def test_untouched_legacy_default_gets_new_voice_without_mutating_saved_agent(self):
        original = self.store.agent(OWNER, self.aid)
        self.store.save_agent(OWNER, dict(original, instructions=LEGACY_DEFAULT_PROMPT), self.aid)
        self.send("今天终于交完作业了")
        self.assertIn(DEFAULT_PROMPT, FakeProvider.calls[-1][0]["content"])
        self.assertEqual(LEGACY_DEFAULT_PROMPT, self.store.agent(OWNER, self.aid)["instructions"])

    def test_custom_voice_and_explicit_output_request_survive_retry_and_regeneration(self):
        original = self.store.agent(OWNER, self.aid)
        custom = "请用简短的文言文交谈。教学时详细展开。"
        self.store.save_agent(OWNER, dict(original, instructions=custom), self.aid)
        FakeProvider.fail = True
        mid, _ = self.send("请分步骤解释递归")
        FakeProvider.fail = False
        list(self.services.chat_events(OWNER, self.cid, mid))
        list(self.services.chat_events(OWNER, self.cid, mid, regenerate=True))
        for context in FakeProvider.calls:
            self.assertIn("角色设定：\n" + custom, context[0]["content"])
            self.assertEqual("请分步骤解释递归", context[-1]["content"])
            self.assertNotIn(DEFAULT_PROMPT, context[0]["content"])

    def test_custom_agent_with_same_text_is_not_silently_rewritten(self):
        original = self.store.agent(OWNER, self.aid)
        self.store.save_agent(OWNER, dict(original, name="自定义助手", instructions=LEGACY_DEFAULT_PROMPT), self.aid)
        self.send("你好")
        self.assertIn("角色设定：\n" + LEGACY_DEFAULT_PROMPT, FakeProvider.calls[-1][0]["content"])
        self.assertNotIn(DEFAULT_PROMPT, FakeProvider.calls[-1][0]["content"])

    def test_previous_default_voice_is_upgraded_without_rewriting_saved_data(self):
        original = self.store.agent(OWNER, self.aid)
        self.store.save_agent(OWNER, dict(original, instructions=PREVIOUS_DEFAULT_PROMPT), self.aid)
        self.send("最近有点烦")
        self.assertIn(DEFAULT_PROMPT, FakeProvider.calls[-1][0]["content"])
        self.assertNotIn(PREVIOUS_DEFAULT_PROMPT, FakeProvider.calls[-1][0]["content"])
        self.assertEqual(PREVIOUS_DEFAULT_PROMPT, self.store.agent(OWNER, self.aid)["instructions"])

    def test_existing_history_is_kept_and_replies_are_not_filtered_or_rewritten(self):
        first, _ = self.send("我有个烦恼")
        self.send("先前说到哪了")
        history = [m for m in FakeProvider.calls[-1] if m["role"] != "system"]
        self.assertEqual(["user", "assistant", "user"], [m["role"] for m in history])
        self.assertEqual("你好，我在听。", history[1]["content"])
        self.assertEqual("我有个烦恼", history[0]["content"])
        self.assertEqual("先前说到哪了", history[2]["content"])
        self.assertEqual(2, len(FakeProvider.calls))

    def test_new_conversation_memory_uses_attributed_sources_not_diary_prose(self):
        mid, _ = self.send("我体测59.1，后来体前屈从18到24就及格了")
        sources = self.store.messages(OWNER, self.cid)
        self.store.save_diary(OWNER, self.aid, "2026-11-01", {
            "title": "体测", "summary": "我体测59.1，这是角色自己的经历 WRONG_OWNER",
            "content": "错误的旧日记正文 WRONG_BODY", "tags": ["体测"]}, sources)
        cid = self.store.create_conversation(OWNER, self.aid)["id"]
        self.send("昨天下午我去体测，一看成绩59.1更绝望了", cid)
        context = FakeProvider.calls[-1]
        memory = json.loads(context[1]["content"].split("\n")[-1])
        quotes = memory["past_dialogue_evidence"][0]["source_messages"]
        self.assertEqual("user", quotes[0]["speaker"])
        self.assertEqual(sources[0]["content"], quotes[0]["quote"])
        self.assertEqual("assistant", quotes[1]["speaker"])
        self.assertNotIn("WRONG_OWNER", str(context))
        self.assertNotIn("WRONG_BODY", str(context))
        self.assertEqual(["user"], [m["role"] for m in context if m["role"] != "system"])

    def test_missing_diary_sources_keep_legacy_memory_with_explicit_attribution(self):
        self.store.save_diary(OWNER, self.aid, "2026-11-01", {
            "title": "旧日记", "summary": "你体测59.1，后来体前屈18到24及格了",
            "content": "旧正文", "tags": []}, [])
        self.send("我体测没过")
        context = FakeProvider.calls[-1]
        memory = json.loads(context[1]["content"].split("\n")[-1])
        legacy = memory["past_dialogue_evidence"][0]["legacy_summary"]
        self.assertIn("18到24", legacy["text"])
        self.assertIn("不可核对", legacy["status"])
        self.assertIn("user", legacy["pronouns"]["你"])
        self.assertIn("不代表亲历事件", legacy["pronouns"]["我"])

    def test_current_chat_diary_is_not_injected_again_on_regeneration(self):
        first, _ = self.send('我还没考完')
        self.send('考完了，已经通过')
        sources = self.store.messages(OWNER, self.cid)
        self.store.save_diary(OWNER, self.aid, '2026-11-01', {
            'title': '考试', 'summary': '用户已经通过', 'content': '通过了', 'tags': []}, sources)
        _, _, context = self.services.build_context(OWNER, self.cid, first)
        self.assertEqual(['system', 'user'], [m['role'] for m in context])
        self.assertNotIn('已经通过', str(context))

    def test_mixed_diary_keeps_only_other_conversations_as_memory(self):
        self.send('这段是当前聊天 ONLY_CURRENT')
        current = self.store.messages(OWNER, self.cid)
        other_cid = self.store.create_conversation(OWNER, self.aid)['id']
        self.send('另一段聊天 OTHER_CHAT', other_cid)
        self.store.save_diary(OWNER, self.aid, '2026-11-01', {
            'title': '聊天', 'summary': '摘要', 'content': '正文', 'tags': []},
            current + self.store.messages(OWNER, other_cid))
        first = current[0]['id']
        _, _, context = self.services.build_context(OWNER, self.cid, first)
        memory = json.loads(context[1]['content'].split('\n')[-1])
        self.assertIn('OTHER_CHAT', str(memory))
        self.assertNotIn('ONLY_CURRENT', str(memory))
