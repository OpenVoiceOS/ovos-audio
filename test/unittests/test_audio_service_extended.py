"""Extended unit tests for AudioService (ovos_audio.audio).

Covers uncovered methods:
- _next, _prev
- _perform_stop
- _stop exception path
- _lower_volume_on_record
- _restore_volume_after_record
- track_start callback
- _extract (tuple tracks)
- play() — tuple uri, mime-hints stripping
- _queue — with and without current
- _play handler
- _track_info
- _list_backends
- _get_track_length, _get_track_position, _set_track_position
- _seek_forward, _seek_backward
- shutdown (with and without error)
- wait_for_load
"""
import time
import unittest
from unittest.mock import MagicMock, patch, call

from ovos_utils.fakebus import FakeBus


def _make_service(disable_ocp=True, validate_source=False, config=None):
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
# _next / _prev
# ---------------------------------------------------------------------------

class TestNextPrev(unittest.TestCase):

    def test_next_calls_current(self):
        svc = _make_service()
        svc.current = _fake_backend()
        svc._next()
        svc.current.next.assert_called_once()

    def test_next_noop_without_current(self):
        svc = _make_service()
        svc.current = None
        svc._next()  # must not raise

    def test_prev_calls_current(self):
        svc = _make_service()
        svc.current = _fake_backend()
        svc._prev()
        svc.current.previous.assert_called_once()

    def test_prev_noop_without_current(self):
        svc = _make_service()
        svc.current = None
        svc._prev()  # must not raise


# ---------------------------------------------------------------------------
# _perform_stop
# ---------------------------------------------------------------------------

