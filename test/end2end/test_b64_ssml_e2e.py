"""End-to-end test: ``ovos.utterance.speak.b64`` with ``utterance_ssml``.

The SSML reaches a TTS whose ``ssml_tags`` include ``speak``. Any other TTS,
a request without ``utterance_ssml``, and malformed SSML get the plain
``utterance``.
"""
import time
import unittest

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovoscope.audio import MockTTS, PlaybackServiceHarness

PLAIN = "Once upon a time. There was a king."
SSML = '<speak>Once upon a time.<break time="500ms"/>There was a king.</speak>'


class SSMLMockTTS(MockTTS):
    def __init__(self):
        super().__init__()
        self.ssml_tags = ["speak", "break"]


class TestB64SSML(unittest.TestCase):

    def _render(self, tts, data):
        replies = []
        with PlaybackServiceHarness(tts=tts, modernize=True) as h:
            h.bus.on(SpecMessage.AUDIO_SPEECH, replies.append)
            h.bus.emit(Message(SpecMessage.SPEAK_B64,
                               {"lang": "en-US", **data}))
            time.sleep(0.3)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].data["utterance"], PLAIN)
        return tts.spoken_utterances

    def test_ssml_tts_gets_ssml(self):
        spoken = self._render(SSMLMockTTS(),
                              {"utterance": PLAIN, "utterance_ssml": SSML})
        self.assertEqual(spoken, [SSML])

    def test_plain_tts_gets_plain_text(self):
        spoken = self._render(MockTTS(),
                              {"utterance": PLAIN, "utterance_ssml": SSML})
        self.assertEqual(spoken, [PLAIN])

    def test_no_ssml_field_unchanged(self):
        spoken = self._render(SSMLMockTTS(), {"utterance": PLAIN})
        self.assertEqual(spoken, [PLAIN])

    def test_malformed_ssml_falls_back_to_plain(self):
        bad = '<speak>Once upon a time.<break time="500ms">There was a king.</speak>'
        spoken = self._render(SSMLMockTTS(),
                              {"utterance": PLAIN, "utterance_ssml": bad})
        self.assertEqual(spoken, [PLAIN])


if __name__ == "__main__":
    unittest.main()
