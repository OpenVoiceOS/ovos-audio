"""Tests for PlaybackService config flags and static helpers.

The full PlaybackService init is heavy (threads, TTS, bus connection).
These tests focus on:
  - Config-flag defaults that are marked TODO for future changes
  - Static utility methods that are pure functions
  - Deprecated-method behaviour (return empty, emit empty response)
"""
import binascii
import os
import tempfile
import unittest
import warnings
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# PlaybackService config defaults
# ---------------------------------------------------------------------------

class TestPlaybackServiceConfigDefaults(unittest.TestCase):
    """The two TODO-flagged defaults must remain stable until explicitly flipped."""

    def _read_defaults_from_source(self):
        """Parse the literal default values from service.py without instantiating."""
        import inspect
        from ovos_audio import service as svc_module
        src = inspect.getsource(svc_module.PlaybackService.__init__)
        return src

    def test_audio_enabled_default_is_true(self):
        src = self._read_defaults_from_source()
        # The line: self.audio_enabled = self.config.get("enable_old_audioservice", True)
        self.assertIn('"enable_old_audioservice", True', src,
                      "audio_enabled default must be True (TODO: flip to False)")

    def test_audio_enabled_config_key_name(self):
        src = self._read_defaults_from_source()
        self.assertIn("enable_old_audioservice", src)


# ---------------------------------------------------------------------------
# Deprecated static methods
# ---------------------------------------------------------------------------

class TestDeprecatedAudioOptions(unittest.TestCase):
    """get_audio_options() is deprecated and must return an empty list."""

    def test_get_audio_options_returns_empty_list(self):
        from ovos_audio.service import PlaybackService
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = PlaybackService.get_audio_options()
        self.assertEqual(result, [])

    def test_get_audio_options_raises_deprecation_warning(self):
        from ovos_audio.service import PlaybackService
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            PlaybackService.get_audio_options()
        deprecation_warnings = [w for w in caught
                                 if issubclass(w.category, DeprecationWarning)]
        self.assertTrue(len(deprecation_warnings) > 0)


class TestDeprecatedOpmAudioQuery(unittest.TestCase):
    """handle_opm_audio_query() is deprecated and must respond with empty data."""

    def _make_minimal_service(self):
        """Build a PlaybackService instance with only the fields needed for
        handle_opm_audio_query(), bypassing the heavy __init__."""
        from ovos_audio.service import PlaybackService
        svc = PlaybackService.__new__(PlaybackService)
        svc.bus = MagicMock()
        return svc

    def test_handle_opm_audio_query_responds_with_empty_plugins(self):
        svc = self._make_minimal_service()
        msg = MagicMock()
        msg.response.return_value = MagicMock()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            svc.handle_opm_audio_query(msg)
        response_data = msg.response.call_args[0][0]
        self.assertEqual(response_data["plugins"], [])
        self.assertEqual(response_data["configs"], {})

    def test_handle_opm_audio_query_raises_deprecation_warning(self):
        svc = self._make_minimal_service()
        msg = MagicMock()
        msg.response.return_value = MagicMock()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            svc.handle_opm_audio_query(msg)
        deprecation_warnings = [w for w in caught
                                 if issubclass(w.category, DeprecationWarning)]
        self.assertTrue(len(deprecation_warnings) > 0)


# ---------------------------------------------------------------------------
# Static utility methods
# ---------------------------------------------------------------------------

class TestResolveSoundUri(unittest.TestCase):

    def test_nonexistent_file_raises(self):
        from ovos_audio.service import PlaybackService
        with self.assertRaises((FileNotFoundError, Exception)):
            PlaybackService._resolve_sound_uri("/does/not/exist.wav")

    def test_nonexistent_file_error_names_requested_uri(self):
        from ovos_audio.service import PlaybackService
        uri = "no/such/sound-file-xyz.wav"
        with self.assertRaises(FileNotFoundError) as excinfo:
            PlaybackService._resolve_sound_uri(uri)
        self.assertIn(uri, str(excinfo.exception))

    def test_none_returns_none(self):
        from ovos_audio.service import PlaybackService
        result = PlaybackService._resolve_sound_uri(None)
        self.assertIsNone(result)

    def test_existing_file_returned(self):
        from ovos_audio.service import PlaybackService
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            result = PlaybackService._resolve_sound_uri(path)
            self.assertEqual(result, path)
        finally:
            os.unlink(path)


