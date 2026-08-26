"""Tests targeting the remaining coverage gaps to reach ~98%+.

Covers:
  - playback.py:156  — Empty exception in _play()
  - playback.py:186-187 — run() loop dequeues and calls _play()
  - service.py:85-86 — MessageBusClient creation when bus=None
  - service.py:92 — TTS.queue = Queue() when TTS.queue is None
  - service.py:100-102 — exception from _maybe_reload_tts in __init__
  - service.py:116-117 — exception from AudioService in __init__
  - service.py:401 — fallback_tts.shutdown() on reload
  - service.py:545 — handle_instant_play with no uri/binary_data (ValueError)
  - audio.py:107-109 — OCP player.validate_source exception
  - audio.py:146 — remote += s (RemoteAudioBackend branch)
  - audio.py:155 — set_track_start_callback
  - transformers.py:164-165 — TTSTransformersService.transform exception logging
  - utils.py:93 — report_timing (pass)
"""
import queue
import sys
import unittest
from threading import Lock
from unittest.mock import MagicMock, patch, call

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus


# ===========================================================================
# playback.py — remaining lines
# ===========================================================================

def _make_thread(bus=None, q=None):
    from ovos_audio.playback import PlaybackThread
    q = q or queue.Queue()
    with patch("ovos_audio.playback.TTSTransformersService"):
        t = PlaybackThread(queue=q, bus=bus)
    return t


class TestPlayEmptyException(unittest.TestCase):
    """Line 156: pass in except Empty block inside _play()."""

    def test_empty_exception_in_play_silenced(self):
        """Raise queue.Empty from inside _play's try block — hits line 156."""
        from queue import Empty
        t = _make_thread(bus=MagicMock())
        msg = Message(SpecMessage.SPEAK, {"utterance": "hi"}, context={})
        t._now_playing = ("/tmp/x.wav", None, False, "tts", msg)
        t.on_start = MagicMock()
        t.on_end = MagicMock()
        t.tts_transform = MagicMock()
        # Make transform raise Empty — hits except Empty: pass
        t.tts_transform.transform.side_effect = Empty()
        t._play()  # must not raise; _now_playing cleared after
        self.assertIsNone(t._now_playing)


class TestRunDequeue(unittest.TestCase):
    """Lines 186-187: run() successfully dequeues an item and calls _play()."""

    def test_run_dequeues_item_and_calls_play(self):
        q = queue.Queue()
        t = _make_thread(bus=MagicMock(), q=q)
        called = []

        def fake_play():
            called.append(1)
            t._terminated = True  # stop the loop after first item

        t._play = fake_play

        msg = Message(SpecMessage.SPEAK, {"utterance": "hello"}, context={})
        q.put(("/tmp/a.wav", None, False, "tts", msg))
        t.run()  # will dequeue, call _play, then terminate
        self.assertEqual(len(called), 1)


# ===========================================================================
# service.py — __init__ edge cases
# ===========================================================================

def _full_mock_init_context():
    """Returns a context manager stack that mocks everything PlaybackService.__init__ touches."""
    from contextlib import ExitStack
    stack = ExitStack()
    try:
        stack.enter_context(patch("ovos_audio.service.Configuration", return_value={}))
        stack.enter_context(patch("ovos_audio.service.MessageBusClient",
                                  return_value=MagicMock()))
        stack.enter_context(patch("ovos_audio.service.ProcessStatus",
                                  return_value=MagicMock()))
        stack.enter_context(patch("ovos_audio.service.StatusCallbackMap",
                                  return_value=MagicMock()))
        stack.enter_context(patch("ovos_audio.service.DialogTransformersService",
                                  return_value=MagicMock()))
        stack.enter_context(patch("ovos_audio.service.PlaybackThread",
                                  return_value=MagicMock()))
        stack.enter_context(patch("ovos_audio.service.AudioService",
                                  return_value=MagicMock()))
    except Exception:
        stack.close()
        raise
    return stack


class TestPlaybackServiceInitNoBus(unittest.TestCase):
    """service.py lines 85-86: bus=None causes MessageBusClient() to be created."""

    def test_no_bus_creates_message_bus_client(self):
        from ovos_audio.service import PlaybackService
        mock_bus_cls = MagicMock()
        mock_bus = MagicMock()
        mock_bus_cls.return_value = mock_bus
        with _full_mock_init_context() as stack:
            stack.enter_context(patch("ovos_audio.service.MessageBusClient", mock_bus_cls))
            # Prevent actual TTS reload from running
            with patch.object(PlaybackService, "_maybe_reload_tts"):
                svc = PlaybackService(bus=None, disable_fallback=True)
        mock_bus_cls.assert_called_once()
        mock_bus.run_in_thread.assert_called_once()


