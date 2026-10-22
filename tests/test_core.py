from io import BytesIO
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rocomusic.score import KEY_MAP, Note, Score, ScoreError, UnsupportedNotes, key_events, load_midi
from rocomusic.player import Player
from rocomusic.catalog import CatalogClient, SiteBlocked, SiteError, download_link, parse_library, validate_url, validate_destination, FILE_HOST


def midi_bytes(tracks, kind=1):
    mid = mido.MidiFile(type=kind, ticks_per_beat=480)
    for messages in tracks:
        mid.tracks.append(mido.MidiTrack(messages))
    stream = BytesIO()
    mid.save(file=stream)
    return stream.getvalue()


class MidiTests(unittest.TestCase):
    def test_multitrack_tempo_and_rests(self):
        data = midi_bytes([
            [mido.MetaMessage("set_tempo", tempo=500000), mido.MetaMessage("set_tempo", tempo=1000000, time=480), mido.MetaMessage("end_of_track", time=960)],
            [mido.Message("note_on", note=52, velocity=70), mido.Message("note_off", note=52, time=480), mido.Message("note_on", note=55, time=480), mido.Message("note_on", note=55, velocity=0, time=480)],
            [mido.Message("note_on", note=60, velocity=80, time=960), mido.Message("note_off", note=60, time=240)],
        ])
        score = load_midi(data)
        self.assertEqual(len(score.notes), 3)
        self.assertAlmostEqual(score.notes[0].duration, .5)
        self.assertAlmostEqual(score.notes[1].start, 1.5)
        self.assertAlmostEqual(score.duration, 2.5)
        self.assertEqual(next(e for e in key_events(score) if abs(e.time - 1.5) < 1e-8).down, ("H", "T"))

    def test_single_track_and_full_length(self):
        data = midi_bytes([[mido.Message("note_on", note=45, time=480*240), mido.Message("note_off", note=45, time=480)]], kind=0)
        score = load_midi(data)
        self.assertAlmostEqual(score.notes[0].start, 120)
        self.assertGreater(score.duration, 120)

    def test_overlap_rearticulates(self):
        score = Score("重复", [Note(52, 0, 2), Note(52, .020, 2)], 2.1)
        events = key_events(score)
        self.assertAlmostEqual(events[1].time, .018)
        self.assertEqual(events[1].up, ("F",))
        self.assertEqual(events[2].down, ("F",))

    def test_unsupported_blocked_without_dropping(self):
        score = Score("不兼容", [Note(52, 0, 1), Note(54, 1, 1)], 2)
        with self.assertRaises(UnsupportedNotes) as raised:
            key_events(score)
        self.assertEqual(raised.exception.counts, {54: 1})
        self.assertEqual(len(score.notes), 2)

    def test_simultaneous_duplicate_coalesced(self):
        score = Score("同音多轨", [Note(52, 0, 1, 0), Note(52, 0, 1, 1)], 1)
        self.assertEqual(score.duplicate_onsets, 1)
        self.assertEqual(key_events(score)[0].down, ("F",))

    def test_dense_same_key_blocked(self):
        with self.assertRaises(ScoreError):
            key_events(Score("密集", [Note(52, 0, 1), Note(52, .001, 1)], 1))

    def test_corrupt_empty_and_type2(self):
        with self.assertRaises(ScoreError): load_midi(b"not a midi")
        with self.assertRaises(ScoreError): load_midi(b"MThd\x00")
        with self.assertRaises(ScoreError): load_midi(midi_bytes([[]]))
        with self.assertRaisesRegex(ScoreError, "Type 2"): load_midi(midi_bytes([[]], 2))


class FakeSink:
    def __init__(self):
        self.focus = True
        self.held = set()
        self.calls = []
        self.delay = 0
    def ready(self): return self.focus
    def begin(self): pass
    def send(self, up=(), down=()):
        if down and not self.focus: raise RuntimeError("focus")
        if down and self.delay: time.sleep(self.delay)
        self.held.difference_update(up)
        self.held.update(down)
        self.calls.append((time.perf_counter(), tuple(up), tuple(down)))
    def release(self): self.held.clear()


