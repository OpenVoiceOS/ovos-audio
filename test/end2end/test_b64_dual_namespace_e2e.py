"""End-to-end test: remote-client (b64) synthesised-audio delivery is
visible on BOTH the spec and the legacy namespace.

OVOS-AUDIO-1 §3.4/§4.3: the remote-client rendering handler (``handle_b64_audio``)
synthesises speech and, instead of enqueuing it for local playback, emits the
result on the spec topic ``ovos.audio.speech`` (``SpecMessage.AUDIO_SPEECH``).
PR #171 removed the old manual legacy double-emit: the service now emits the
spec topic ONLY. The bus client's ``emit_legacy`` flag mirrors it onto the
legacy ``speak:b64_audio.response`` via the ovos-spec-tools MIGRATION_MAP
(``'speak:b64_audio.response' -> AUDIO_SPEECH``).

This boots a real PlaybackService on a real (Fake)Bus with a dummy offline TTS
(``MockTTS``, writes a silent WAV — no network, no model download) and asserts
that a single spec-only emit reaches a subscriber on BOTH namespaces, carrying
the expected b64 audio payload. The dual delivery is the behaviour under test —
it comes from the bus, not from production code emitting twice.

The handler is reachable on both its legacy (``speak:b64_audio``) and spec
(``SpecMessage.SPEAK_B64``) input topics, so each is driven independently.
"""
import base64
import time
import unittest

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovoscope.audio import MockTTS, PlaybackServiceHarness

# The legacy ↔ spec partners under test (verified against ovos-spec-tools
# MIGRATION_MAP at authoring time).
SPEC_SPEECH_TOPIC = SpecMessage.AUDIO_SPEECH        # "ovos.audio.speech"
LEGACY_SPEECH_TOPIC = "speak:b64_audio.response"    # mirror of AUDIO_SPEECH


class _B64Capture:
    """Subscribes to both the spec and legacy synthesised-audio reply topics."""

    def __init__(self, bus):
        self.spec = []
        self.legacy = []
        bus.on(SPEC_SPEECH_TOPIC, self.spec.append)
        bus.on(LEGACY_SPEECH_TOPIC, self.legacy.append)
        bus.on(SpecMessage.MIC_LISTEN, self._mic)
        self.mic_listen = []

    def _mic(self, msg):
        self.mic_listen.append(msg)


class TestB64DualNamespaceDelivery(unittest.TestCase):
    """A spec-only b64 emit is delivered on BOTH namespaces (§3.4/§4.3)."""

    def tearDown(self):
        # The b64 render path does not enqueue playback, but PlaybackService
        # owns a class-level ``TTS.queue``. Drain it so this file stays a good
        # citizen and never bleeds half-rendered state into a following test
        # that drives the queue-based ``speak`` path.
        from ovos_plugin_manager.templates.tts import TTS
        if TTS.queue is not None:
            while not TTS.queue.empty():
                try:
                    TTS.queue.get_nowait()
                except Exception:
                    break

    def _drive_b64(self, input_topic, listen=False, utterance="hello b64"):
        """Boot the service, emit a b64 render request on ``input_topic`` and
        return the capture of both-namespace replies.

        Uses a dummy ``MockTTS`` (silent WAV, fully offline) so no real TTS
        plugin / model is pulled.
        """
        # emit_legacy=True is the bus-client mirror behaviour under test:
        # a spec-only emit must surface the legacy counterpart too.
        with PlaybackServiceHarness(tts=MockTTS(),
                                    modernize=True,
                                    emit_legacy=True) as h:
            cap = _B64Capture(h.bus)
            h.bus.emit(Message(input_topic, {"utterance": utterance,
                                             "lang": "en-US",
                                             "listen": listen}))
            # handler is synchronous over the in-process bus; small grace for
            # the mirrored typed-event re-dispatch.
            time.sleep(0.3)
            return cap

    # ------------------------------------------------------------------
    # legacy input topic -> both-namespace delivery
    # ------------------------------------------------------------------

    def test_legacy_input_delivers_on_both_namespaces(self):
        cap = self._drive_b64("speak:b64_audio")
        self.assertEqual(len(cap.spec), 1,
                         f"expected one {SPEC_SPEECH_TOPIC} emit")
        self.assertEqual(len(cap.legacy), 1,
                         f"expected one {LEGACY_SPEECH_TOPIC} mirror emit")

    # ------------------------------------------------------------------
    # spec input topic -> both-namespace delivery
    # ------------------------------------------------------------------

    def test_spec_input_delivers_on_both_namespaces(self):
        cap = self._drive_b64(SpecMessage.SPEAK_B64)
        self.assertEqual(len(cap.spec), 1,
                         f"expected one {SPEC_SPEECH_TOPIC} emit")
        self.assertEqual(len(cap.legacy), 1,
                         f"expected one {LEGACY_SPEECH_TOPIC} mirror emit")

    # ------------------------------------------------------------------
    # payload is the synthesised b64 audio, identical on both namespaces
    # ------------------------------------------------------------------

    def test_payload_carries_b64_audio_on_both_namespaces(self):
        cap = self._drive_b64(SpecMessage.SPEAK_B64, utterance="payload check")
        self.assertTrue(cap.spec and cap.legacy)
        spec_data = cap.spec[0].data
        legacy_data = cap.legacy[0].data

        # both namespaces carry the same render result
        self.assertEqual(spec_data.get("utterance"), "payload check")
        self.assertEqual(legacy_data.get("utterance"), "payload check")
        self.assertEqual(spec_data.get("audio"), legacy_data.get("audio"))

        # the audio field is the base64 of the dummy TTS's silent WAV
        decoded = base64.b64decode(spec_data["audio"])
        self.assertEqual(decoded, MockTTS.SILENT_WAV)
        self.assertEqual(spec_data.get("tts_id"), legacy_data.get("tts_id"))

    # ------------------------------------------------------------------
    # the spec emit happens exactly once on the wire (no manual double-emit)
    # ------------------------------------------------------------------

    def test_spec_topic_not_emitted_twice(self):
        # PR #171 dropped the hand-rolled legacy reply; the service emits the
        # spec topic a single time and relies on the bus mirror. Confirm the
        # spec listener fires exactly once (a re-introduced manual legacy
        # emit would not double the spec topic, but a regression that emits
        # both spec+legacy by hand would surface here as the legacy listener
        # firing twice — once direct, once mirrored).
        cap = self._drive_b64("speak:b64_audio")
        self.assertEqual(len(cap.spec), 1)
        self.assertEqual(len(cap.legacy), 1)

    # ------------------------------------------------------------------
    # listen=True re-opens the mic after the synthesised-audio delivery (§3.4)
    # ------------------------------------------------------------------

    def test_listen_true_reopens_mic_after_delivery(self):
        cap = self._drive_b64(SpecMessage.SPEAK_B64, listen=True)
        self.assertEqual(len(cap.spec), 1)
        self.assertEqual(len(cap.legacy), 1)
        self.assertTrue(cap.mic_listen,
                        "listen=True must emit ovos.mic.listen after delivery")

    def test_listen_false_does_not_reopen_mic(self):
        cap = self._drive_b64(SpecMessage.SPEAK_B64, listen=False)
        self.assertFalse(cap.mic_listen,
                         "listen=False must not emit ovos.mic.listen")


if __name__ == "__main__":
    unittest.main()
