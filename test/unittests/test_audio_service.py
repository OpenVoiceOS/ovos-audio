"""Tests for AudioService (ovos_audio.audio).

Covers: OCP plugin exclusion from discovery, backend selection by URI scheme,
audio ducking, stop-guard, and find_ocp/find_default logic.
No real audio plugins or OCP needed — all external calls are mocked.
"""
import time
import unittest
from unittest.mock import MagicMock, patch, call

from ovos_utils.fakebus import FakeBus
from ovos_utils.ocp import MediaState


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_service(disable_ocp=True, validate_source=False, config=None):
    """Instantiate AudioService with autoload=False so no real plugins load."""
    from ovos_audio.audio import AudioService
    bus = FakeBus()
    cfg = config or {}
    with patch("ovos_audio.audio.Configuration", return_value={"Audio": cfg}):
        svc = AudioService(bus, autoload=False,
                           disable_ocp=disable_ocp,
                           validate_source=validate_source)
    return svc


def _fake_backend(name="fake", uris=None, supports_mime=False):
    b = MagicMock()
    b.name = name
    b.supported_uris.return_value = uris or ["http", "https"]
    b.supports_mime_hints = supports_mime
    b.stop.return_value = True
    return b


# ---------------------------------------------------------------------------
# load_services — OCP exclusion
# ---------------------------------------------------------------------------

class TestLoadServicesOcpExclusion(unittest.TestCase):
    """load_services() must pop ovos_common_play before iterating plugins."""

    def _run_load_services(self, found_plugins):
        svc = _make_service()
        with patch("ovos_audio.audio.find_audio_service_plugins",
                   return_value=found_plugins), \
             patch("ovos_audio.audio.setup_audio_service",
                   return_value=[]) as mock_setup, \
             patch.object(svc, "find_ocp"), \
             patch.object(svc, "find_default"):
            svc.load_services()
        return mock_setup

    def test_ovos_common_play_never_passed_to_setup(self):
        ocp_plugin = MagicMock()
        vlc_plugin = MagicMock()
        mock_setup = self._run_load_services(
            {"ovos_common_play": ocp_plugin, "ovos_vlc": vlc_plugin}
        )
        called_modules = [c.args[0] for c in mock_setup.call_args_list]
        self.assertNotIn(ocp_plugin, called_modules)

    def test_other_plugins_still_passed_to_setup(self):
        vlc_plugin = MagicMock()
        mock_setup = self._run_load_services({"ovos_vlc": vlc_plugin})
        called_modules = [c.args[0] for c in mock_setup.call_args_list]
        self.assertIn(vlc_plugin, called_modules)

    def test_no_plugins_gives_empty_service_list(self):
        svc = _make_service()
        with patch("ovos_audio.audio.find_audio_service_plugins", return_value={}), \
             patch.object(svc, "find_ocp"), \
             patch.object(svc, "find_default"):
            svc.load_services()
        self.assertEqual(svc.service, [])

    def test_find_ocp_called_when_not_disabled(self):
        svc = _make_service(disable_ocp=False)
        with patch("ovos_audio.audio.find_audio_service_plugins", return_value={}), \
             patch("ovos_audio.audio.setup_audio_service", return_value=[]), \
             patch.object(svc, "find_ocp") as mock_ocp, \
             patch.object(svc, "find_default"):
            svc.load_services()
        mock_ocp.assert_called_once()

    def test_find_ocp_called_even_when_disabled(self):
        """find_ocp is always called; disable_ocp is checked inside it."""
        svc = _make_service(disable_ocp=True)
        with patch("ovos_audio.audio.find_audio_service_plugins", return_value={}), \
             patch("ovos_audio.audio.setup_audio_service", return_value=[]), \
             patch.object(svc, "find_ocp") as mock_ocp, \
             patch.object(svc, "find_default"):
            svc.load_services()
        mock_ocp.assert_called_once()


# ---------------------------------------------------------------------------
# find_ocp
# ---------------------------------------------------------------------------