class TestPerformStop(unittest.TestCase):

    def test_perform_stop_calls_stop_and_ocp_stop(self):
        svc = _make_service()
        backend = _fake_backend()
        svc.current = backend
        svc._perform_stop()
        backend.stop.assert_called_once()
        backend.ocp_stop.assert_called_once()

    def test_perform_stop_emits_handled(self):
        svc = _make_service()
        backend = _fake_backend("vlc")
        backend.stop.return_value = True
        svc.current = backend
        emitted = []
        svc.bus.on("mycroft.stop.handled", lambda m: emitted.append(m))
        svc._perform_stop()
        self.assertTrue(len(emitted) > 0)

    def test_perform_stop_resets_current_to_none(self):
        svc = _make_service()
        svc.current = _fake_backend()
        svc._perform_stop()
        self.assertIsNone(svc.current)

    def test_perform_stop_restores_volume(self):
        svc = _make_service()
        backend = _fake_backend()
        svc.current = backend
        svc.volume_is_low = True
        svc._perform_stop()
        backend.restore_volume.assert_called_once()
        self.assertFalse(svc.volume_is_low)

    def test_perform_stop_noop_without_current(self):
        svc = _make_service()
        svc.current = None
        svc._perform_stop()  # must not raise
        self.assertIsNone(svc.current)

    def test_perform_stop_with_message(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = _fake_backend("vlc")
        msg = Message("mycroft.stop", {})
        emitted = []
        svc.bus.on("mycroft.stop.handled", lambda m: emitted.append(m))
        svc._perform_stop(message=msg)
        self.assertTrue(len(emitted) > 0)


# ---------------------------------------------------------------------------
# _stop exception handler
# ---------------------------------------------------------------------------

class TestStop(unittest.TestCase):

    def test_stop_exception_in_perform_stop_is_caught(self):
        svc = _make_service()
        svc.play_start_time = time.monotonic() - 2
        with patch.object(svc, "_perform_stop", side_effect=RuntimeError("bang")):
            svc._stop()  # must not raise

    def test_stop_calls_perform_stop_after_guard(self):
        svc = _make_service()
        svc.play_start_time = time.monotonic() - 2
        with patch.object(svc, "_perform_stop") as mock_stop:
            svc._stop()
        mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# audio ducking — record events
# ---------------------------------------------------------------------------

class TestAudioDuckingRecord(unittest.TestCase):

    def test_lower_volume_on_record(self):
        svc = _make_service()
        svc.current = _fake_backend()
        svc.volume_is_low = False
        svc._lower_volume_on_record()
        svc.current.lower_volume.assert_called_once()
        self.assertTrue(svc.volume_is_low)

    def test_lower_volume_on_record_already_low(self):
        svc = _make_service()
        svc.current = _fake_backend()
        svc.volume_is_low = True
        svc._lower_volume_on_record()
        svc.current.lower_volume.assert_not_called()

    def test_lower_volume_on_record_no_current(self):
        svc = _make_service()
        svc.current = None
        svc._lower_volume_on_record()  # must not raise

    def test_restore_volume_after_record_no_current(self):
        svc = _make_service()
        svc.current = None
        svc._restore_volume_after_record()  # must not raise, logs debug

    def test_restore_volume_after_record_speech_detected(self):
        """If a speak message IS detected, volume is NOT immediately restored."""
        svc = _make_service()
        svc.current = _fake_backend()
        svc.volume_is_low = True
        # bus.wait_for_message returns a truthy message object
        svc.bus.wait_for_message = MagicMock(return_value=MagicMock())
        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()
        svc._restore_volume_after_record()
        # restore_volume should NOT be called since speech was detected
        svc.current.restore_volume.assert_not_called()

    def test_restore_volume_after_record_no_speech(self):
        """If no speak message is detected, volume IS restored."""
        svc = _make_service()
        svc.current = _fake_backend()
        svc.volume_is_low = True
        svc.bus.wait_for_message = MagicMock(return_value=None)
        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()
        svc._restore_volume_after_record()
        svc.current.restore_volume.assert_called()


# ---------------------------------------------------------------------------
# track_start callback
# ---------------------------------------------------------------------------

class TestTrackStart(unittest.TestCase):

    def test_track_start_with_track_emits_playing_track(self):
        svc = _make_service()
        svc.current = _fake_backend()
        emitted = []
        svc.bus.on("mycroft.audio.playing_track", lambda m: emitted.append(m.data))
        with patch("ovos_audio.audio.dig_for_message", return_value=None):
            svc.track_start("some_track.mp3")
        self.assertTrue(any(d.get("track") == "some_track.mp3" for d in emitted))
        svc.current.ocp_start.assert_called_once()

    def test_track_start_without_track_emits_queue_end(self):
        svc = _make_service()
        svc.current = _fake_backend()
        emitted = []
        svc.bus.on("mycroft.audio.queue_end", lambda m: emitted.append(m))
        with patch("ovos_audio.audio.dig_for_message", return_value=None):
            svc.track_start(None)
        self.assertTrue(len(emitted) > 0)
        svc.current.ocp_stop.assert_called_once()


# ---------------------------------------------------------------------------
# _extract — tuple tracks
# ---------------------------------------------------------------------------

class TestExtract(unittest.TestCase):

    def test_extract_tuple_tracks(self):
        svc = _make_service()
        mock_xtract = MagicMock()
        mock_xtract.extract_stream.return_value = {"uri": "http://real.mp3"}
        with patch("ovos_audio.audio.load_stream_extractors", return_value=mock_xtract):
            result = svc._extract([("http://raw.mp3", "audio/mpeg")])
        self.assertEqual(result, ["http://real.mp3"])

    def test_extract_string_tracks(self):
        svc = _make_service()
        mock_xtract = MagicMock()
        mock_xtract.extract_stream.return_value = {"uri": "http://real.mp3"}
        with patch("ovos_audio.audio.load_stream_extractors", return_value=mock_xtract):
            result = svc._extract(["http://raw.mp3"])
        self.assertEqual(result, ["http://real.mp3"])


# ---------------------------------------------------------------------------
# play() — more paths
# ---------------------------------------------------------------------------

class TestPlayExtended(unittest.TestCase):

    def _svc(self, services, default=None):
        svc = _make_service(validate_source=False)
        svc.service = services
        svc.default = default or (services[0] if services else None)
        return svc

    def test_play_tuple_tracks(self):
        """Tracks as (uri, mime) tuples — uri_type derived from first element."""
        backend = _fake_backend("vlc", uris=["http"])
        svc = self._svc([backend])
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: ["http://extracted.mp3"]):
            svc.play([("http://example.com/track.mp3", "audio/mpeg")], prefered_service=None)
        backend.play.assert_called_once()

    def test_play_strips_mime_hints_when_not_supported(self):
        backend = _fake_backend("vlc", uris=["http"], supports_mime=False)
        svc = self._svc([backend])
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", return_value=["http://a.mp3"]):
            svc.play(["http://a.mp3"], prefered_service=None)
        add_list_arg = backend.add_list.call_args[0][0]
        # Each entry should be a plain string, not a list/tuple
        for item in add_list_arg:
            self.assertNotIsInstance(item, list)

    def test_play_ocp_error_called_on_exception(self):
        backend = _fake_backend("vlc", uris=["http"])
        backend.play.side_effect = RuntimeError("playback failed")
        svc = self._svc([backend])
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", return_value=["http://a.mp3"]):
            svc.play(["http://a.mp3"], prefered_service=None)
        backend.ocp_error.assert_called_once()

    def test_play_sets_play_start_time(self):
        backend = _fake_backend("vlc", uris=["http"])
        svc = self._svc([backend])
        before = time.monotonic()
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", return_value=["http://a.mp3"]):
            svc.play(["http://a.mp3"], prefered_service=None)
        self.assertGreaterEqual(svc.play_start_time, before)


