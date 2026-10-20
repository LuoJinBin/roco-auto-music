from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import threading
import time

from .score import Score, ScoreError, key_events, validate_speed


@dataclass
class Timing:
    planned: float
    actual: float
    error_ms: float
    keys: tuple[str, ...]
    run: int
    speed: float = 1.0


class Player:
    def __init__(self, sink, log_dir: Path | None = None, countdown: float = 3.0):
        self.sink = sink
        self.log_dir = log_dir
        self.countdown_seconds = countdown
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = False
        self.state = "idle"
        self.message = "请先选曲或导入 MIDI。"
        self.score = None
        self.speed = 1.0
        self.pulse_ms = 30
        self.duration = 0.0
        self.events = []
        self.index = 0
        self.position = 0.0
        self.origin = 0.0
        self.deadline = 0.0
        self.timings: list[Timing] = []
        self.runs = 0
        self.focus_required = True
        self.log_path = ""
        self.thread = threading.Thread(target=self._run, name="roco-timeline", daemon=True)
        self.thread.start()

    def load(self, score: Score, pulse_ms: int = 30, speed: float = 1.0):
        speed = validate_speed(speed)
        events = key_events(score, pulse_ms, speed)
        with self.lock:
            self._halt("idle", "曲谱已就绪。进入游戏演奏界面后按 F8。", reset=True)
            self.score, self.events = score, events
            self.speed, self.pulse_ms = speed, pulse_ms
            self.duration = max(score.duration / speed, events[-1].time)
            self.timings.clear()
            self.runs = 0

    def unload(self):
        with self.lock:
            self._halt("idle", "请先选曲或导入有效的 MIDI。", reset=True)
            self.score, self.events = None, []
            self.duration = 0.0

    def set_speed(self, speed: float):
        speed = validate_speed(speed)
        with self.lock:
            if self.closed or self.speed == speed:
                return
            score, pulse = self.score, self.pulse_ms
            if score is None:
                self.speed = speed
                return
        # Build outside the scheduling lock; a large score must not stall playback.
        events = key_events(score, pulse, speed)
        with self.lock:
            if self.closed:
                return
            if self.score is not score or self.pulse_ms != pulse:
                raise ScoreError("曲谱已变化，请重新选择倍速。")
            now = time.perf_counter()
            position = max(0.0, now - self.origin) if self.state == "playing" else self.position
            position *= self.speed / speed
            # Preserve the next unsent onset by its ordinal, avoiding floating-point
            # boundary comparisons and replaying a note that has already sounded.
            sent_groups = sum(bool(e.down) for e in self.events[:self.index])
            down_indices = [i for i, e in enumerate(events) if e.down]
            index = down_indices[sent_groups] if sent_groups < len(down_indices) else len(events)
            if index < len(events):
                position = min(position, events[index].time)
            duration = max(score.duration / speed, events[-1].time)
            try:
                self.sink.release()
            except Exception:
                self._halt("error", "切换倍速时释放按键失败，已停止。")
                raise
            self.speed, self.events, self.index, self.duration = speed, events, index, duration
            self.position = duration if self.state == "finished" else min(position, duration)
            if self.state == "playing":
                self.origin = now - self.position
                self.runs += 1
            self.wake.set()

    def toggle(self):
        with self.lock:
            if self.closed:
                return
            if self.state in ("playing", "countdown"):
                self._halt("paused", "已暂停，按 F8 继续。")
                return
            if not self.score:
                self.message = "请先选曲或导入有效的九键 MIDI。"
                return
            if self.state in ("finished", "error"):
                self.position, self.index = 0.0, 0
            resume = self.state == "paused"
            if resume and not self.sink.ready():
                self.message = "请先把绑定的游戏窗口切到前台，再按 F8。"
                return
            if resume:
                try:
                    self.sink.begin()
                except Exception as exc:
                    self.message = str(exc)
                    return
                self._play()
            else:
                self.state = "countdown"
                self.deadline = time.perf_counter() + self.countdown_seconds
                self.message = "倒计时中，请切回游戏九键演奏界面。"
            self.wake.set()

    def _play(self):
        self.state = "playing"
        self.origin = time.perf_counter() - self.position
        self.runs += 1
        self.message = "正在演奏 · F8 暂停 / F9 停止"

    def _halt(self, state, message, reset=False):
        if self.state == "playing":
            now_pos = max(0.0, time.perf_counter() - self.origin)
            # Keep unsent onsets in the future on resume, never flush them in a burst.
            next_onset = next((e.time for e in self.events[self.index:] if e.down), now_pos)
            self.position = min(now_pos, next_onset)
        self.state, self.message = state, message
        if reset:
            self.position, self.index = 0.0, 0
        try:
            self.sink.release()
        except Exception as exc:
            self.state = "error"
            self.message = f"释放按键失败：{exc}。请手动松开游戏按键并停止使用。"
        self.wake.set()

    def pause(self, message="已暂停。"):
        with self.lock:
            if self.state in ("playing", "countdown"):
                self._halt("paused", message)

    def stop(self):
        with self.lock:
            self._halt("idle", "已停止并回到开头。按 F8 重新演奏。", reset=True)

    def snapshot(self):
        with self.lock:
            pos = min(self.duration, max(0.0, time.perf_counter() - self.origin)) if self.state == "playing" and self.score else self.position
            source_duration = self.score.duration if self.score else 0
            return {"state": self.state, "message": self.message, "position": pos, "duration": self.duration, "score_position": min(source_duration, pos * self.speed), "source_duration": source_duration, "speed": self.speed, "countdown": max(0, math.ceil(self.deadline - time.perf_counter())) if self.state == "countdown" else 0, "sent": len(self.timings)}

    def _run(self):
        # 1 ms timer resolution only while this process is alive. Always restored.
        winmm = None
        try:
            if hasattr(ctypes, "WinDLL"):
                winmm = ctypes.WinDLL("winmm")
                winmm.timeBeginPeriod(1)
            while not self.closed:
                wait = .02
                with self.lock:
                    now = time.perf_counter()
                    if self.state == "countdown":
                        if now >= self.deadline:
                            if not self.sink.ready():
                                self._halt("paused", "游戏不在前台，已暂停。切回游戏后按 F8。")
                            else:
                                try:
                                    self.sink.begin()
                                    self._play()
                                except Exception as exc:
                                    self._halt("paused", str(exc))
                        wait = .005
                    elif self.state == "playing":
                        if not self.sink.ready():
                            self._halt("paused", "游戏已失去前台，自动暂停。切回游戏后按 F8 继续。")
                        else:
                            elapsed = now - self.origin
                            if self.index < len(self.events):
                                event = self.events[self.index]
                                delta = event.time - elapsed
                                if delta <= 0:
                                    if event.down and -delta > .100:
                                        self._halt("paused", "系统调度落后超过 100 毫秒，已暂停，避免突发补音。按 F8 从未发送音符继续。")
                                    else:
                                        try:
                                            self.sink.send(event.up, event.down)
                                            actual = time.perf_counter() - self.origin
                                            if event.down:
                                                self.timings.append(Timing(event.time, actual, (actual - event.time) * 1000, event.down, self.runs, self.speed))
                                            self.index += 1
                                        except Exception as exc:
                                            if exc.__class__.__name__ == "FocusLost":
                                                self._halt("paused", str(exc))
                                            else:
                                                self._halt("error", str(exc))
                                    wait = 0
                                else:
                                    wait = min(.003, max(0.0, delta - .0005))
                            elif elapsed >= self.duration:
                                self.position = self.duration
                                self._halt("finished", "本曲已播放完，已停止。按 F8 从头重播。")
                                self.position = self.duration
                            else:
                                wait = .003
                if wait > 0:
                    self.wake.wait(wait)
                    self.wake.clear()
                else:
                    # Event and short precision waits yield briefly without a full timer tick.
                    time.sleep(0)
        except Exception as exc:
            with self.lock:
                self._halt("error", f"演奏线程异常：{exc}")
        finally:
            try:
                self.sink.release()
            finally:
                if winmm:
                    winmm.timeEndPeriod(1)

    def export_log(self) -> Path | None:
        if not self.log_dir:
            return None
        with self.lock:
            data = {"score": self.score.title if self.score else "", "source": self.score.source if self.score else "", "version": self.score.version if self.score else "", "sha256": self.score.sha256 if self.score else "", "speed": self.speed, "source_duration": self.score.duration if self.score else 0, "playback_duration": self.duration, "state": self.state, "message": self.message, "note": "时间为 Windows 调用完成时刻；各起音记录对应倍速，切换倍速另记调度段。不能证明游戏已收键或实际发声。", "summary": timing_summary(self.timings), "onsets": [asdict(t) for t in self.timings]}
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / (time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1000000:06d}.json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log_path = str(path)
        return path

    def close(self):
        with self.lock:
            if self.closed:
                return
            self._halt("idle", "已退出。", reset=True)
            self.closed = True
            self.wake.set()
        self.thread.join(3)
        if hasattr(self.sink, "close"):
            self.sink.close()
        self.export_log()


def timing_summary(timings):
    errors = sorted(abs(t.error_ms) for t in timings)
    if not errors:
        return {"count": 0}
    runs = {}
    for t in timings:
        runs.setdefault(t.run, []).append(t)
    drift = max(abs(group[-1].error_ms - group[0].error_ms) for group in runs.values())
    return {"count": len(errors), "p95_ms": errors[max(0, math.ceil(len(errors) * .95) - 1)], "max_ms": errors[-1], "drift_ms": drift, "runs": len(runs)}
