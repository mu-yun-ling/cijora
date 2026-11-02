"""Debounce automatic diaries; explicit requests always run immediately."""
import datetime as dt
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .provider import ProviderError


class DiaryQueue:
    def __init__(self, services, idle_seconds=600, min_interval_seconds=3600,
                 clock=time.monotonic, wall_clock=time.time, timer_factory=threading.Timer):
        self.services, self.store = services, services.store
        self.idle_seconds, self.min_interval_seconds = idle_seconds, min_interval_seconds
        self.clock, self.wall_clock, self.timer_factory = clock, wall_clock, timer_factory
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="diary")
        self.lock, self.jobs, self.cooldowns = threading.Lock(), {}, {}
        self.stopped = False

    def submit(self, owner, aid, day, force=False):
        key = (owner, aid, day)
        with self.lock:
            if self.stopped:
                return
            if not force and self.store.diary_generation_state(*key)['deleted']:
                return
            state = self.jobs.get(key)
            if state is None:
                entry = self.store.diary_for_day(*key)
                if not force and entry:
                    config = self.services.public_settings(owner)
                    sources = self.store.daily_messages(*key, config["offset_minutes"])
                    if entry["source_hash"] == self.store.source_hash(sources):
                        self.store.diary_status(*key, "complete")
                        return
                if key not in self.cooldowns:
                    previous = [self.store.diary_last_attempt(*key)]
                    if entry:
                        previous.append(entry["updated_at"])
                    timestamps = [dt.datetime.fromisoformat(stamp).timestamp() for stamp in previous if stamp]
                    if timestamps:
                        elapsed = self.wall_clock() - max(timestamps)
                        self.cooldowns[key] = self.clock() + max(0, self.min_interval_seconds - elapsed)
                state = {"running": False, "dirty": False, "force": False,
                         "last_activity": self.clock(), "timer": None, "ticket": None}
                self.jobs[key] = state
            state["dirty"] = True
            state["force"] |= force
            state["last_activity"] = self.clock()
            if not state["running"]:
                self._schedule_locked(key, state)

    def _schedule_locked(self, key, state):
        if state["timer"]:
            state["timer"].cancel()
        due = self.clock() if state["force"] else max(
            state["last_activity"] + self.idle_seconds, self.cooldowns.get(key, 0))
        delay = max(0, due - self.clock())
        if delay == 0:
            state["timer"], state["ticket"] = None, None
            force = state["force"]
            state.update(running=True, dirty=False, force=False)
            self.store.diary_status(*key, "queued")
            revision = self.store.diary_generation_state(*key)['revision']
            self.pool.submit(self._run, key, state, force, revision)
            return
        ticket = object()
        state["ticket"] = ticket
        self.store.diary_status(*key, "scheduled")
        timer = self.timer_factory(delay, lambda: self._timer_due(key, ticket))
        timer.daemon = True
        state["timer"] = timer
        timer.start()

    def _timer_due(self, key, ticket):
        with self.lock:
            state = self.jobs.get(key)
            if self.stopped or not state or state["ticket"] is not ticket:
                return
            state["timer"] = None
            if self.store.diary_generation_state(*key)['deleted'] and not state['force']:
                self.jobs.pop(key, None)
                return
            if not self.services.public_settings(key[0])["auto_diary"]:
                self.jobs.pop(key, None)
                self.store.diary_status(*key, "cancelled")
                return
            self._schedule_locked(key, state)

    def _run(self, key, state, force, revision):
        try:
            if self.store.diary_generation_state(*key)['revision'] != revision:
                return
            if not force and not self.services.public_settings(key[0])["auto_diary"]:
                self.store.diary_status(*key, "cancelled")
                return
            with self.lock:
                self.cooldowns[key] = self.clock() + self.min_interval_seconds
            started_at = dt.datetime.fromtimestamp(self.wall_clock(), dt.timezone.utc).isoformat()
            self.store.record_diary_attempt(*key, started_at)
            self.store.diary_status(*key, "running")
            self.services.generate_diary(*key, force=force, expected_revision=revision)
            if self.store.diary_generation_state(*key)['revision'] == revision:
                self.store.diary_status(*key, "complete")
        except Exception as exc:
            error = str(exc) if isinstance(exc, (ProviderError, ValueError)) else "日记整理失败，请稍后重试"
            if self.store.diary_generation_state(*key)['revision'] == revision:
                self.store.diary_status(*key, "failed", error)
        finally:
            with self.lock:
                if self.jobs.get(key) is state:
                    state["running"] = False
                    if state["dirty"] and not self.stopped and not self.store.diary_generation_state(*key)['deleted']:
                        self._schedule_locked(key, state)
                    else:
                        self.jobs.pop(key, None)

    def cancel_day(self, owner, aid, day):
        key = (owner, aid, day)
        with self.lock:
            state = self.jobs.get(key)
            if state:
                state['dirty'] = False
                state['force'] = False
                if state['timer']:
                    state['timer'].cancel()
                if not state['running']:
                    self.jobs.pop(key, None)

    def cancel_automatic(self, owner):
        with self.lock:
            for key, state in list(self.jobs.items()):
                if key[0] != owner or state["force"]:
                    continue
                if state["running"]:
                    state["dirty"] = False
                else:
                    if state["timer"]:
                        state["timer"].cancel()
                    self.jobs.pop(key, None)
                    self.store.diary_status(*key, "cancelled")

    def close(self):
        with self.lock:
            self.stopped = True
            for state in self.jobs.values():
                if state["timer"]:
                    state["timer"].cancel()
        self.pool.shutdown(wait=False)
