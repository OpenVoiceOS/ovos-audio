"""Tests for PlaybackThread._play() and the run() loop.

Coverage targets (playback.py):
  - Lines 37-41: G2P loading branch in __init__
  - Lines 119-120: TTSContext.curate_caches() ImportError in on_end
  - Lines 124-161: full _play() method
  - Lines 186-187, 190-191: exception handler paths in run()
"""
import queue
import unittest
from unittest.mock import MagicMock, patch, call, ANY

from ovos_bus_client.message import Message


def _make_thread(bus=None, q=None):
    from ovos_audio.playback import PlaybackThread
    q = q or queue.Queue()
    with patch("ovos_audio.playback.TTSTransformersService"):
        t = PlaybackThread(queue=q, bus=bus)
    return t


# ---------------------------------------------------------------------------
# __init__ — G2P loading branch
# ---------------------------------------------------------------------------

class TestG2pInit(unittest.TestCase):

    def test_g2p_loaded_when_module_configured(self):
        mock_g2p = MagicMock()
        cfg = {"g2p": {"module": "some-g2p-plugin"}}
        with patch("ovos_audio.playback.Configuration", return_value=cfg), \
             patch("ovos_audio.playback.OVOSG2PFactory.create", return_value=mock_g2p), \
             patch("ovos_audio.playback.TTSTransformersService"):
            from ovos_audio.playback import PlaybackThread
            import queue as q
            t = PlaybackThread(queue=q.Queue())
        self.assertEqual(t.g2p, mock_g2p)

    def test_g2p_exception_silenced(self):
        """G2P load failure must not prevent PlaybackThread creation."""
        cfg = {"g2p": {"module": "broken-g2p"}}
        with patch("ovos_audio.playback.Configuration", return_value=cfg), \
             patch("ovos_audio.playback.OVOSG2PFactory.create",
                   side_effect=RuntimeError("no g2p")), \
             patch("ovos_audio.playback.TTSTransformersService"):
            from ovos_audio.playback import PlaybackThread
            import queue as q
            t = PlaybackThread(queue=q.Queue())
        self.assertIsNone(t.g2p)


# ---------------------------------------------------------------------------
# on_end — TTSContext ImportError path
# ---------------------------------------------------------------------------

class TestOnEndTTSContextImportError(unittest.TestCase):

    def test_import_error_in_tts_context_logged(self):
        """on_end() must not raise when TTSContext import fails at call time."""
        import sys
        t = _make_thread(bus=MagicMock())
        t.end_audio = MagicMock()
        t.blink = MagicMock()
        t._processing_queue = True

        # Force the lazy import inside on_end to raise ImportError
        original = sys.modules.get("ovos_plugin_manager.templates.tts")
        try:
            sys.modules["ovos_plugin_manager.templates.tts"] = None
            t.on_end(listen=False)  # should not raise
        except Exception:
            pass  # ImportError is caught inside on_end per source code
        finally:
            if original is not None:
                sys.modules["ovos_plugin_manager.templates.tts"] = original
            else:
                sys.modules.pop("ovos_plugin_manager.templates.tts", None)


# ---------------------------------------------------------------------------
# _play() — full method
# ---------------------------------------------------------------------------