class TestPathFromHexdata(unittest.TestCase):

    def test_creates_file_with_correct_content(self):
        from ovos_audio.service import PlaybackService
        raw = b"RIFF\x00\x00\x00\x00WAVEfmt "
        hex_str = binascii.hexlify(raw).decode("utf-8")
        path = PlaybackService._path_from_hexdata(hex_str, "wav")
        try:
            self.assertTrue(os.path.exists(path))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), raw)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_default_extension_is_wav(self):
        from ovos_audio.service import PlaybackService
        raw = b"\x00\x01\x02"
        hex_str = binascii.hexlify(raw).decode("utf-8")
        path = PlaybackService._path_from_hexdata(hex_str)
        try:
            self.assertTrue(path.endswith(".wav"))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_custom_extension_used(self):
        from ovos_audio.service import PlaybackService
        raw = b"\x00\x01"
        hex_str = binascii.hexlify(raw).decode("utf-8")
        path = PlaybackService._path_from_hexdata(hex_str, "mp3")
        try:
            self.assertTrue(path.endswith(".mp3"))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_deterministic_filename(self):
        """Same hex data always maps to the same temp path (MD5 based)."""
        from ovos_audio.service import PlaybackService
        raw = b"hello"
        hex_str = binascii.hexlify(raw).decode("utf-8")
        path1 = PlaybackService._path_from_hexdata(hex_str, "wav")
        path2 = PlaybackService._path_from_hexdata(hex_str, "wav")
        self.assertEqual(path1, path2)


class TestPlaybackHandlersDontCrashOnBadSound(unittest.TestCase):
    """A missing sound file or malformed message must be logged and
    swallowed by the bus handlers, never raised into pyee's emit."""

    def _make_minimal_service(self):
        from ovos_audio.service import PlaybackService
        from threading import Lock
        svc = PlaybackService.__new__(PlaybackService)
        svc.bus = MagicMock()
        svc.playback_lock = Lock()
        svc.tts = None
        svc.validate_source = False
        return svc

    def test_handle_instant_play_unresolvable_uri_logs_and_returns(self):
        svc = self._make_minimal_service()
        msg = MagicMock()
        msg.data = {"uri": "no/such/sound-file-xyz.wav"}
        with patch("ovos_audio.service.LOG") as mock_log:
            svc.handle_instant_play(msg)
        mock_log.warning.assert_called()

    def test_handle_instant_play_no_uri_or_binary_data_logs_and_returns(self):
        svc = self._make_minimal_service()
        msg = MagicMock()
        msg.data = {}
        with patch("ovos_audio.service.LOG") as mock_log:
            svc.handle_instant_play(msg)
        mock_log.warning.assert_called()

    def test_handle_queue_audio_unresolvable_uri_logs_and_returns(self):
        svc = self._make_minimal_service()
        msg = MagicMock()
        msg.data = {"uri": "no/such/sound-file-xyz.wav"}
        with patch("ovos_audio.service.LOG") as mock_log:
            svc.handle_queue_audio(msg)
        mock_log.warning.assert_called()

    def test_handle_queue_audio_no_uri_or_binary_data_logs_and_returns(self):
        svc = self._make_minimal_service()
        msg = MagicMock()
        msg.data = {}
        with patch("ovos_audio.service.LOG") as mock_log:
            svc.handle_queue_audio(msg)
        mock_log.warning.assert_called()


if __name__ == "__main__":
    unittest.main()