class TestPlaybackServiceInitTTSQueueNone(unittest.TestCase):
    """service.py line 92: TTS.queue = Queue() when TTS.queue is None."""

    def test_tts_queue_set_when_none(self):
        from ovos_plugin_manager.templates.tts import TTS
        from ovos_audio.service import PlaybackService
        original_queue = TTS.queue
        try:
            TTS.queue = None
            with _full_mock_init_context():
                with patch.object(PlaybackService, "_maybe_reload_tts"):
                    svc = PlaybackService(bus=FakeBus(), disable_fallback=True)
            self.assertIsNotNone(TTS.queue)
        finally:
            TTS.queue = original_queue


class TestPlaybackServiceInitMaybeReloadException(unittest.TestCase):
    """service.py lines 100-102: exception from _maybe_reload_tts sets status.error."""

    def test_status_error_on_maybe_reload_exception(self):
        from ovos_audio.service import PlaybackService
        mock_status = MagicMock()
        with _full_mock_init_context():
            with patch("ovos_audio.service.ProcessStatus", return_value=mock_status), \
                 patch.object(PlaybackService, "_maybe_reload_tts",
                              side_effect=RuntimeError("TTS boom")):
                svc = PlaybackService(bus=FakeBus(), disable_fallback=True)
        mock_status.set_error.assert_called_once()


class TestPlaybackServiceInitAudioServiceException(unittest.TestCase):
    """service.py lines 116-117: exception from AudioService is caught."""

    def test_audio_service_exception_caught(self):
        from ovos_audio.service import PlaybackService
        with _full_mock_init_context():
            with patch("ovos_audio.service.AudioService",
                       side_effect=RuntimeError("audio boom")), \
                 patch.object(PlaybackService, "_maybe_reload_tts"):
                # Must not raise; audio stays None
                svc = PlaybackService(bus=FakeBus(), disable_fallback=True)
        self.assertIsNone(svc.audio)


# ===========================================================================
# service.py — _maybe_reload_tts: fallback_tts.shutdown() on reload (line 401)
# ===========================================================================

def _make_svc(**kwargs):
    from ovos_audio.service import PlaybackService
    svc = PlaybackService.__new__(PlaybackService)
    svc.bus = kwargs.get("bus") or FakeBus()
    svc.config = {}
    svc.lock = Lock()
    svc.playback_lock = Lock()
    svc.validate_source = False
    svc.tts = kwargs.get("tts") or MagicMock()
    svc._tts_hash = kwargs.get("_tts_hash")
    svc._fallback_tts_hash = kwargs.get("_fallback_tts_hash")
    svc.fallback_tts = kwargs.get("fallback_tts")
    svc.disable_reload = kwargs.get("disable_reload", False)
    svc.disable_fallback = kwargs.get("disable_fallback", False)
    svc._last_stop_signal = 0
    svc.dialog_transform = MagicMock()
    svc.playback_thread = MagicMock()
    svc.status = MagicMock()
    svc.audio = None
    svc.pip_installer = MagicMock()
    return svc


class TestMaybeReloadFallbackShutdown(unittest.TestCase):
    """service.py line 401: existing fallback_tts is shut down before reload."""

    def test_old_fallback_tts_shutdown_on_reload(self):
        import json
        old_fallback = MagicMock()
        tts_hash = hash(json.dumps({}, sort_keys=True))
        svc = _make_svc(
            _tts_hash=tts_hash,  # same hash → no main TTS reload
            _fallback_tts_hash=None,  # different → trigger fallback reload
            fallback_tts=old_fallback,
        )
        new_fallback = MagicMock()
        cfg = {
            "tts": {
                "module": "main",
                "fallback_module": "fallback",
                "preload_fallback": True,
                "main": {},
                "fallback": {},
            }
        }
        with patch("ovos_audio.service.Configuration", return_value=cfg), \
             patch("ovos_audio.service.TTSFactory.create", return_value=new_fallback), \
             patch.object(svc, "_get_tts_fallback"):
            svc._maybe_reload_tts()
        old_fallback.shutdown.assert_called_once()


# ===========================================================================
# service.py:545 — handle_instant_play ValueError (no uri, no binary_data)
# ===========================================================================

