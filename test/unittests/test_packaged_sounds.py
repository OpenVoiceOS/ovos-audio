"""The distribution must carry the default sounds.

mycroft.conf names snd/start_listening.wav, snd/acknowledge.mp3 and snd/error.mp3,
and PlaybackService resolves them from ovos_audio/res first. They are data files,
which a wheel only includes when the build is told to. From 1.2.0a1 to 2.2.8a2 it
was not: every sound failed with "could not resolve sound uri", and no test
noticed, because the tests import ovos_audio from the checkout, where the files
always are. So this one asks the installed distribution what it carries.
"""
import importlib.metadata
import json
import unittest

DEFAULT_SOUNDS = ("start_listening.wav", "acknowledge.mp3", "error.mp3")


class TestPackagedSounds(unittest.TestCase):

    def test_installed_distribution_carries_the_default_sounds(self):
        dist = importlib.metadata.distribution("ovos-audio")
        direct_url = dist.read_text("direct_url.json")
        if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable"):
            self.skipTest("an editable install records no files; "
                          "the build test installs the wheel")
        shipped = {str(path) for path in dist.files}
        for sound in DEFAULT_SOUNDS:
            self.assertIn(f"ovos_audio/res/snd/{sound}", shipped)


if __name__ == "__main__":
    unittest.main()
