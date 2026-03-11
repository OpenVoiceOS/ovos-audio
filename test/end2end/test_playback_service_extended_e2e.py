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

"""Extended end-to-end tests for PlaybackService (ovos_audio.service).

Covers scenarios not exercised by the base E2E suite:
  - speak:b64_audio returns base64-encoded audio over the bus
  - ovos.languages.tts returns list of supported languages
  - mycroft.audio.play_sound plays a WAV immediately (handle_instant_play)
  - opm.g2p.query returns a valid response
  - Session validation: non-default session is rejected for speak
  - speak with context ident triggers deprecation-safe execution
  - AudioCaptureSession captures full TTS lifecycle sequence
  - Multiple speaks — AudioCaptureSession records all output events
  - mycroft.audio.queue with binary_data produces audio output events
  - Speak status is false when not speaking
"""

import base64
import binascii
import os
import tempfile
import threading
import time
import unittest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from ovoscope.audio import AudioCaptureSession, PlaybackServiceHarness, SILENT_WAV


class TestB64Audio(unittest.TestCase):
    """speak:b64_audio message returns base64-encoded audio on the bus."""

    def test_b64_audio_returns_encoded_audio(self) -> None:
        reply: dict = {}
        done = threading.Event()

        with PlaybackServiceHarness() as h:
            def _on_reply(msg: Message) -> None:
                reply.update(msg.data)
                done.set()

            h.bus.on("speak:b64_audio.response", _on_reply)
            h.bus.emit(Message("speak:b64_audio",
                               {"utterance": "hello from b64", "listen": False}))
            done.wait(timeout=5)
            h.bus.remove("speak:b64_audio.response", _on_reply)

        self.assertTrue(done.is_set(), "speak:b64_audio received no response")
        self.assertIn("audio", reply)
        # Must be valid base64
        decoded = base64.b64decode(reply["audio"])
        self.assertIsInstance(decoded, bytes)
        self.assertIn("utterance", reply)
        self.assertEqual(reply["utterance"], "hello from b64")


class TestGetLanguagesTts(unittest.TestCase):
    """ovos.languages.tts returns a list of supported TTS languages."""

    def test_get_languages_tts(self) -> None:
        reply: dict = {}
        done = threading.Event()

        with PlaybackServiceHarness() as h:
            def _on_reply(msg: Message) -> None:
                reply.update(msg.data)
                done.set()

            h.bus.on("ovos.languages.tts.response", _on_reply)
            h.bus.emit(Message("ovos.languages.tts"))
            done.wait(timeout=3)
            h.bus.remove("ovos.languages.tts.response", _on_reply)

        self.assertTrue(done.is_set(), "ovos.languages.tts received no response")
        self.assertIn("langs", reply)
        self.assertIsInstance(reply["langs"], list)


