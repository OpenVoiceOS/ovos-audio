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

"""End-to-end tests for PlaybackService (ovos_audio.service).

Uses PlaybackServiceHarness from ovoscope to run PlaybackService on a FakeBus
with MockTTS — no real TTS engine, audio device, or network required.
"""

import time
import unittest

from ovos_bus_client.message import Message

from ovoscope.audio import AudioCaptureSession, PlaybackServiceHarness


class TestSpeakBasic(unittest.TestCase):
    """Basic speak flow emits audio_output_start and audio_output_end."""

    def test_speak_basic(self) -> None:
        """speak message must produce audio_output_start → audio_output_end."""
        with PlaybackServiceHarness() as h:
            with AudioCaptureSession(bus=h.bus) as cap:
                h.speak("hello")
            cap.assert_sequence(
                "recognizer_loop:audio_output_start",
                "recognizer_loop:audio_output_end",
            )
            h.assert_spoke("hello")


class TestSpeakExpectResponse(unittest.TestCase):
    """speak with expect_response=True must trigger mycroft.mic.listen."""

    def test_speak_expect_response(self) -> None:
        """speak(expect_response=True) must emit mycroft.mic.listen after speech."""
        with PlaybackServiceHarness() as h:
            h.speak("are you there?", expect_response=True)
            h.assert_audio_output_ended()
            h.assert_mic_listen()


class TestStopTTS(unittest.TestCase):
    """mycroft.stop halts TTS without crashing."""

    def test_stop_tts(self) -> None:
        """Service must remain operational after mycroft.stop."""
        with PlaybackServiceHarness() as h:
            h.speak("something to say")
            h.stop()
            # Service should still handle another speak
            h.speak("after stop")
            h.assert_spoke("after stop")


class TestQueueSound(unittest.TestCase):
    """mycroft.audio.queue queues a WAV file through PlaybackThread."""

    def test_queue_sound(self) -> None:
        """Queuing a valid WAV via mycroft.audio.queue emits audio output events."""
        import os
        import tempfile
        from ovoscope.audio import SILENT_WAV

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(SILENT_WAV)
            wav_path = f.name

        try:
            with PlaybackServiceHarness() as h:
                with AudioCaptureSession(bus=h.bus) as cap:
                    h.bus.emit(Message("mycroft.audio.queue", {"uri": wav_path}))
                    # Wait for playback to complete
                    h._audio_output_end.wait(timeout=5.0)
                cap.assert_sequence(
                    "recognizer_loop:audio_output_start",
                    "recognizer_loop:audio_output_end",
                )
        finally:
            os.unlink(wav_path)


class TestOpmTtsQuery(unittest.TestCase):
    """opm.tts.query returns a response with langs, plugins, and configs keys."""

    def test_opm_tts_query(self) -> None:
        """opm.tts.query response data must contain 'langs' and 'plugins'."""
        import threading

        reply_data = {}
        done = threading.Event()

        with PlaybackServiceHarness() as h:
            def _on_reply(msg: Message) -> None:
                reply_data.update(msg.data)
                done.set()

            h.bus.on("opm.tts.query.response", _on_reply)
            h.bus.emit(Message("opm.tts.query"))
            done.wait(timeout=5)
            h.bus.remove("opm.tts.query.response", _on_reply)

        self.assertTrue(done.is_set(), "opm.tts.query received no response")
        self.assertIn("langs", reply_data)
        self.assertIn("plugins", reply_data)
        self.assertIn("configs", reply_data)


class TestSpeakStatus(unittest.TestCase):
    """mycroft.audio.speak.status replies with mycroft.audio.is_speaking."""

    def test_speak_status(self) -> None:
        """mycroft.audio.speak.status must reply with 'speaking' key in data."""
        import threading

        reply_data = {}
        done = threading.Event()

        with PlaybackServiceHarness() as h:
            def _on_reply(msg: Message) -> None:
                reply_data.update(msg.data)
                done.set()

            h.bus.on("mycroft.audio.is_speaking", _on_reply)
            h.bus.emit(Message("mycroft.audio.speak.status"))
            done.wait(timeout=3)
            h.bus.remove("mycroft.audio.is_speaking", _on_reply)

        self.assertTrue(done.is_set(), "mycroft.audio.speak.status received no response")
        self.assertIn("speaking", reply_data)


class TestMultipleSpeaks(unittest.TestCase):
    """Sequential speak calls are each recorded separately."""

    def test_multiple_speaks(self) -> None:
        """Each sequential speak call must appear in spoken_utterances."""
        sentences = ["first", "second", "third"]
        with PlaybackServiceHarness() as h:
            for s in sentences:
                h.speak(s)
            for s in sentences:
                self.assertIn(s, h.mock_tts.spoken_utterances)


if __name__ == "__main__":
    unittest.main()