def wait_for(predicate, timeout=2):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate(): return
        time.sleep(.002)
    raise AssertionError("timed out")


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.sink = FakeSink()
        self.player = Player(self.sink, countdown=.03)
        self.player.load(Score("测试", [Note(52, .01, .1), Note(55, .15, .1), Note(57, .30, .1)], .45))
    def tearDown(self): self.player.close()
    def test_countdown_finish_and_replay(self):
        self.player.toggle()
        self.assertEqual(len(self.sink.calls), 0)
        wait_for(lambda: self.player.state == "finished")
        self.assertEqual([t.keys for t in self.player.timings], [("F",), ("H",), ("J",)])
        self.assertFalse(self.sink.held)
        self.player.toggle()
        wait_for(lambda: self.player.state == "finished")
        self.assertEqual(len(self.player.timings), 6)
    def test_pause_freezes_and_resumes_without_duplicate(self):
        self.player.toggle()
        wait_for(lambda: len(self.player.timings) == 1)
        self.player.toggle()
        frozen = self.player.snapshot()["position"]
        time.sleep(.1)
        self.assertEqual(self.player.snapshot()["position"], frozen)
        self.assertFalse(self.sink.held)
        self.player.toggle()
        wait_for(lambda: self.player.state == "finished")
        self.assertEqual(len(self.player.timings), 3)
    def test_end_of_song_stays_stopped_without_explicit_start(self):
        self.player.toggle()
        wait_for(lambda: self.player.state == "finished")
        calls = list(self.sink.calls)
        time.sleep(.12)
        self.assertEqual(self.player.state, "finished")
        self.assertEqual(self.sink.calls, calls)
        self.assertFalse(self.sink.held)
        self.assertEqual(self.player.position, self.player.score.duration)
    def test_focus_loss_pauses_and_never_auto_resumes(self):
        self.player.toggle()
        wait_for(lambda: len(self.player.timings) == 1)
        self.sink.focus = False
        wait_for(lambda: self.player.state == "paused")
        count = len(self.sink.calls)
        self.sink.focus = True
        time.sleep(.12)
        self.assertEqual(len(self.sink.calls), count)
        self.assertFalse(self.sink.held)
    def test_stop_and_close_release(self):
        self.player.toggle()
        wait_for(lambda: len(self.player.timings) == 1)
        self.player.stop()
        self.assertEqual(self.player.position, 0)
        self.assertFalse(self.sink.held)
        self.player.toggle()
        wait_for(lambda: self.player.state == "playing")
        self.player.close()
        self.assertFalse(self.sink.held)
        self.assertFalse(self.player.thread.is_alive())
    def test_lag_pauses_without_burst(self):
        self.sink.delay = .30
        self.player.toggle()
        wait_for(lambda: self.player.state == "paused")
        self.assertEqual(len(self.player.timings), 1)
        self.assertFalse(self.sink.held)
    def test_no_target_at_countdown_end(self):
        self.sink.focus = False
        self.player.toggle()
        wait_for(lambda: self.player.state == "paused")
        self.assertFalse(self.sink.calls)


class SiteTests(unittest.TestCase):
    def test_parse_results_and_download_version(self):
        html = '<form class="library-search"></form><article class="score-card"><span class="format-chip">MIDI</span><a class="score-title" href="/scores/edc06666-0897-48b4-82d7-cb1b9d404a33">曲&amp;名</a><a class="byline">作者</a><div class="score-labels">入门</div></article><input id="library-page" max="4">'
        result = parse_library(html, 1, "test")
        self.assertEqual(result.entries[0].title, "曲&名")
        self.assertEqual(result.pages, 4)
        link, version = download_link('<section id="score-download"><a href="/api/scores/edc06666-0897-48b4-82d7-cb1b9d404a33/file?download=1&amp;version=8db1413d-9763-4f17-8df3-c8dc84124386">下载</a></section>', result.entries[0].url)
        self.assertEqual(version, "8db1413d-9763-4f17-8df3-c8dc84124386")
        self.assertIn("download=1&version=8db1413d", link)
    def test_incomplete_results_fail(self):
        with self.assertRaises(SiteError): parse_library('<form class="library-search"></form><article class="score-card"></article>', 1, "test")
    def test_other_host_and_plain_http_blocked(self):
        for url in ("https://evil.test/file", "http://rocomusic.cn/file", "https://rocomusic.cn.evil.test/"):
            with self.assertRaises(SiteError): validate_url(url)
    def test_only_verified_midi_cdn_redirect_allowed(self):
        origin = "https://rocomusic.cn/api/scores/edc06666-0897-48b4-82d7-cb1b9d404a33/file"
        destination = f"https://{FILE_HOST}/rocomusic/2a1e1368-f987-4569-a688-6e0029852ef5.mid?signature=example"
        validate_destination(origin, destination)
        with self.assertRaises(SiteError): validate_destination("https://rocomusic.cn/library", destination)
        with self.assertRaises(SiteError): validate_destination(origin, destination.replace(".mid", ".exe"))
        with self.assertRaises(SiteError): validate_destination(origin, destination.replace(FILE_HOST, "evil.test"))
    def test_http_refusal_latches_without_retry(self):
        from urllib.error import HTTPError
        client = CatalogClient(Path("unused"))
        with patch.object(client.opener, "open", side_effect=HTTPError("url",429,"stop",{},None)) as request:
            with self.assertRaises(SiteBlocked): client.search()
            with self.assertRaises(SiteBlocked): client.search()
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__": unittest.main(verbosity=2)
