"""The legacy loader loads the AudioBackend shim of each default media plugin.

The default plugins are the ``extras`` media plugins in pyproject.toml. The
test loads each one through the same calls as ``AudioService.load_services``.
"""
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


def _load(plugin_name, backend_config):
    plugins = find_audio_service_plugins()
    if plugin_name not in plugins:
        pytest.skip(f"{plugin_name} is not installed")
    config = {"backends": {"test": dict(backend_config, type=plugin_name, active=True)}}
    services = setup_audio_service(plugins[plugin_name], config=config, bus=FakeBus())
    assert services, f"setup_audio_service returned {services!r} for {plugin_name}"
    return services[0]


def _check_backend(service):
    assert isinstance(service, AudioBackend)
    for method in NO_TRACK_CALLS:
        getattr(service, method)()


class TestDefaultMediaPlugins(unittest.TestCase):
    @pytest.mark.xfail(OPM3, strict=True, reason=(
        "ovos-media-plugin-cli#17: under ovos-plugin-manager 3 CLIOldAudioService "
        "does not implement the abstract method _stop, so it cannot be instantiated"))
    def test_cli(self):
        _check_backend(_load("ovos_cli", {}))

    @pytest.mark.xfail(strict=True, reason=(
        "ovos-media-plugin-mpv#33: under ovos-plugin-manager 3 OVOSMPVService does not "
        "implement the abstract methods _stop and load_track; under 2.x play() "
        "with no track raises MPVError"))
    def test_mpv(self):
        _check_backend(_load("ovos_mpv", {}))

    @pytest.mark.xfail(strict=True, reason=(
        "ovos-media-plugin-spotify#54: with no credentials SpotifyClient.spotify is "
        "None and stop() raises AttributeError on pause_playback"))
    def test_spotify(self):
        # No credentials: the client must not reach the network.
        with patch("ovos_media_plugin_spotify.spotify_client.SpotifyClient.spotify", None):
            _check_backend(_load("ovos_spotify", {"identifier": "test"}))

    @pytest.mark.xfail(strict=True, reason=(
        "ovos-media-plugin-chromecast#49: the mycroft.plugin.audioservice entry point "
        "names the class ChromecastAudioService, not the audio module, so "
        "setup_audio_service finds no load_service and returns None"))
    def test_chromecast(self):
        with patch("ovos_media_plugin_chromecast.media.CastListener.start_browser"):
            _check_backend(_load("ovos_chromecast", {"identifier": "test"}))