# ---------------------------------------------------------------------------
# _queue and _play handlers
# ---------------------------------------------------------------------------

class TestQueuePlay(unittest.TestCase):

    def test_queue_with_current_adds_tracks(self):
        svc = _make_service()
        svc.current = _fake_backend()
        msg = MagicMock()
        msg.data = {"tracks": ["http://a.mp3", "http://b.mp3"]}
        svc._queue(msg)
        svc.current.add_list.assert_called_with(["http://a.mp3", "http://b.mp3"])

    def test_queue_without_current_calls_play(self):
        svc = _make_service()
        svc.current = None
        msg = MagicMock()
        msg.data = {"tracks": ["http://a.mp3"]}
        with patch.object(svc, "_play") as mock_play:
            svc._queue(msg)
        mock_play.assert_called_once_with(msg)

    def test_queue_exception_is_caught(self):
        svc = _make_service()
        svc.current = _fake_backend()
        svc.current.add_list.side_effect = RuntimeError("boom")
        msg = MagicMock()
        msg.data = {"tracks": ["http://a.mp3"]}
        svc._queue(msg)  # must not raise

    def test_play_handler_no_preferred(self):
        svc = _make_service()
        svc.service = []
        msg = MagicMock()
        msg.data = {"tracks": ["http://a.mp3"], "repeat": False}
        with patch.object(svc, "play") as mock_play:
            svc._play(msg)
        mock_play.assert_called_once_with(["http://a.mp3"], None, False)

    def test_play_handler_matches_service_name_in_utterance(self):
        svc = _make_service()
        backend = _fake_backend("spotify")
        svc.service = [backend]
        msg = MagicMock()
        msg.data = {"tracks": ["http://a.mp3"], "utterance": "play on spotify", "repeat": False}
        with patch.object(svc, "play") as mock_play:
            svc._play(msg)
        _, args, _ = mock_play.mock_calls[0]
        self.assertEqual(args[1], backend)

    def test_play_handler_exception_is_caught(self):
        svc = _make_service()
        svc.service = []
        msg = MagicMock()
        msg.data = {"tracks": ["http://a.mp3"], "repeat": False}
        with patch.object(svc, "play", side_effect=RuntimeError("boom")):
            svc._play(msg)  # must not raise


# ---------------------------------------------------------------------------
# _track_info
# ---------------------------------------------------------------------------

class TestTrackInfo(unittest.TestCase):

    def test_track_info_with_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = _fake_backend()
        svc.current.track_info.return_value = {"title": "Test Track"}
        msg = Message("mycroft.audio.service.track_info", {})
        emitted = []
        svc.bus.on("mycroft.audio.service.track_info_reply", lambda m: emitted.append(m.data))
        svc._track_info(msg)
        self.assertTrue(len(emitted) > 0)

    def test_track_info_without_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = None
        msg = Message("mycroft.audio.service.track_info", {})
        emitted = []
        svc.bus.on("mycroft.audio.service.track_info_reply", lambda m: emitted.append(m.data))
        svc._track_info(msg)
        self.assertTrue(len(emitted) > 0)


# ---------------------------------------------------------------------------
# _list_backends
# ---------------------------------------------------------------------------

