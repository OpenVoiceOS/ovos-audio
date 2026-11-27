"""The legacy loader loads the AudioBackend shim of each default media plugin.

The default plugins are the ``extras`` media plugins in pyproject.toml. The
test loads each one through the same calls as ``AudioService.load_services``.
"""
import logging
import unittest
from importlib.metadata import version
from unittest.mock import patch

import pytest
from ovos_plugin_manager.audio import find_audio_service_plugins, setup_audio_service
from ovos_plugin_manager.templates.audio import AudioBackend
from ovos_utils.fakebus import FakeBus

OPM3 = int(version("ovos-plugin-manager").split(".")[0]) >= 3
NO_TRACK_CALLS = ("play", "stop", "pause", "resume", "get_track_position",
                  "seek_forward", "seek_backward")


class KnownDefect(Exception):
    """The failure named in the xfail reason happened, and no other one."""


def _load(plugin_name, backend_config, caplog, logged=None):
    """Load one backend through the legacy loader.

    When ``logged`` is given and the loader returns no service, the test
    raises KnownDefect only if the loader logged that error text.
    """
    plugins = find_audio_service_plugins()
    if plugin_name not in plugins:
        pytest.skip(f"{plugin_name} is not installed")
    config = {"backends": {"test": dict(backend_config, type=plugin_name, active=True)}}
    services = setup_audio_service(plugins[plugin_name], config=config, bus=FakeBus())
    if not services and logged and logged in caplog.text:
        raise KnownDefect(logged)
    assert services, f"setup_audio_service returned {services!r} for {plugin_name}"
    return services[0]


def _check_backend(service):
    assert isinstance(service, AudioBackend)
    for method in NO_TRACK_CALLS:
        getattr(service, method)()


def _abstract(cls, methods):
    return f"Can't instantiate abstract class {cls} without an implementation for {methods}"


class TestDefaultMediaPlugins(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _caplog(self, caplog):
        # The OVOS logger does not propagate, so caplog would not see the
        # loader's error. A standard logger does.
        with patch("ovos_plugin_manager.audio.LOG", logging.getLogger("opm.audio")):
            self.caplog = caplog
            yield

    @pytest.mark.xfail(OPM3, strict=True, raises=KnownDefect, reason=(
        "ovos-media-plugin-cli#17: under ovos-plugin-manager 3 CLIOldAudioService "
        "does not implement the abstract method _stop, so it cannot be instantiated"))
    def test_cli(self):
        _check_backend(_load("ovos_cli", {}, self.caplog,
                             _abstract("CLIOldAudioService", "abstract method '_stop'")))

    @pytest.mark.xfail(OPM3, strict=True, raises=KnownDefect, reason=(
        "ovos-media-plugin-mpv#35: under ovos-plugin-manager 3 OVOSMPVService does not "
        "implement the abstract methods _stop and load_track"))
    def test_mpv(self):
        _check_backend(_load("ovos_mpv", {}, self.caplog,
                             _abstract("OVOSMPVService",
                                       "abstract methods '_stop', 'load_track'")))

    def test_spotify(self):
        pytest.importorskip("ovos_media_plugin_spotify.spotify_client")
        # No credentials: the client must not reach the network.
        with patch("ovos_media_plugin_spotify.spotify_client.SpotifyClient.spotify", None):
            _check_backend(_load("ovos_spotify", {"identifier": "test"}, self.caplog))

    @pytest.mark.xfail(OPM3, strict=True, raises=KnownDefect, reason=(
        "ovos-media-plugin-chromecast#51: under ovos-plugin-manager 3 "
        "ChromecastOCPAudioService does not implement the abstract method _stop"))
    def test_chromecast(self):
        pytest.importorskip("ovos_media_plugin_chromecast.media")
        with patch("ovos_media_plugin_chromecast.media.CastListener.start_browser"):
            service = _load("ovos_chromecast", {"identifier": "test"}, self.caplog,
                            _abstract("ChromecastOCPAudioService", "abstract method '_stop'"))
            assert isinstance(service, AudioBackend)
            # The raise is the failure signal: the audio service catches it
            # and reports a playback error.
            with pytest.raises(RuntimeError, match="^Unknown Chromecast device: test$"):
                service.play()
            for method in NO_TRACK_CALLS[1:]:
                getattr(service, method)()