class TestFindOcp(unittest.TestCase):

    def test_disable_ocp_skips_import(self):
        svc = _make_service(disable_ocp=True)
        svc.find_ocp()
        self.assertIsNone(svc.ocp)

    def test_ocp_not_installed_returns_false(self):
        svc = _make_service(disable_ocp=False)
        with patch("ovos_audio.audio.Configuration", return_value={"Audio": {}}), \
             patch.dict("sys.modules", {"ovos_plugin_common_play": None}):
            result = svc.find_ocp()
        self.assertFalse(result)

    def test_ocp_installed_instantiates(self):
        svc = _make_service(disable_ocp=False)
        mock_backend_cls = MagicMock()
        mock_ocp_module = MagicMock()
        mock_ocp_module.OCPAudioBackend = mock_backend_cls
        with patch("ovos_audio.audio.Configuration", return_value={"Audio": {
                "backends": {"OCP": {}}}}), \
             patch.dict("sys.modules", {"ovos_plugin_common_play": mock_ocp_module}):
            svc.find_ocp()
        mock_backend_cls.assert_called_once()
        self.assertIsNotNone(svc.ocp)


# ---------------------------------------------------------------------------
# find_default
# ---------------------------------------------------------------------------

class TestFindDefault(unittest.TestCase):

    def test_empty_service_list_returns_false(self):
        svc = _make_service()
        svc.service = []
        result = svc.find_default()
        self.assertFalse(result)

    def test_named_default_selected(self):
        svc = _make_service()
        svc.config = {"default-backend": "vlc"}
        vlc = _fake_backend("vlc")
        mpv = _fake_backend("mpv")
        svc.service = [mpv, vlc]
        svc.find_default()
        self.assertEqual(svc.default.name, "vlc")

    def test_falls_back_to_first_service(self):
        svc = _make_service()
        svc.config = {"default-backend": "nonexistent"}
        first = _fake_backend("first")
        svc.service = [first, _fake_backend("second")]
        svc.find_default()
        self.assertEqual(svc.default.name, "first")


# ---------------------------------------------------------------------------
# play() — backend selection
# ---------------------------------------------------------------------------

class TestPlay(unittest.TestCase):

    def _svc_with_backends(self, services, default=None):
        svc = _make_service(validate_source=False)
        svc.service = services
        svc.default = default or (services[0] if services else None)
        return svc

    def test_preferred_service_used_when_supports_uri(self):
        preferred = _fake_backend("pref", uris=["library"])
        fallback = _fake_backend("fallback", uris=["http"])
        svc = self._svc_with_backends([fallback])
        svc.default = fallback
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: t):
            svc.play(["library://track/1"], prefered_service=preferred)
        preferred.play.assert_called_once()

    def test_default_backend_used_when_uri_supported(self):
        default = _fake_backend("default", uris=["http"])
        svc = self._svc_with_backends([default])
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: t):
            svc.play(["http://example.com/track.mp3"], prefered_service=None)
        default.play.assert_called_once()

    def test_fallback_service_selected_when_default_does_not_support_uri(self):
        default = _fake_backend("default", uris=["http"])
        library_backend = _fake_backend("mass", uris=["library"])
        svc = self._svc_with_backends([default, library_backend])
        svc.default = default
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: t):
            svc.play(["library://track/1"], prefered_service=None)
        library_backend.play.assert_called_once()
        default.play.assert_not_called()

    def test_invalid_media_emitted_when_no_backend_found(self):
        svc = self._svc_with_backends([_fake_backend("http-only", uris=["http"])])
        emitted = []
        svc.bus.on("ovos.common_play.media.state",
                   lambda m: emitted.append(m.data))
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: t):
            svc.play(["xyz://unknown/stream"], prefered_service=None)
        self.assertTrue(any(d.get("state") == MediaState.INVALID_MEDIA
                            for d in emitted))

    def test_current_set_to_selected_backend(self):
        backend = _fake_backend("vlc", uris=["http"])
        svc = self._svc_with_backends([backend])
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: t):
            svc.play(["http://example.com/track.mp3"], prefered_service=None)
        self.assertEqual(svc.current, backend)