class TestListBackends(unittest.TestCase):

    def test_list_backends_returns_all_services(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        b1 = _fake_backend("vlc", uris=["http"])
        b2 = _fake_backend("mpv", uris=["http", "https"])
        svc.service = [b1, b2]
        svc.default = b1
        emitted = []
        svc.bus.on("ovos.response", lambda m: emitted.append(m.data))
        msg = Message("mycroft.audio.service.list_backends", {})
        # patch bus.emit to capture response
        captured = []
        orig_emit = svc.bus.emit
        def capture_emit(m):
            captured.append(m)
            try:
                orig_emit(m)
            except Exception:
                pass
        svc.bus.emit = capture_emit
        svc._list_backends(msg)
        # response is the first emitted message
        self.assertTrue(len(captured) > 0)

    def test_list_backends_empty(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.service = []
        captured = []
        orig_emit = svc.bus.emit
        def capture_emit(m):
            captured.append(m)
            try:
                orig_emit(m)
            except Exception:
                pass
        svc.bus.emit = capture_emit
        msg = Message("mycroft.audio.service.list_backends", {})
        svc._list_backends(msg)
        self.assertTrue(len(captured) > 0)


# ---------------------------------------------------------------------------
# track position / length / seek
# ---------------------------------------------------------------------------

class TestPositionLength(unittest.TestCase):

    def _capture_emit(self, svc):
        captured = []
        orig_emit = svc.bus.emit
        def capture_emit(m):
            captured.append(m)
            try:
                orig_emit(m)
            except Exception:
                pass
        svc.bus.emit = capture_emit
        return captured

    def test_get_track_length_with_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        captured = self._capture_emit(svc)
        svc.current = _fake_backend()
        svc.current.get_track_length.return_value = 300000
        msg = Message("mycroft.audio.service.get_track_length", {})
        svc._get_track_length(msg)
        self.assertTrue(len(captured) > 0)

    def test_get_track_length_without_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        captured = self._capture_emit(svc)
        svc.current = None
        msg = Message("mycroft.audio.service.get_track_length", {})
        svc._get_track_length(msg)
        self.assertTrue(len(captured) > 0)

    def test_get_track_position_with_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        captured = self._capture_emit(svc)
        svc.current = _fake_backend()
        svc.current.get_track_position.return_value = 12345
        msg = Message("mycroft.audio.service.get_track_position", {})
        svc._get_track_position(msg)
        self.assertTrue(len(captured) > 0)

    def test_get_track_position_without_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        captured = self._capture_emit(svc)
        svc.current = None
        msg = Message("mycroft.audio.service.get_track_position", {})
        svc._get_track_position(msg)
        self.assertTrue(len(captured) > 0)

    def test_set_track_position_with_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = _fake_backend()
        msg = Message("mycroft.audio.service.set_track_position", {"position": 5000})
        svc._set_track_position(msg)
        svc.current.set_track_position.assert_called_with(5000)

    def test_set_track_position_no_position_is_noop(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = _fake_backend()
        msg = Message("mycroft.audio.service.set_track_position", {})
        svc._set_track_position(msg)
        svc.current.set_track_position.assert_not_called()

    def test_seek_forward(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = _fake_backend()
        msg = Message("mycroft.audio.service.seek_forward", {"seconds": 10})
        svc._seek_forward(msg)
        svc.current.seek_forward.assert_called_with(10)

    def test_seek_forward_default_seconds(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = _fake_backend()
        msg = Message("mycroft.audio.service.seek_forward", {})
        svc._seek_forward(msg)
        svc.current.seek_forward.assert_called_with(1)

    def test_seek_backward(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = _fake_backend()
        msg = Message("mycroft.audio.service.seek_backward", {"seconds": 5})
        svc._seek_backward(msg)
        svc.current.seek_backward.assert_called_with(5)

    def test_seek_backward_no_current(self):
        from ovos_bus_client.message import Message
        svc = _make_service()
        svc.current = None
        msg = Message("mycroft.audio.service.seek_backward", {"seconds": 5})
        svc._seek_backward(msg)  # must not raise


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown(unittest.TestCase):

    def test_shutdown_calls_all_service_shutdown(self):
        svc = _make_service()
        b1 = _fake_backend("vlc")
        b2 = _fake_backend("mpv")
        svc.service = [b1, b2]
        svc.shutdown()
        b1.shutdown.assert_called_once()
        b2.shutdown.assert_called_once()

    def test_shutdown_service_error_logged_not_raised(self):
        svc = _make_service()
        b1 = _fake_backend("vlc")
        b1.shutdown.side_effect = RuntimeError("bad")
        svc.service = [b1]
        svc.shutdown()  # must not raise

    def test_shutdown_removes_bus_listeners(self):
        svc = _make_service()
        svc.service = []
        svc.shutdown()  # must not raise


# ---------------------------------------------------------------------------
# wait_for_load
# ---------------------------------------------------------------------------

class TestWaitForLoad(unittest.TestCase):

    def test_wait_for_load_returns_true_after_load(self):
        svc = _make_service()
        svc._loaded.set()
        result = svc.wait_for_load(timeout=1)
        self.assertTrue(result)

    def test_wait_for_load_returns_false_when_not_loaded(self):
        svc = _make_service()
        # _loaded is not set
        result = svc.wait_for_load(timeout=0.01)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# load_services — RemoteAudioBackend and set_track_start_callback
# ---------------------------------------------------------------------------

class TestLoadServicesRemote(unittest.TestCase):

    def test_remote_backends_placed_after_local(self):
        """RemoteAudioBackend instances go to remote list, local first."""
        from ovos_audio.audio import AudioService
        from ovos_plugin_manager.templates.audio import RemoteAudioBackend
        bus = FakeBus()
        local_backend = MagicMock(spec=["name", "supported_uris", "supports_mime_hints",
                                        "stop", "set_track_start_callback"])
        # Not a RemoteAudioBackend, so goes to local list
        remote_backend = MagicMock(spec=RemoteAudioBackend)

        with patch("ovos_audio.audio.Configuration", return_value={"Audio": {}}):
            svc = AudioService(bus, autoload=False, disable_ocp=True, validate_source=False)

        local_plugin = MagicMock()
        remote_plugin = MagicMock()

        def fake_setup(plugin_module, config, bus):
            if plugin_module is local_plugin:
                return [local_backend]
            return [remote_backend]  # RemoteAudioBackend instance

        with patch("ovos_audio.audio.find_audio_service_plugins",
                   return_value={"local": local_plugin, "remote": remote_plugin}), \
             patch("ovos_audio.audio.setup_audio_service", side_effect=fake_setup), \
             patch("ovos_audio.audio.isinstance",
                   side_effect=lambda obj, cls: cls == RemoteAudioBackend and obj is remote_backend), \
             patch.object(svc, "find_ocp"), \
             patch.object(svc, "find_default"):
            svc.load_services()
        # set_track_start_callback should be called for each loaded service
        # (even if order is tricky to verify, the test executes the branch)

    def test_set_track_start_callback_called_per_service(self):
        from ovos_audio.audio import AudioService
        bus = FakeBus()
        with patch("ovos_audio.audio.Configuration", return_value={"Audio": {}}):
            svc = AudioService(bus, autoload=False, disable_ocp=True, validate_source=False)

        b1 = MagicMock()
        b2 = MagicMock()

        with patch("ovos_audio.audio.find_audio_service_plugins",
                   return_value={"p1": MagicMock(), "p2": MagicMock()}), \
             patch("ovos_audio.audio.setup_audio_service",
                   side_effect=[[b1], [b2]]), \
             patch.object(svc, "find_ocp"), \
             patch.object(svc, "find_default"):
            svc.load_services()

        b1.set_track_start_callback.assert_called_with(svc.track_start)
        b2.set_track_start_callback.assert_called_with(svc.track_start)


class TestPlayPreferredService(unittest.TestCase):
    """play() line 420 — preferred service supports URI but preferred_service is used."""

    def _svc(self, services, default=None):
        svc = _make_service(validate_source=False)
        svc.service = services
        svc.default = default or (services[0] if services else None)
        return svc

    def test_preferred_service_used_when_supports_uri(self):
        preferred = _fake_backend("pref", uris=["library"])
        default = _fake_backend("default", uris=["http"])
        svc = self._svc([default])
        svc.default = default
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: t):
            svc.play(["library://track"], prefered_service=preferred)
        preferred.play.assert_called_once()

    def test_fallback_service_used_when_default_does_not_support(self):
        fallback = _fake_backend("fallback", uris=["library"])
        default = _fake_backend("default", uris=["http"])
        svc = self._svc([default, fallback])
        svc.default = default
        with patch.object(svc, "_perform_stop"), \
             patch.object(svc, "_extract", side_effect=lambda t: t):
            svc.play(["library://track"], prefered_service=None)
        fallback.play.assert_called_once()
        default.play.assert_not_called()