class TestHandleInstantPlayNoUri(unittest.TestCase):

    def test_raises_value_error_when_no_uri_or_binary_data(self):
        svc = _make_svc()
        msg = Message("mycroft.audio.play_sound", {})  # no uri, no binary_data
        with self.assertRaises(ValueError):
            svc.handle_instant_play(msg)


# ===========================================================================
# audio.py:107-109 — OCP player.validate_source exception
# ===========================================================================

class TestFindOcpValidateSourceException(unittest.TestCase):

    def test_old_ocp_version_warning_logged(self):
        from ovos_audio.audio import AudioService
        bus = FakeBus()
        with patch("ovos_audio.audio.Configuration", return_value={"Audio": {}}):
            svc = AudioService(bus, autoload=False, disable_ocp=False, validate_source=True)

        mock_backend_cls = MagicMock()
        mock_ocp = MagicMock()
        # Setting player.validate_source raises AttributeError (old OCP version)
        type(mock_ocp.player).validate_source = property(
            fget=lambda self: None,
            fset=MagicMock(side_effect=AttributeError("old OCP"))
        )
        mock_backend_cls.return_value = mock_ocp
        mock_ocp_module = MagicMock()
        mock_ocp_module.OCPAudioBackend = mock_backend_cls

        with patch("ovos_audio.audio.Configuration",
                   return_value={"Audio": {"backends": {"OCP": {}}}}), \
             patch.dict("sys.modules", {"ovos_plugin_common_play": mock_ocp_module}):
            # Should not raise — exception is caught
            svc.find_ocp()


# ===========================================================================
# audio.py:146 — remote += s (RemoteAudioBackend)
# ===========================================================================

class TestLoadServicesRemoteBackend(unittest.TestCase):

    def test_remote_backend_added_to_service(self):
        from ovos_audio.audio import AudioService, RemoteAudioBackend
        bus = FakeBus()
        with patch("ovos_audio.audio.Configuration", return_value={"Audio": {}}):
            svc = AudioService(bus, autoload=False, disable_ocp=True, validate_source=False)

        # Create a proper RemoteAudioBackend mock instance
        remote_instance = MagicMock(spec=RemoteAudioBackend)
        # setup_audio_service returns a list containing the backend
        # The code does: s = setup_audio_service(...); if not s: continue; if isinstance(s, RemoteAudioBackend): remote += s

        with patch("ovos_audio.audio.find_audio_service_plugins",
                   return_value={"my_remote": MagicMock()}), \
             patch("ovos_audio.audio.setup_audio_service",
                   return_value=[remote_instance]), \
             patch.object(svc, "find_ocp"), \
             patch.object(svc, "find_default"):
            svc.load_services()
        # remote backend should be in service list
        self.assertIn(remote_instance, svc.service)


# ===========================================================================
# audio.py:155 — set_track_start_callback
# ===========================================================================

class TestSetTrackStartCallback(unittest.TestCase):

    def test_set_track_start_callback_called(self):
        from ovos_audio.audio import AudioService
        bus = FakeBus()
        with patch("ovos_audio.audio.Configuration", return_value={"Audio": {}}):
            svc = AudioService(bus, autoload=False, disable_ocp=True, validate_source=False)

        b1 = MagicMock()

        with patch("ovos_audio.audio.find_audio_service_plugins",
                   return_value={"p1": MagicMock()}), \
             patch("ovos_audio.audio.setup_audio_service", return_value=[b1]), \
             patch.object(svc, "find_ocp"), \
             patch.object(svc, "find_default"):
            svc.load_services()
        b1.set_track_start_callback.assert_called_with(svc.track_start)


# ===========================================================================
# transformers.py:164-165 — exception in TTSTransformersService.transform
# ===========================================================================

class TestTTSTransformersException(unittest.TestCase):

    def test_transform_exception_logged_not_raised(self):
        from ovos_audio.transformers import TTSTransformersService
        svc = TTSTransformersService(bus=MagicMock(), config={})
        mock_plugin = MagicMock()
        mock_plugin.priority = 50
        mock_plugin.transform.side_effect = RuntimeError("transform boom")
        svc.loaded_plugins["p"] = mock_plugin
        # Must not raise, returns original wav_file
        result, ctx = svc.transform("/tmp/test.wav", context={})
        self.assertEqual(result, "/tmp/test.wav")


# ===========================================================================
# utils.py:93 — report_timing (pass)
# ===========================================================================

