from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from io import BytesIO
import math
from pathlib import Path

import mido

KEY_MAP = {45: "B", 52: "F", 53: "G", 55: "H", 57: "J", 59: "K", 60: "T", 62: "Y", 64: "U"}
MAX_MIDI_BYTES = 5 * 1024 * 1024
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def validate_speed(speed: float) -> float:
    try:
        speed = float(speed)
    except (ValueError, TypeError):
        raise ScoreError("倍速请选择 0.5×、0.75×、1×、1.25×、1.5× 或 2×。") from None
    if speed not in SPEEDS:
        raise ScoreError("倍速请选择 0.5×、0.75×、1×、1.25×、1.5× 或 2×。")
    return speed


class ScoreError(ValueError):
    pass


@dataclass(frozen=True)
class Note:
    pitch: int
    start: float
    duration: float
    track: int = 0
    velocity: int = 80


@dataclass
class Score:
    title: str
    notes: list[Note]
    duration: float
    tempos: list[tuple[float, float]] = field(default_factory=list)
    source: str = ""
    version: str = ""
    sha256: str = ""

    @property
    def unsupported(self) -> Counter:
        return Counter(n.pitch for n in self.notes if n.pitch not in KEY_MAP)

    @property
    def duplicate_onsets(self) -> int:
        return len(self.notes) - len({(n.start, n.pitch) for n in self.notes})

    def validate(self) -> None:
        if not self.notes:
            raise ScoreError("曲谱没有可演奏的音符。")
        if not math.isfinite(self.duration) or self.duration <= 0:
            raise ScoreError("曲谱时长无效。")
        if len(self.notes) > 200_000 or self.duration > 24 * 3600:
            raise ScoreError("曲谱超过 20 万音符或 24 小时，无法载入。")
        for n in self.notes:
            if not all(math.isfinite(x) for x in (n.start, n.duration)) or n.start < 0 or n.duration < 0:
                raise ScoreError("曲谱包含无效的时间数据。")
        if self.unsupported:
            detail = "、".join(f"{note_name(p)}(MIDI {p}) ×{c}" for p, c in sorted(self.unsupported.items()))
            raise ScoreError(f"有 {sum(self.unsupported.values())} 个音符超出游戏九键范围：{detail}。请先在网站转谱并导出 MIDI，不会自动改音或丢音。")


def note_name(pitch: int) -> str:
    return f"{('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')[pitch % 12]}{pitch // 12 - 1}"


def load_midi(data: bytes, title: str = "本地曲谱", source: str = "", version: str = "") -> Score:
    import hashlib
    if len(data) > MAX_MIDI_BYTES:
        raise ScoreError("MIDI 文件超过 5 MB。")
    if not data.startswith(b"MThd"):
        raise ScoreError("文件不是有效的标准 MIDI（缺少 MThd 文件头）。")
    try:
        midi = mido.MidiFile(file=BytesIO(data))
        if midi.type not in (0, 1):
            raise ScoreError("暂不支持各轨独立计时的 MIDI Type 2，请导出为 Type 0 或 Type 1。")
        if midi.ticks_per_beat <= 0:
            raise ScoreError("暂不支持 SMPTE 计时的 MIDI，请导出为 PPQN 计时。")
        events = []
        for track_id, track in enumerate(midi.tracks):
            tick = 0
            for order, message in enumerate(track):
                tick += message.time
                events.append((tick, track_id, order, message))
        events.sort(key=lambda e: (e[0], e[1], e[2]))
        active = defaultdict(deque)
        notes: list[Note] = []
        tempo, tick, elapsed = 500_000, 0, 0.0
        tempos = [(0.0, 120.0)]
        for current, track_id, _, message in events:
            elapsed += mido.tick2second(current - tick, midi.ticks_per_beat, tempo)
            tick = current
            if message.type == "set_tempo":
                if message.tempo <= 0:
                    raise ScoreError("MIDI 含有无效速度。")
                tempo = message.tempo
                tempos.append((elapsed, 60_000_000 / tempo))
            elif message.type == "note_on" and message.velocity > 0:
                active[(track_id, message.channel, message.note)].append((elapsed, message.velocity))
            elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
                pending = active[(track_id, message.channel, message.note)]
                if pending:
                    start, velocity = pending.popleft()
                    notes.append(Note(message.note, start, max(0.0, elapsed - start), track_id, velocity))
        for (track_id, _, pitch), pending in active.items():
            for start, velocity in pending:
                notes.append(Note(pitch, start, max(0.0, elapsed - start), track_id, velocity))
        notes.sort(key=lambda n: (n.start, n.pitch, n.track))
        duration = max(elapsed, max((n.start + n.duration for n in notes), default=0))
        # A zero-duration final note still needs room for the physical key pulse.
        duration = max(duration, max((n.start + .031 for n in notes), default=0))
        score = Score(title, notes, duration, tempos, source, version, hashlib.sha256(data).hexdigest())
        if not notes:
            raise ScoreError("MIDI 文件没有音符。")
        return score
    except ScoreError:
        raise
    except Exception as exc:
        raise ScoreError(f"无法解析 MIDI：{exc}") from exc


def load_file(path: str | Path) -> Score:
    path = Path(path)
    if path.suffix.lower() not in (".mid", ".midi"):
        raise ScoreError("第一版只支持 .mid / .midi 文件。")
    if path.stat().st_size > MAX_MIDI_BYTES:
        raise ScoreError("MIDI 文件超过 5 MB。")
    return load_midi(path.read_bytes(), path.stem, str(path.resolve()))


@dataclass(frozen=True)
class KeyEvent:
    time: float
    down: tuple[str, ...] = ()
    up: tuple[str, ...] = ()


def key_events(score: Score, pulse_ms: int = 30, speed: float = 1.0) -> list[KeyEvent]:
    score.validate()
    speed = validate_speed(speed)
    if not 10 <= pulse_ms <= 100:
        raise ScoreError("按压时长应为 10–100 毫秒。")
    by_key = defaultdict(set)
    for n in score.notes:
        by_key[KEY_MAP[n.pitch]].add(n.start / speed)
    changes = defaultdict(lambda: {"down": [], "up": []})
    for key, starts in by_key.items():
        ordered = sorted(starts)
        for i, start in enumerate(ordered):
            end = start + pulse_ms / 1000
            if i + 1 < len(ordered):
                gap = ordered[i + 1] - start
                if gap < .004 - 1e-9:
                    raise ScoreError(f"{key} 键在 {start:.3f} 秒附近的重复音间隔小于 4 毫秒，无法可靠直奏。")
                end = min(end, ordered[i + 1] - .002)
            changes[start]["down"].append(key)
            changes[end]["up"].append(key)
    return [KeyEvent(t, tuple(sorted(c["down"])), tuple(sorted(c["up"]))) for t, c in sorted(changes.items())]