# ---------------------------------------------------------------------------
# audio ducking
# ---------------------------------------------------------------------------

class TestAudioDucking(unittest.TestCase):

    def _svc_with_current(self):
        svc = _make_service(validate_source=False)
        svc.current = _fake_backend("playing")
        return svc

    def test_lower_volume_on_speak_sets_flag(self):
        svc = self._svc_with_current()
        svc.volume_is_low = False
        svc._lower_volume_on_speak()
        self.assertTrue(svc.volume_is_low)
        svc.current.lower_volume.assert_called_once()

    def test_lower_volume_not_applied_twice(self):
        svc = self._svc_with_current()
        svc.volume_is_low = True
        svc._lower_volume_on_speak()
        svc.current.lower_volume.assert_not_called()

    def test_restore_volume_on_speak_end(self):
        svc = self._svc_with_current()
        svc.volume_is_low = True
        svc.volume_is_speaking = True
        svc._restore_volume_on_speak()
        self.assertFalse(svc.volume_is_low)
        svc.current.restore_volume.assert_called_once()

    def test_restore_volume_not_applied_when_not_ducked(self):
        svc = self._svc_with_current()
        svc.volume_is_low = False
        svc._restore_volume_on_speak()
        svc.current.restore_volume.assert_not_called()

    def test_restore_on_handled_skips_when_still_speaking(self):
        svc = self._svc_with_current()
        svc.volume_is_low = True
        svc.volume_is_speaking = True
        svc._restore_volume_on_handled()
        # still speaking — must NOT restore yet
        svc.current.restore_volume.assert_not_called()

    def test_restore_on_handled_restores_when_not_speaking(self):
        svc = self._svc_with_current()
        svc.volume_is_low = True
        svc.volume_is_speaking = False
        svc._restore_volume_on_handled()
        svc.current.restore_volume.assert_called_once()
        self.assertFalse(svc.volume_is_low)

    def test_no_current_ducking_is_noop(self):
        svc = _make_service(validate_source=False)
        svc.current = None
        svc.volume_is_low = False
        svc._lower_volume_on_speak()
        self.assertFalse(svc.volume_is_low)


# ---------------------------------------------------------------------------
# _stop() guard
# ---------------------------------------------------------------------------

class TestStopGuard(unittest.TestCase):

    def test_stop_within_1_second_is_ignored(self):
        svc = _make_service(validate_source=False)
        svc.current = _fake_backend()
        svc.play_start_time = time.monotonic()  # just started
        with patch.object(svc, "_perform_stop") as mock_stop:
            svc._stop()
        mock_stop.assert_not_called()

    def test_stop_after_1_second_calls_perform_stop(self):
        svc = _make_service(validate_source=False)
        svc.current = _fake_backend()
        svc.play_start_time = time.monotonic() - 2  # 2 seconds ago
        with patch.object(svc, "_perform_stop") as mock_stop:
            svc._stop()
        mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# _pause / _resume — no-ops without current
# ---------------------------------------------------------------------------

class TestPauseResume(unittest.TestCase):

    def test_pause_calls_current(self):
        svc = _make_service(validate_source=False)
        svc.current = _fake_backend()
        svc._pause()
        svc.current.pause.assert_called_once()
        svc.current.ocp_pause.assert_called_once()

    def test_pause_noop_without_current(self):
        svc = _make_service(validate_source=False)
        svc.current = None
        svc._pause()  # must not raise

    def test_resume_calls_current(self):
        svc = _make_service(validate_source=False)
        svc.current = _fake_backend()
        svc._resume()
        svc.current.resume.assert_called_once()
        svc.current.ocp_resume.assert_called_once()

    def test_resume_noop_without_current(self):
        svc = _make_service(validate_source=False)
        svc.current = None
        svc._resume()  # must not raise


if __name__ == "__main__":
    unittest.main()
