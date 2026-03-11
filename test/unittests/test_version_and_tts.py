"""Tests for ovos_audio.version and ovos_audio.tts."""
import unittest
from unittest.mock import MagicMock, patch


class TestVersion(unittest.TestCase):
    """Ensure version module exports correct fields."""

    def test_version_constants_exist(self):
        from ovos_audio.version import VERSION_MAJOR, VERSION_MINOR, VERSION_BUILD
        self.assertIsInstance(VERSION_MAJOR, int)
        self.assertIsInstance(VERSION_MINOR, int)
        self.assertIsInstance(VERSION_BUILD, int)

    def test_version_string_format(self):
        from ovos_audio.version import __version__, VERSION_MAJOR, VERSION_MINOR, VERSION_BUILD
        self.assertTrue(__version__.startswith(f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_BUILD}"))

    def test_alpha_suffix(self):
        import ovos_audio.version as v
        if v.VERSION_ALPHA:
            self.assertIn(f"a{v.VERSION_ALPHA}", v.__version__)
        else:
            self.assertNotIn("a", v.__version__)


class TestTTSFactory(unittest.TestCase):
    """TTSFactory.create() delegates to OVOSTTSFactory.create()."""

    def test_create_uses_configuration_when_no_config(self):
        from ovos_audio.tts import TTSFactory
        with patch("ovos_audio.tts.OVOSTTSFactory.create") as mock_create, \
             patch("ovos_audio.tts.Configuration") as mock_cfg:
            mock_cfg.return_value = {"tts": {}}
            TTSFactory.create()
            mock_create.assert_called_once()

    def test_create_passes_provided_config(self):
        from ovos_audio.tts import TTSFactory
        cfg = {"tts": {"module": "dummy"}}
        with patch("ovos_audio.tts.OVOSTTSFactory.create") as mock_create:
            TTSFactory.create(config=cfg)
            mock_create.assert_called_once_with(cfg)


if __name__ == "__main__":
    unittest.main()
