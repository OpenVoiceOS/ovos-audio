"""Dual bus-message tests for ovos-audio.

ovos-audio is a *subscriber*: it listens on BOTH the legacy and the OVOS spec
namespaces, so a deployment emitting in either namespace drives audio. Verified:
- ``speak`` and ``ovos.utterance.speak``           → TTS    (PIPELINE-1 §9.6)
- ``mycroft.stop`` and ``ovos.stop``               → TTS halts (STOP-1 §5.3)
- ``mycroft.audio.service.stop`` and ``ovos.stop`` → playback stop (STOP-1 §5.3)
"""
import time
import unittest

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovoscope.audio import AudioServiceHarness, PlaybackServiceHarness


class TestSpeakDualTopic(unittest.TestCase):
    """Both ``speak`` (legacy) and ``ovos.utterance.speak`` (§9.6) drive TTS."""

    def test_legacy_speak_topic_speaks(self):
        with PlaybackServiceHarness() as h:
            h.speak("hello legacy")
            h.assert_spoke("hello legacy")

    def test_spec_utterance_speak_topic_speaks(self):
        with PlaybackServiceHarness() as h:
            h.bus.emit(Message("ovos.utterance.speak",
                               {"utterance": "hello spec", "lang": "en-US"}))
            h._audio_output_end.wait(timeout=5.0)
            h.assert_spoke("hello spec")


class TestTtsStopDualTopic(unittest.TestCase):
    """Both ``mycroft.stop`` (legacy) and ``ovos.stop`` (§5.3) halt TTS cleanly."""

    def test_legacy_stop_keeps_service_operational(self):
        with PlaybackServiceHarness() as h:
            h.speak("something to say")
            h.bus.emit(Message("mycroft.stop"))
            time.sleep(0.1)
            h.speak("after legacy stop")
            h.assert_spoke("after legacy stop")

    def test_spec_ovos_stop_keeps_service_operational(self):
        with PlaybackServiceHarness() as h:
            h.speak("something to say")
            h.bus.emit(Message("ovos.stop"))
            time.sleep(0.1)
            h.speak("after spec stop")
            h.assert_spoke("after spec stop")


class TestPlaybackStopDualSubscription(unittest.TestCase):
    """The media playback stop handler is reachable on BOTH the legacy
    ``mycroft.audio.service.stop`` and the spec ``ovos.stop`` (STOP-1 §5.3)."""

    def _stop_calls_for(self, topic):
        import ovos_audio.audio as audio_mod
        seen = []
        orig = audio_mod.AudioService._stop

        def spy(self, message=None):
            seen.append(message.msg_type if message else None)
            return orig(self, message)

        audio_mod.AudioService._stop = spy
        try:
            bus = FakeBus()
            audio_mod.AudioService(bus)
            time.sleep(0.2)
            bus.emit(Message(topic))
            time.sleep(0.2)
        finally:
            audio_mod.AudioService._stop = orig
        return seen

    def test_legacy_service_stop_reaches_handler(self):
        self.assertIn("mycroft.audio.service.stop",
                      self._stop_calls_for("mycroft.audio.service.stop"))

    def test_spec_ovos_stop_reaches_handler(self):
        self.assertIn("ovos.stop", self._stop_calls_for("ovos.stop"))


if __name__ == "__main__":
    unittest.main()
