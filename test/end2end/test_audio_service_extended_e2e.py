# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Extended end-to-end tests for AudioService (ovos_audio.audio).

Covers scenarios not exercised by the base E2E suite:
  - Record-begin/end volume ducking
  - Restore volume on utterance handled (not-speaking path)
  - Restore volume on handled while speaking (volume stays ducked)
  - Stop guard (< 1 second): stop is silently ignored
  - Track position/length bus messages return responses
  - Seek forward/backward messages are handled without error
  - track_start callback emits mycroft.audio.playing_track
  - track_start(None) emits mycroft.audio.queue_end
  - Default session accepted when validate_source=True
  - AudioCaptureSession captures play→stop message sequence
  - No spurious events after AudioService shutdown
"""

import threading
import time
import unittest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from ovoscope.audio import AudioCaptureSession, AudioServiceHarness


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _wait_for_response(bus, request_type: str, timeout: float = 3.0):
    """Subscribe, emit, wait, return first reply data dict."""
    reply: dict = {}
    done = threading.Event()
    reply_type = f"{request_type}.response"

    def _on_reply(msg: Message) -> None:
        reply.update(msg.data)
        done.set()

    bus.on(reply_type, _on_reply)
    try:
        bus.emit(Message(request_type))
        done.wait(timeout)
    finally:
        bus.remove(reply_type, _on_reply)
    return reply if done.is_set() else None


# ---------------------------------------------------------------------------
# volume ducking — record events
# ---------------------------------------------------------------------------

class TestAudioDuckingOnRecord(unittest.TestCase):
    """recognizer_loop:record_begin lowers volume while playing."""

    def test_record_begin_lowers_volume(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.emit(Message("recognizer_loop:record_begin"))
            time.sleep(0.05)
            h.assert_volume_lowered()


class TestAudioDuckingNoCurrentOnRecord(unittest.TestCase):
    """record_begin with no active track must not raise."""

    def test_record_begin_no_current(self) -> None:
        with AudioServiceHarness() as h:
            h.bus.emit(Message("recognizer_loop:record_begin"))
            time.sleep(0.05)
            self.assertEqual(h.backend.lower_volume_calls, 0)


class TestRestoreVolumeOnHandled(unittest.TestCase):
    """ovos.utterance.handled restores volume when not speaking."""

    def test_restore_on_handled_not_speaking(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.emit(Message("recognizer_loop:record_begin"))
            time.sleep(0.05)
            h.assert_volume_lowered()
            # No speech → handled restores immediately
            h.bus.emit(Message("ovos.utterance.handled"))
            time.sleep(0.05)
            h.assert_volume_restored()
            self.assertFalse(h.service.volume_is_low)


class TestRestoreVolumeOnHandledWhileSpeaking(unittest.TestCase):
    """ovos.utterance.handled must NOT restore volume when still speaking."""

    def test_restore_on_handled_speaking(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.emit(Message("recognizer_loop:audio_output_start"))
            time.sleep(0.05)
            h.assert_volume_lowered()
            self.assertTrue(h.service.volume_is_speaking)
            h.bus.emit(Message("ovos.utterance.handled"))
            time.sleep(0.05)
            self.assertTrue(h.service.volume_is_low,
                            "volume must stay ducked while TTS is still speaking")


# ---------------------------------------------------------------------------
# stop guard
# ---------------------------------------------------------------------------

class TestStopBeforeGuardIsIgnored(unittest.TestCase):
    """stop() sent within 1 second of play() must be silently ignored."""

    def test_stop_within_1_second_no_effect(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.assert_playing()
            h.stop()
            time.sleep(0.05)
            self.assertTrue(h.backend.is_playing,
                            "stop sent within 1 second must not halt playback")


# ---------------------------------------------------------------------------
# position / length / seek — verify bus roundtrip
# ---------------------------------------------------------------------------

class TestGetTrackLength(unittest.TestCase):
    """mycroft.audio.service.get_track_length replies with a 'length' key."""

    def test_get_track_length(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            reply = _wait_for_response(h.bus, "mycroft.audio.service.get_track_length")

        self.assertIsNotNone(reply, "get_track_length received no response")
        self.assertIn("length", reply)


class TestGetTrackPosition(unittest.TestCase):
    """mycroft.audio.service.get_track_position replies with a 'position' key."""

    def test_get_track_position(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            reply = _wait_for_response(h.bus, "mycroft.audio.service.get_track_position")

        self.assertIsNotNone(reply, "get_track_position received no response")
        self.assertIn("position", reply)


class TestSetTrackPosition(unittest.TestCase):
    """set_track_position message is handled without raising."""

    def test_set_track_position_no_error(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            # MockAudioBackend.set_track_position is a no-op; just verify no crash
            h.bus.emit(Message("mycroft.audio.service.set_track_position",
                               {"position": 30000}))
            time.sleep(0.05)
            # Backend is still playing (seek didn't break anything)
            h.assert_playing()


class TestSeekForward(unittest.TestCase):
    """seek_forward message is handled without raising."""

    def test_seek_forward_no_error(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.emit(Message("mycroft.audio.service.seek_forward", {"seconds": 15}))
            time.sleep(0.05)
            h.assert_playing()


class TestSeekBackward(unittest.TestCase):
    """seek_backward message is handled without raising."""

    def test_seek_backward_no_error(self) -> None:
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.emit(Message("mycroft.audio.service.seek_backward", {"seconds": 10}))
            time.sleep(0.05)
            h.assert_playing()


# ---------------------------------------------------------------------------
# track_start callback
# ---------------------------------------------------------------------------

class TestTrackStartCallbackEmission(unittest.TestCase):
    """track_start callback emits mycroft.audio.playing_track."""

    def test_track_start_emits_playing_track(self) -> None:
        received: list = []
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.on("mycroft.audio.playing_track",
                     lambda m: received.append(m.data))
            # Directly invoke the track_start callback (as backend would)
            h.service.track_start("http://example.com/track.mp3")
            time.sleep(0.05)

        self.assertTrue(len(received) > 0,
                        "mycroft.audio.playing_track was not emitted")
        self.assertEqual(received[0]["track"], "http://example.com/track.mp3")


class TestTrackEndCallbackEmission(unittest.TestCase):
    """track_start(None) emits mycroft.audio.queue_end."""

    def test_track_end_emits_queue_end(self) -> None:
        received: list = []
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.on("mycroft.audio.queue_end", lambda m: received.append(m))
            h.service.track_start(None)
            time.sleep(0.05)

        self.assertTrue(len(received) > 0,
                        "mycroft.audio.queue_end was not emitted")


# ---------------------------------------------------------------------------
# session validation
# ---------------------------------------------------------------------------

class TestDefaultSessionAccepted(unittest.TestCase):
    """Default session is accepted even when validate_source=True."""

    def test_default_session_play_accepted(self) -> None:
        with AudioServiceHarness(validate_source=True) as h:
            h.play(["http://example.com/song.mp3"])
            h.assert_playing()


# ---------------------------------------------------------------------------
# AudioCaptureSession
# ---------------------------------------------------------------------------

class TestAudioCaptureSequencePlayStop(unittest.TestCase):
    """AudioCaptureSession records the play→stop sequence."""

    def test_capture_play_stop_sequence(self) -> None:
        with AudioServiceHarness() as h:
            with AudioCaptureSession(
                bus=h.bus,
                track_prefixes=["mycroft.audio.", "mycroft.stop"],
            ) as cap:
                h.play(["http://example.com/track.mp3"])
                time.sleep(1.1)
                h.stop()
                time.sleep(0.1)

        self.assertIn("mycroft.stop.handled", cap.message_types)


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestNoSpuriousEventsAfterShutdown(unittest.TestCase):
    """Bus listeners are removed on shutdown — no events fire after context exit."""

    def test_no_events_after_shutdown(self) -> None:
        received: list = []

        with AudioServiceHarness() as h:
            bus = h.bus

        bus.on("mycroft.audio.playing_track", lambda m: received.append(m))
        bus.emit(Message("mycroft.audio.service.play",
                         {"tracks": ["http://example.com/song.mp3"]}))
        time.sleep(0.05)
        self.assertEqual(len(received), 0,
                         "Events must not fire after AudioService shutdown")


if __name__ == "__main__":
    unittest.main()