class TestReportTiming(unittest.TestCase):

    def test_report_timing_is_noop(self):
        from ovos_audio.utils import report_timing
        # Just call it — it's a TODO stub that does nothing
        report_timing("ident", MagicMock(), {"key": "val"})


if __name__ == "__main__":
    unittest.main()

# ===========================================================================
# service.py — _maybe_reload_tts: the module name must take part in the hash
# ===========================================================================

class TestReloadOnModuleChange(unittest.TestCase):
    """Swapping tts.module must reload the engine.

    The reload hash covered only the selected module's own settings block. Two
    plugins with no settings of their own therefore hashed identically, so the
    swap looked like no change and the old engine kept speaking until the
    service restarted.
    """

    @staticmethod
    def _cfg(module):
        return {"tts": {"module": module, "fallback_module": "", "preload_fallback": False}}

    def _reload_with(self, svc, module, new_tts):
        with patch("ovos_audio.service.Configuration", return_value=self._cfg(module)), \
             patch("ovos_audio.service.TTSFactory.create", return_value=new_tts), \
             patch.object(svc, "_get_tts_fallback"):
            svc._maybe_reload_tts()

    def test_changing_the_module_reloads_even_without_a_settings_block(self):
        old = MagicMock()
        svc = _make_svc(tts=old, disable_fallback=True)
        self._reload_with(svc, "ovos-tts-plugin-mimic3", MagicMock())
        first_hash = svc._tts_hash

        new = MagicMock()
        self._reload_with(svc, "ovos-tts-plugin-piper", new)

        self.assertNotEqual(first_hash, svc._tts_hash,
                            "the module name is not part of the reload hash")
        self.assertIs(svc.tts, new, "the engine was not swapped")

    def test_saving_the_same_module_again_does_not_reload(self):
        svc = _make_svc(tts=MagicMock(), disable_fallback=True)
        self._reload_with(svc, "ovos-tts-plugin-piper", MagicMock())
        settled = svc.tts

        self._reload_with(svc, "ovos-tts-plugin-piper", MagicMock())
        self.assertIs(svc.tts, settled, "an unchanged configuration reloaded anyway")

    def test_changing_the_fallback_module_reloads_the_fallback(self):
        svc = _make_svc(tts=MagicMock(), fallback_tts=MagicMock())
        cfg = {"tts": {"module": "main", "fallback_module": "fb-one",
                       "preload_fallback": True}}
        with patch("ovos_audio.service.Configuration", return_value=cfg), \
             patch("ovos_audio.service.TTSFactory.create", return_value=MagicMock()), \
             patch.object(svc, "_get_tts_fallback"):
            svc._maybe_reload_tts()
        first = svc._fallback_tts_hash

        cfg["tts"]["fallback_module"] = "fb-two"
        with patch("ovos_audio.service.Configuration", return_value=cfg), \
             patch("ovos_audio.service.TTSFactory.create", return_value=MagicMock()), \
             patch.object(svc, "_get_tts_fallback"):
            svc._maybe_reload_tts()

        self.assertNotEqual(first, svc._fallback_tts_hash,
                            "the fallback module name is not part of its hash")


class TestFallbackReloadReplacesTheEngine(unittest.TestCase):
    """Reloading the fallback must produce the NEW plugin, not the old one.

    `_get_tts_fallback` is lazy: it builds an engine only `if not
    self.fallback_tts`. Shutting the old one down does not clear the attribute,
    so the reload branch shut the engine down and then handed the same dead
    object straight back. The tests around this mocked `_get_tts_fallback`,
    which is exactly why it went unseen.
    """

    def test_changing_the_fallback_module_builds_the_new_one(self):
        old_fallback = MagicMock()
        svc = _make_svc(tts=MagicMock(), fallback_tts=old_fallback)
        svc._tts_hash = None
        svc._fallback_tts_hash = "stale"

        cfg = {"tts": {"module": "main", "fallback_module": "fb-two",
                       "preload_fallback": True}}
        created = []

        def _create(config):
            engine = MagicMock()
            created.append(config.get("tts", {}).get("module"))
            return engine

        # _get_tts_fallback is deliberately NOT mocked: it is what was broken.
        with patch("ovos_audio.service.Configuration", return_value=cfg), \
             patch("ovos_audio.service.TTSFactory.create", side_effect=_create):
            svc._maybe_reload_tts()

        old_fallback.shutdown.assert_called_once()
        self.assertIsNot(svc.fallback_tts, old_fallback,
                         "the shut-down fallback engine is still in use")
        self.assertIn("fb-two", created,
                      f"the replacement fallback was never built: {created}")