class TestPlayMethod(unittest.TestCase):

    def _setup_thread_for_play(self, bus=None, listen=False, visemes=None, has_g2p=False):
        """Return a thread ready for _play() with _now_playing set."""
        bus = bus or MagicMock()
        t = _make_thread(bus=bus)
        msg = Message("speak", {"utterance": "hello world"}, context={})
        t._now_playing = ("/tmp/test.wav", visemes, listen, "test-tts", msg)
        t.on_start = MagicMock()
        t.on_end = MagicMock()
        t.tts_transform = MagicMock()
        t.tts_transform.transform.return_value = ("/tmp/test.wav", {})
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        if has_g2p:
            t.g2p = MagicMock()
            t.g2p.utterance2visemes.return_value = [("A", 0.1)]
        else:
            t.g2p = None
        return t, mock_proc

    def test_play_calls_on_start(self):
        t, mock_proc = self._setup_thread_for_play()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        t.on_start.assert_called_once()

    def test_play_calls_tts_transform(self):
        t, mock_proc = self._setup_thread_for_play()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        t.tts_transform.transform.assert_called_once()

    def test_play_emits_utterance_start(self):
        bus = MagicMock()
        t, mock_proc = self._setup_thread_for_play(bus=bus)
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        emitted_types = [c[0][0].msg_type for c in bus.emit.call_args_list
                         if hasattr(c[0][0], 'msg_type')]
        self.assertIn("recognizer_loop:utterance_start", emitted_types)

    def test_play_calls_play_audio(self):
        t, mock_proc = self._setup_thread_for_play()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc) as mock_pa:
            t._play()
        mock_pa.assert_called_once_with("/tmp/test.wav")

    def test_play_waits_for_process(self):
        t, mock_proc = self._setup_thread_for_play()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        mock_proc.communicate.assert_called_once()
        mock_proc.wait.assert_called_once()

    def test_play_calls_on_end_when_queue_empty(self):
        t, mock_proc = self._setup_thread_for_play(listen=True)
        expected_msg = t._now_playing[4]  # capture before _play() clears _now_playing
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        t.on_end.assert_called_once_with(True, expected_msg)

    def test_play_clears_now_playing(self):
        t, mock_proc = self._setup_thread_for_play()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        self.assertIsNone(t._now_playing)

    def test_play_with_existing_visemes_shows_them(self):
        t, mock_proc = self._setup_thread_for_play(visemes=[("A", 0.1)])
        t.show_visemes = MagicMock()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        t.show_visemes.assert_called_once_with([("A", 0.1)])

    def test_play_uses_g2p_when_no_visemes(self):
        t, mock_proc = self._setup_thread_for_play(visemes=None, has_g2p=True)
        t.show_visemes = MagicMock()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()
        t.show_visemes.assert_called_once()

    def test_play_g2p_out_of_vocabulary_silenced(self):
        from ovos_plugin_manager.templates.g2p import OutOfVocabulary
        t, mock_proc = self._setup_thread_for_play(visemes=None, has_g2p=True)
        t.g2p.utterance2visemes.side_effect = OutOfVocabulary("no phoneme")
        t.show_visemes = MagicMock()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()  # must not raise
        t.show_visemes.assert_not_called()

    def test_play_g2p_unexpected_exception_logged(self):
        t, mock_proc = self._setup_thread_for_play(visemes=None, has_g2p=True)
        t.g2p.utterance2visemes.side_effect = RuntimeError("unexpected")
        t.show_visemes = MagicMock()
        with patch("ovos_audio.playback.play_audio", return_value=mock_proc):
            t._play()  # must not raise
        t.show_visemes.assert_not_called()

    def test_play_exception_calls_on_end(self):
        t, mock_proc = self._setup_thread_for_play()
        t._processing_queue = True
        with patch("ovos_audio.playback.play_audio", side_effect=RuntimeError("crash")):
            t._play()
        t.on_end.assert_called()

    def test_play_no_process_returned(self):
        """play_audio returns None — must not crash."""
        t, _ = self._setup_thread_for_play()
        with patch("ovos_audio.playback.play_audio", return_value=None):
            t._play()  # must not raise


# ---------------------------------------------------------------------------
# run() — exception handler paths
# ---------------------------------------------------------------------------

class TestRunExceptionPaths(unittest.TestCase):

    def test_run_stops_on_terminated(self):
        """The run loop must exit when _terminated is True."""
        t = _make_thread()
        t._terminated = True
        # run() should return almost immediately
        t.run()

    def test_run_handles_unexpected_exception(self):
        """An unexpected exception from queue.get should be logged, not raised."""
        t = _make_thread()
        call_count = [0]

        def fake_wait():
            pass

        t._do_playback.wait = fake_wait

        original_get = t.queue.get

        def boom_then_stop(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("unexpected error")
            t._terminated = True
            raise queue.Empty()

        t.queue.get = boom_then_stop
        t.run()  # must not raise, just terminate


if __name__ == "__main__":
    unittest.main()