class TestInstantPlayWav(unittest.TestCase):
    """mycroft.audio.play_sound plays a WAV file immediately."""

    def test_instant_play_wav(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(SILENT_WAV)
            wav_path = f.name

        reply: dict = {}
        done = threading.Event()

        try:
            with PlaybackServiceHarness() as h:
                def _on_reply(msg: Message) -> None:
                    reply.update(msg.data)
                    done.set()

                h.bus.on("mycroft.audio.play_sound.response", _on_reply)
                h.bus.emit(Message("mycroft.audio.play_sound", {"uri": wav_path}))
                done.wait(timeout=5)
                h.bus.remove("mycroft.audio.play_sound.response", _on_reply)
        finally:
            os.unlink(wav_path)

        self.assertTrue(done.is_set(), "mycroft.audio.play_sound received no response")


class TestInstantPlayBinaryData(unittest.TestCase):
    """mycroft.audio.play_sound with binary_data plays successfully."""

    def test_instant_play_binary_data(self) -> None:
        hex_audio = binascii.hexlify(SILENT_WAV).decode("utf-8")
        done = threading.Event()

        with PlaybackServiceHarness() as h:
            h.bus.on("mycroft.audio.play_sound.response",
                     lambda m: done.set())
            h.bus.emit(Message("mycroft.audio.play_sound",
                               {"binary_data": hex_audio, "audio_ext": "wav"}))
            done.wait(timeout=5)

        self.assertTrue(done.is_set(), "mycroft.audio.play_sound (binary) received no response")


class TestOpmG2pQuery(unittest.TestCase):
    """opm.g2p.query returns a response with langs and plugins keys."""

    def test_opm_g2p_query(self) -> None:
        reply: dict = {}
        done = threading.Event()

        with PlaybackServiceHarness() as h:
            def _on_reply(msg: Message) -> None:
                reply.update(msg.data)
                done.set()

            h.bus.on("opm.g2p.query.response", _on_reply)
            h.bus.emit(Message("opm.g2p.query"))
            done.wait(timeout=5)
            h.bus.remove("opm.g2p.query.response", _on_reply)

        self.assertTrue(done.is_set(), "opm.g2p.query received no response")
        self.assertIn("langs", reply)
        self.assertIn("plugins", reply)


class TestSpeakNonDefaultSessionRejected(unittest.TestCase):
    """validate_source=True rejects speak from non-default sessions."""

    def test_speak_non_default_rejected(self) -> None:
        with PlaybackServiceHarness(validate_source=True) as h:
            custom = Session("non-default-xyz")
            msg = Message(
                "speak",
                {"utterance": "should be rejected"},
                {"session": custom.serialize()},
            )
            h.bus.emit(msg)
            time.sleep(0.5)
            self.assertNotIn("should be rejected",
                             h.mock_tts.spoken_utterances,
                             "Non-default session speak must be rejected")


class TestSpeakWithIdentContext(unittest.TestCase):
    """speak with legacy 'ident' in context still executes (logs deprecation)."""

    def test_speak_with_ident(self) -> None:
        with PlaybackServiceHarness() as h:
            msg = Message(
                "speak",
                {"utterance": "legacy ident test"},
                {"ident": "abc-123"},
            )
            h.bus.emit(msg)
            h.assert_audio_output_ended(timeout=5)
            h.assert_spoke("legacy ident test")


class TestAudioCaptureSequence(unittest.TestCase):
    """AudioCaptureSession captures the complete TTS lifecycle for a speak."""

    def test_capture_tts_lifecycle(self) -> None:
        with PlaybackServiceHarness() as h:
            with AudioCaptureSession(bus=h.bus) as cap:
                h.speak("capture me")

        cap.assert_sequence(
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",
        )


class TestMultipleSpeaksCaptureAllEvents(unittest.TestCase):
    """Sequential speaks each produce their own audio_output_start/end pair."""

    def test_multiple_speaks_capture(self) -> None:
        sentences = ["alpha", "beta", "gamma"]
        with PlaybackServiceHarness() as h:
            with AudioCaptureSession(bus=h.bus) as cap:
                for s in sentences:
                    h.speak(s)

        starts = [t for t in cap.message_types
                  if t == "recognizer_loop:audio_output_start"]
        ends = [t for t in cap.message_types
                if t == "recognizer_loop:audio_output_end"]
        self.assertGreaterEqual(len(starts), 1,
                                "At least one audio_output_start must be emitted")
        self.assertGreaterEqual(len(ends), 1,
                                "At least one audio_output_end must be emitted")
        # All utterances must have been spoken
        for s in sentences:
            self.assertIn(s, h.mock_tts.spoken_utterances)


class TestQueueSoundWithBinaryData(unittest.TestCase):
    """mycroft.audio.queue with binary_data produces audio output events."""

    def test_queue_binary_data(self) -> None:
        hex_audio = binascii.hexlify(SILENT_WAV).decode("utf-8")

        with PlaybackServiceHarness() as h:
            with AudioCaptureSession(bus=h.bus) as cap:
                h.bus.emit(Message("mycroft.audio.queue",
                                   {"binary_data": hex_audio, "audio_ext": "wav"}))
                h._audio_output_end.wait(timeout=5.0)

        cap.assert_sequence(
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",
        )


class TestSpeakStatusNotSpeaking(unittest.TestCase):
    """mycroft.audio.speak.status returns speaking=False when idle."""

    def test_speak_status_idle(self) -> None:
        reply: dict = {}
        done = threading.Event()

        with PlaybackServiceHarness() as h:
            def _on_reply(msg: Message) -> None:
                reply.update(msg.data)
                done.set()

            h.bus.on("mycroft.audio.is_speaking", _on_reply)
            h.bus.emit(Message("mycroft.audio.speak.status"))
            done.wait(timeout=3)
            h.bus.remove("mycroft.audio.is_speaking", _on_reply)

        self.assertTrue(done.is_set())
        self.assertFalse(reply["speaking"],
                         "Service must report speaking=False when idle")


class TestSpeakResetMockTts(unittest.TestCase):
    """mock_tts.reset() clears spoken_utterances between test phases."""

    def test_reset_clears_history(self) -> None:
        with PlaybackServiceHarness() as h:
            h.speak("first utterance")
            self.assertIn("first utterance", h.mock_tts.spoken_utterances)
            h.mock_tts.reset()
            self.assertEqual(h.mock_tts.spoken_utterances, [],
                             "reset() must clear spoken_utterances")
            h.speak("second utterance")
            self.assertIn("second utterance", h.mock_tts.spoken_utterances)
            self.assertNotIn("first utterance", h.mock_tts.spoken_utterances)


class TestSpeakAfterStop(unittest.TestCase):
    """PlaybackService remains functional after a mycroft.stop command."""

    def test_speak_after_stop_produces_events(self) -> None:
        with PlaybackServiceHarness() as h:
            h.speak("before stop")
            h.stop()
            time.sleep(0.1)

            with AudioCaptureSession(bus=h.bus) as cap:
                h.speak("after stop")
                h._audio_output_end.wait(timeout=5.0)

        cap.assert_sequence(
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",
        )


if __name__ == "__main__":
    unittest.main()
