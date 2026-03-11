"""Unit tests for PlaybackThread.

Covers:
- Construction
- is_running property
- set_bus / init (deprecated)
- clear_queue
- begin_audio / end_audio with/without bus
- on_start / on_end
- show_visemes (with and without enclosure)
- pause / resume / clear / stop / shutdown
- blink (with and without enclosure)
"""
import queue
import unittest
from unittest.mock import MagicMock, patch, call


def _make_thread(bus=None, q=None):
    """Create a PlaybackThread without starting it."""
    from ovos_audio.playback import PlaybackThread
    q = q or queue.Queue()
    with patch("ovos_audio.playback.TTSTransformersService"):
        t = PlaybackThread(queue=q, bus=bus)
    return t


class TestPlaybackThreadInit(unittest.TestCase):

    def test_is_running_false_before_start(self):
        t = _make_thread()
        self.assertFalse(t.is_running)

    def test_init_stores_bus(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        self.assertEqual(t.bus, bus)

    def test_init_no_bus(self):
        t = _make_thread()
        self.assertIsNone(t.bus)

    def test_terminated_false_initially(self):
        t = _make_thread()
        self.assertFalse(t._terminated)


class TestSetBus(unittest.TestCase):

    def test_set_bus_updates_bus(self):
        t = _make_thread()
        bus = MagicMock()
        t.set_bus(bus)
        self.assertEqual(t.bus, bus)

    def test_set_bus_propagates_to_transform(self):
        t = _make_thread()
        bus = MagicMock()
        t.set_bus(bus)
        t.tts_transform.set_bus.assert_called_with(bus)

    def test_init_deprecated_calls_set_bus(self):
        t = _make_thread(bus=MagicMock())
        tts = MagicMock()
        tts.bus = MagicMock()
        t.init(tts)
        self.assertEqual(t.bus, tts.bus)


class TestClearQueue(unittest.TestCase):

    def test_clear_queue_empties_queue(self):
        q = queue.Queue()
        q.put("item1")
        q.put("item2")
        t = _make_thread(q=q)
        t.p = None
        t.clear_queue()
        self.assertTrue(q.empty())

    def test_clear_queue_terminates_process(self):
        t = _make_thread()
        mock_proc = MagicMock()
        t.p = mock_proc
        t.clear_queue()
        mock_proc.terminate.assert_called_once()

    def test_clear_queue_handles_terminate_exception(self):
        t = _make_thread()
        mock_proc = MagicMock()
        mock_proc.terminate.side_effect = OSError("fail")
        t.p = mock_proc
        # Should not raise
        t.clear_queue()


class TestBeginAudio(unittest.TestCase):

    def test_begin_audio_emits_output_start(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        t.begin_audio(message=msg)
        msg.forward.assert_any_call("recognizer_loop:audio_output_start")

    def test_begin_audio_no_bus_logs_warning(self):
        t = _make_thread(bus=None)
        # Should not raise
        t.begin_audio()

    def test_begin_audio_ocp_cork(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        cfg = {"tts": {"ocp_cork": True}}
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        with patch("ovos_audio.playback.Configuration", return_value=cfg):
            t.begin_audio(message=msg)
        emitted_types = [c[0][0].msg_type if hasattr(c[0][0], 'msg_type') else str(c[0][0])
                         for c in bus.emit.call_args_list]
        # bus.emit was called at least once
        self.assertTrue(bus.emit.called)

    def test_begin_audio_ocp_duck(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        cfg = {"tts": {"ocp_duck": True}}
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        with patch("ovos_audio.playback.Configuration", return_value=cfg):
            t.begin_audio(message=msg)
        self.assertTrue(bus.emit.called)


class TestEndAudio(unittest.TestCase):

    def test_end_audio_emits_output_end(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        t.end_audio(listen=False, message=msg)
        msg.forward.assert_any_call("recognizer_loop:audio_output_end")

    def test_end_audio_emits_listen_when_requested(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        t.end_audio(listen=True, message=msg)
        msg.forward.assert_any_call("mycroft.mic.listen")

    def test_end_audio_no_listen(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        t.end_audio(listen=False, message=msg)
        forwarded = [c[0][0] for c in msg.forward.call_args_list]
        self.assertNotIn("mycroft.mic.listen", forwarded)

    def test_end_audio_no_bus_logs_warning(self):
        t = _make_thread(bus=None)
        # Should not raise
        t.end_audio(listen=False)

    def test_end_audio_ocp_uncork(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        cfg = {"tts": {"ocp_cork": True}}
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        with patch("ovos_audio.playback.Configuration", return_value=cfg):
            t.end_audio(listen=False, message=msg)
        self.assertTrue(bus.emit.called)

    def test_end_audio_ocp_unduck(self):
        bus = MagicMock()
        t = _make_thread(bus=bus)
        cfg = {"tts": {"ocp_duck": True}}
        msg = MagicMock()
        msg.forward.return_value = MagicMock()
        with patch("ovos_audio.playback.Configuration", return_value=cfg):
            t.end_audio(listen=False, message=msg)
        self.assertTrue(bus.emit.called)


class TestOnStartOnEnd(unittest.TestCase):

    def test_on_start_sets_processing_flag(self):
        t = _make_thread(bus=MagicMock())
        t.begin_audio = MagicMock()
        t.blink = MagicMock()
        t._processing_queue = False
        t.on_start()
        self.assertTrue(t._processing_queue)
        t.begin_audio.assert_called_once()

    def test_on_start_already_processing_no_begin_audio(self):
        t = _make_thread(bus=MagicMock())
        t.begin_audio = MagicMock()
        t.blink = MagicMock()
        t._processing_queue = True
        t.on_start()
        t.begin_audio.assert_not_called()

    def test_on_end_clears_processing_flag(self):
        t = _make_thread(bus=MagicMock())
        t.end_audio = MagicMock()
        t.blink = MagicMock()
        t._processing_queue = True
        t.on_end(listen=False)
        self.assertFalse(t._processing_queue)
        t.end_audio.assert_called_once()

    def test_on_end_not_processing_no_end_audio(self):
        t = _make_thread(bus=MagicMock())
        t.end_audio = MagicMock()
        t.blink = MagicMock()
        t._processing_queue = False
        t.on_end(listen=False)
        t.end_audio.assert_not_called()


class TestShowVisemes(unittest.TestCase):

    def test_show_visemes_with_enclosure(self):
        t = _make_thread()
        t.enclosure = MagicMock()
        t.show_visemes([("A", 0.1)])
        t.enclosure.mouth_viseme.assert_called_once()

    def test_show_visemes_without_enclosure(self):
        t = _make_thread()
        t.enclosure = None
        # Should not raise
        t.show_visemes([("A", 0.1)])


class TestPauseResumeClear(unittest.TestCase):

    def test_pause_clears_do_playback_event(self):
        t = _make_thread()
        t._do_playback.set()
        t.p = None
        t.pause()
        self.assertFalse(t._do_playback.is_set())

    def test_pause_terminates_process(self):
        t = _make_thread()
        mock_proc = MagicMock()
        t.p = mock_proc
        t.pause()
        mock_proc.terminate.assert_called_once()

    def test_resume_sets_do_playback_event(self):
        t = _make_thread()
        t._do_playback.clear()
        t._now_playing = None
        t.resume()
        self.assertTrue(t._do_playback.is_set())

    def test_resume_calls_play_when_now_playing(self):
        t = _make_thread()
        t._now_playing = ("data", [], False, "id", MagicMock())
        t._play = MagicMock()
        t.resume()
        t._play.assert_called_once()

    def test_clear_calls_clear_queue(self):
        t = _make_thread()
        t.clear_queue = MagicMock()
        t.clear()
        t.clear_queue.assert_called_once()


class TestStopShutdown(unittest.TestCase):

    def test_stop_sets_terminated(self):
        t = _make_thread()
        t.clear_queue = MagicMock()
        t.stop()
        self.assertTrue(t._terminated)

    def test_stop_clears_now_playing(self):
        t = _make_thread()
        t._now_playing = ("something",)
        t.clear_queue = MagicMock()
        t.stop()
        self.assertIsNone(t._now_playing)

    def test_shutdown_calls_stop(self):
        t = _make_thread()
        t.stop = MagicMock()
        t.shutdown()
        t.stop.assert_called_once()


class TestBlink(unittest.TestCase):

    def test_blink_with_enclosure_full_rate(self):
        t = _make_thread()
        t.enclosure = MagicMock()
        t.blink(rate=1.0)
        t.enclosure.eyes_blink.assert_called_with("b")

    def test_blink_without_enclosure_no_error(self):
        t = _make_thread()
        t.enclosure = None
        t.blink(1.0)  # should not raise


if __name__ == "__main__":
    unittest.main()
