"""End-to-end test: SSML in the ``utterance`` of ``ovos.utterance.speak.b64``.

The b64 path applies ``validate_ssml``, the same as ``speak``: an SSML TTS
gets the SSML, a plain TTS gets the text with the tags removed.
"""
import time
import unittest

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovoscope.audio import MockTTS, PlaybackServiceHarness

PLAIN = "Once upon a time. There was a king."
SSML = '<speak>Once upon a time. <break time="500ms"/>There was a king.</speak>'


class SSMLMockTTS(MockTTS):
    def __init__(self):
        super().__init__()
        self.ssml_tags = ["speak", "break"]


class TestB64UtteranceSSML(unittest.TestCase):

    def _render(self, tts, utterance):
        replies = []
        with PlaybackServiceHarness(tts=tts, modernize=True) as h:
            h.bus.on(SpecMessage.AUDIO_SPEECH, replies.append)
            h.bus.emit(Message(SpecMessage.SPEAK_B64,
                               {"lang": "en-US", "utterance": utterance}))
            time.sleep(0.3)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].data["utterance"], utterance)
        return tts.spoken_utterances

    def test_ssml_tts_gets_ssml(self):
        self.assertEqual(self._render(SSMLMockTTS(), SSML), [SSML])

    def test_plain_tts_gets_tags_stripped(self):
        self.assertEqual(self._render(MockTTS(), SSML), [PLAIN])

    def test_plain_text_unchanged(self):
        self.assertEqual(self._render(SSMLMockTTS(), PLAIN), [PLAIN])
        self.assertEqual(self._render(MockTTS(), PLAIN), [PLAIN])


if __name__ == "__main__":
    unittest.main()
