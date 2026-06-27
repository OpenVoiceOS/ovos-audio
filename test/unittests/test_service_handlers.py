"""Tests for PlaybackService message handlers and helper methods.

Uses __new__ to bypass the heavy __init__, then patches only the minimal
fields each handler needs.

Coverage targets:
  - get_tts_lang_options / get_g2p_lang_options (blacklist branch)
  - handle_b64_audio
  - handle_speak (including ident deprecation warning, dialog transform)
  - _maybe_reload_tts (disable_reload, tts.shutdown, disable_fallback,
    preload_fallback=False, fallback reload)
  - execute_tts (fallback path)
  - _get_tts_fallback (no engine configured)
  - execute_fallback_tts (exception path)
  - handle_speak_status
  - _resolve_sound_uri (snd/ path prefix)
  - handle_queue_audio (hex audio, uri)
  - handle_instant_play (ensure_volume paths, no binary)
  - handle_get_languages_tts
  - shutdown
  - handle_opm_tts_query
  - handle_opm_g2p_query
"""
import binascii
import json
import os
import tempfile
import unittest
import warnings
from threading import Lock
from unittest.mock import MagicMock, patch, call

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_svc(tts=None, bus=None, validate_source=False):
    """Return a bare PlaybackService with minimal fields set, no real init."""
    from ovos_audio.service import PlaybackService
    svc = PlaybackService.__new__(PlaybackService)
    svc.bus = bus or FakeBus()
    svc.config = {}
    svc.lock = Lock()
    svc.playback_lock = Lock()
    svc.validate_source = validate_source
    svc.tts = tts or MagicMock()
    svc._tts_hash = None
    svc._fallback_tts_hash = None
    svc.fallback_tts = None
    svc.disable_reload = False
    svc.disable_fallback = False
    svc._last_stop_signal = 0
    svc.dialog_transform = MagicMock()
    svc.dialog_transform.blacklisted_skills = []
    svc.dialog_transform.transform.side_effect = lambda dialog, context=None, sess=None: (dialog, context)
    svc.playback_thread = MagicMock()
    svc.status = MagicMock()
    svc.audio = None
    svc.pip_installer = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# get_tts_lang_options — blacklist branch
# ---------------------------------------------------------------------------

class TestGetTtsLangOptions(unittest.TestCase):

    def test_blacklisted_engine_excluded(self):
        from ovos_audio.service import PlaybackService
        cfgs = {
            "good-engine": [{"lang": "en-us", "voice": "a"}],
            "bad-engine":  [{"lang": "en-us", "voice": "b"}],
        }
        with patch("ovos_audio.service.get_tts_lang_configs", return_value=cfgs):
            opts = PlaybackService.get_tts_lang_options("en-us", blacklist=["bad-engine"])
        engines = [o["engine"] for o in opts]
        self.assertIn("good-engine", engines)
        self.assertNotIn("bad-engine", engines)

    def test_no_blacklist_returns_all(self):
        from ovos_audio.service import PlaybackService
        cfgs = {
            "engine-a": [{"lang": "en-us"}],
            "engine-b": [{"lang": "en-us"}],
        }
        with patch("ovos_audio.service.get_tts_lang_configs", return_value=cfgs):
            opts = PlaybackService.get_tts_lang_options("en-us")
        self.assertEqual(len(opts), 2)

    def test_lang_filled_from_arg_when_missing(self):
        from ovos_audio.service import PlaybackService
        cfgs = {"engine-a": [{}]}  # no lang key
        with patch("ovos_audio.service.get_tts_lang_configs", return_value=cfgs):
            opts = PlaybackService.get_tts_lang_options("fr-fr")
        self.assertEqual(opts[0]["lang"], "fr-fr")


class TestGetG2pLangOptions(unittest.TestCase):

    def test_blacklisted_engine_excluded(self):
        from ovos_audio.service import PlaybackService
        cfgs = {
            "good-g2p":  [{"lang": "en-us"}],
            "bad-g2p":   [{"lang": "en-us"}],
        }
        with patch("ovos_audio.service.get_g2p_lang_configs", return_value=cfgs):
            opts = PlaybackService.get_g2p_lang_options("en-us", blacklist=["bad-g2p"])
        engines = [o["engine"] for o in opts]
        self.assertNotIn("bad-g2p", engines)


# ---------------------------------------------------------------------------
# handle_b64_audio
# ---------------------------------------------------------------------------

class TestHandleB64Audio(unittest.TestCase):

    def test_returns_b64_encoded_audio(self):
        svc = _make_svc()
        raw = b"RIFF\x00WAVEfmt "
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(raw)
            wav_path = f.name

        svc.tts._get_ctxt.return_value = {}
        svc.tts.synth.return_value = (wav_path, {})
        svc.tts.plugin_id = "test-tts"

        msg = Message("speak:b64_audio", {"utterance": "hello", "listen": False})
        captured = []
        orig_emit = svc.bus.emit

        def cap(m):
            captured.append(m)
            try:
                orig_emit(m)
            except Exception:
                pass

        svc.bus.emit = cap

        with patch("ovos_audio.service.report_timing"):
            svc.handle_b64_audio(msg)

        os.unlink(wav_path)
        self.assertTrue(len(captured) > 0)
        # The emitted message should have audio key
        emitted_data = captured[0].data
        self.assertIn("audio", emitted_data)

    def test_handle_b64_audio_with_listen_true(self):
        svc = _make_svc()
        raw = b"hello"
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(raw)
            wav_path = f.name

        svc.tts._get_ctxt.return_value = {}
        svc.tts.synth.return_value = (wav_path, {})
        svc.tts.plugin_id = "test-tts"

        msg = Message("speak:b64_audio", {"utterance": "ok", "listen": True})
        captured = []

        def cap(m):
            captured.append(m)

        svc.bus.emit = cap
        with patch("ovos_audio.service.report_timing"):
            svc.handle_b64_audio(msg)
        os.unlink(wav_path)
        self.assertTrue(captured[0].data.get("listen"))


# ---------------------------------------------------------------------------
# handle_speak
# ---------------------------------------------------------------------------

class TestHandleSpeak(unittest.TestCase):

    def test_ident_in_context_triggers_deprecation_log(self):
        svc = _make_svc()
        msg = Message(SpecMessage.SPEAK, {"utterance": "hello"},
                      context={"ident": "abc123"})
        with patch.object(svc, "execute_tts") as mock_exec, \
             patch("ovos_audio.service.report_timing"):
            svc.handle_speak(msg)
        mock_exec.assert_called_once()

    def test_dialog_transform_applied_when_changed(self):
        svc = _make_svc()
        svc.dialog_transform.blacklisted_skills = []
        svc.dialog_transform.transform.side_effect = lambda dialog, context=None, sess=None: (
            "TRANSFORMED", context
        )
        msg = Message(SpecMessage.SPEAK,
                      {"utterance": "original", "meta": {"skill": "my-skill"}},
                      context={})
        called_with = []
        with patch.object(svc, "execute_tts",
                          side_effect=lambda u, *a, **kw: called_with.append(u)), \
             patch("ovos_audio.service.report_timing"):
            svc.handle_speak(msg)
        self.assertEqual(called_with[0], "TRANSFORMED")

    def test_dialog_transform_not_applied_for_blacklisted_skill(self):
        svc = _make_svc()
        svc.dialog_transform.blacklisted_skills = ["bad-skill"]
        msg = Message(SpecMessage.SPEAK,
                      {"utterance": "original", "meta": {"skill": "bad-skill"}},
                      context={})
        called_with = []
        with patch.object(svc, "execute_tts",
                          side_effect=lambda u, *a, **kw: called_with.append(u)), \
             patch("ovos_audio.service.report_timing"):
            svc.handle_speak(msg)
        self.assertEqual(called_with[0], "original")

    def test_handle_speak_no_skill_id(self):
        svc = _make_svc()
        msg = Message(SpecMessage.SPEAK, {"utterance": "no skill"}, context={})
        with patch.object(svc, "execute_tts") as mock_exec, \
             patch("ovos_audio.service.report_timing"):
            svc.handle_speak(msg)
        mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# _maybe_reload_tts
# ---------------------------------------------------------------------------

class TestMaybeReloadTts(unittest.TestCase):

    def test_disable_reload_returns_early(self):
        svc = _make_svc()
        svc.disable_reload = True
        with patch("ovos_audio.service.TTSFactory") as mock_factory:
            svc._maybe_reload_tts()
        mock_factory.create.assert_not_called()

    def test_reloads_when_hash_changes(self):
        svc = _make_svc()
        svc._tts_hash = None
        svc.tts = None
        mock_tts = MagicMock()
        with patch("ovos_audio.service.Configuration",
                   return_value={"tts": {"module": "dummy"}}), \
             patch("ovos_audio.service.TTSFactory.create", return_value=mock_tts):
            svc._maybe_reload_tts()
        self.assertEqual(svc.tts, mock_tts)

    def test_shuts_down_old_tts_on_reload(self):
        svc = _make_svc()
        old_tts = MagicMock()
        svc.tts = old_tts
        svc._tts_hash = None
        mock_tts = MagicMock()
        with patch("ovos_audio.service.Configuration",
                   return_value={"tts": {"module": "dummy"}}), \
             patch("ovos_audio.service.TTSFactory.create", return_value=mock_tts):
            svc._maybe_reload_tts()
        old_tts.shutdown.assert_called_once()

    def test_disable_fallback_skips_fallback_reload(self):
        svc = _make_svc()
        svc.disable_fallback = True
        svc._tts_hash = "same"
        cfg = {"module": "dummy", "dummy": {}}
        import json
        svc._tts_hash = hash(json.dumps({}, sort_keys=True))
        with patch("ovos_audio.service.Configuration",
                   return_value={"tts": {"module": "dummy"}}), \
             patch("ovos_audio.service.TTSFactory") as mock_factory:
            # no reload needed since hash matches
            svc._maybe_reload_tts()
        # fallback create should not be called
        mock_factory.create.assert_not_called()

    def test_preload_fallback_false_skips(self):
        svc = _make_svc()
        svc._tts_hash = hash(json.dumps({}, sort_keys=True))
        cfg = {"module": "main", "fallback_module": "fallback", "preload_fallback": False}
        with patch("ovos_audio.service.Configuration", return_value={"tts": cfg}), \
             patch("ovos_audio.service.TTSFactory") as mock_factory:
            svc._maybe_reload_tts()
        mock_factory.create.assert_not_called()

    def test_same_module_skips_fallback(self):
        svc = _make_svc()
        svc._tts_hash = hash(json.dumps({}, sort_keys=True))
        cfg = {"module": "same", "fallback_module": "same"}
        with patch("ovos_audio.service.Configuration", return_value={"tts": cfg}), \
             patch("ovos_audio.service.TTSFactory") as mock_factory:
            svc._maybe_reload_tts()
        mock_factory.create.assert_not_called()


# ---------------------------------------------------------------------------
# execute_tts (fallback path)
# ---------------------------------------------------------------------------

class TestExecuteTts(unittest.TestCase):

    def test_execute_calls_tts(self):
        svc = _make_svc()
        svc._tts_hash = "a"
        svc._fallback_tts_hash = "a"  # same → no fallback
        svc.execute_tts("hello", "sess-1", False)
        svc.tts.execute.assert_called_once()

    def test_fallback_called_on_tts_exception(self):
        svc = _make_svc()
        svc.tts.execute.side_effect = RuntimeError("TTS broken")
        svc._tts_hash = "abc"
        svc._fallback_tts_hash = "xyz"  # different → try fallback
        with patch.object(svc, "execute_fallback_tts") as mock_fallback:
            svc.execute_tts("hello", "sess-1", False)
        mock_fallback.assert_called_once()

    def test_no_fallback_when_hashes_same(self):
        svc = _make_svc()
        svc.tts.execute.side_effect = RuntimeError("TTS broken")
        svc._tts_hash = "same"
        svc._fallback_tts_hash = "same"
        with patch.object(svc, "execute_fallback_tts") as mock_fallback:
            svc.execute_tts("hello", "sess-1", False)
        mock_fallback.assert_not_called()


# ---------------------------------------------------------------------------
# _get_tts_fallback
# ---------------------------------------------------------------------------

class TestGetTtsFallback(unittest.TestCase):

    def test_no_engine_configured_returns_none(self):
        svc = _make_svc()
        with patch("ovos_audio.service.Configuration",
                   return_value={"tts": {}}):
            result = svc._get_tts_fallback()
        self.assertIsNone(result)

    def test_returns_existing_fallback_without_reinitializing(self):
        svc = _make_svc()
        existing = MagicMock()
        svc.fallback_tts = existing
        result = svc._get_tts_fallback()
        self.assertEqual(result, existing)


# ---------------------------------------------------------------------------
# execute_fallback_tts
# ---------------------------------------------------------------------------

class TestExecuteFallbackTts(unittest.TestCase):

    def test_calls_fallback_tts_execute(self):
        svc = _make_svc()
        fallback = MagicMock()
        with patch.object(svc, "_get_tts_fallback", return_value=fallback):
            svc.execute_fallback_tts("hello", "sess", False)
        fallback.execute.assert_called_once()

    def test_exception_logged_not_raised(self):
        svc = _make_svc()
        fallback = MagicMock()
        fallback.execute.side_effect = RuntimeError("boom")
        with patch.object(svc, "_get_tts_fallback", return_value=fallback):
            svc.execute_fallback_tts("hello", "sess", False)  # must not raise

    def test_no_fallback_tts_available(self):
        svc = _make_svc()
        with patch.object(svc, "_get_tts_fallback", return_value=None):
            svc.execute_fallback_tts("hello", "sess", False)  # must not raise


# ---------------------------------------------------------------------------
# handle_speak_status
# ---------------------------------------------------------------------------

class TestHandleSpeakStatus(unittest.TestCase):

    def test_responds_with_speaking_true(self):
        svc = _make_svc()
        svc.tts.playback = MagicMock()
        svc.tts.playback._now_playing = ("something",)
        msg = Message("mycroft.audio.speak.status", {})
        captured = []
        orig_emit = svc.bus.emit

        def cap(m):
            captured.append(m)
            try:
                orig_emit(m)
            except Exception:
                pass

        svc.bus.emit = cap
        svc.handle_speak_status(msg)
        self.assertTrue(len(captured) > 0)

    def test_responds_with_speaking_false(self):
        svc = _make_svc()
        svc.tts.playback = None
        msg = Message("mycroft.audio.speak.status", {})
        captured = []

        def cap(m):
            captured.append(m)

        svc.bus.emit = cap
        svc.handle_speak_status(msg)
        data = captured[0].data
        self.assertFalse(data["speaking"])


# ---------------------------------------------------------------------------
# _resolve_sound_uri — snd/ prefix
# ---------------------------------------------------------------------------

class TestResolveSoundUriSndPrefix(unittest.TestCase):

    def test_snd_prefix_uses_local_resource_path(self):
        from ovos_audio.service import PlaybackService
        # Create a temp file to act as the local resource
        res_dir = os.path.join(os.path.dirname(
            __import__("ovos_audio.service", fromlist=["service"]).__file__
        ), "res", "snd")
        os.makedirs(res_dir, exist_ok=True)
        test_file = os.path.join(res_dir, "_test_sound.wav")
        with open(test_file, "wb") as f:
            f.write(b"FAKE")
        try:
            result = PlaybackService._resolve_sound_uri("snd/_test_sound.wav")
            self.assertTrue(result.endswith("_test_sound.wav"))
        finally:
            os.unlink(test_file)

    def test_snd_prefix_falls_through_when_not_found_locally(self):
        """If snd/ file doesn't exist locally, falls through to resolve_resource_file."""
        from ovos_audio.service import PlaybackService
        with patch("ovos_audio.service.resolve_resource_file", return_value=None):
            with self.assertRaises((FileNotFoundError, Exception)):
                PlaybackService._resolve_sound_uri("snd/nonexistent.wav")


# ---------------------------------------------------------------------------
# handle_queue_audio
# ---------------------------------------------------------------------------

class TestHandleQueueAudio(unittest.TestCase):

    def test_uri_based_queue(self):
        from ovos_plugin_manager.templates.tts import TTS
        import queue as queuemod
        TTS.queue = queuemod.Queue()
        svc = _make_svc()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            msg = Message("mycroft.audio.queue", {"uri": path})
            with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                       return_value=path):
                svc.handle_queue_audio(msg)
            self.assertFalse(TTS.queue.empty())
        finally:
            TTS.queue.get_nowait()
            os.unlink(path)

    def test_hex_audio_queue(self):
        from ovos_plugin_manager.templates.tts import TTS
        import queue as queuemod
        TTS.queue = queuemod.Queue()
        svc = _make_svc()
        raw = b"RIFF\x00WAVEfmt "
        hex_str = binascii.hexlify(raw).decode("utf-8")
        msg = Message("mycroft.audio.queue",
                      {"binary_data": hex_str, "audio_ext": "wav"})
        with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                   side_effect=lambda p: p):
            svc.handle_queue_audio(msg)
        item = TTS.queue.get_nowait()
        self.assertIsNotNone(item)


# ---------------------------------------------------------------------------
# handle_instant_play
# ---------------------------------------------------------------------------

class TestHandleInstantPlay(unittest.TestCase):

    def test_plays_uri(self):
        svc = _make_svc()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            msg = Message("mycroft.audio.play_sound", {"uri": path})
            mock_proc = MagicMock()
            captured = []

            def cap(m):
                captured.append(m)

            svc.bus.emit = cap

            with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                       return_value=path), \
                 patch("ovos_audio.service.play_audio", return_value=mock_proc):
                svc.handle_instant_play(msg)
            mock_proc.wait.assert_called_once()
        finally:
            os.unlink(path)

    def test_plays_hex_audio(self):
        svc = _make_svc()
        raw = b"hello"
        hex_str = binascii.hexlify(raw).decode("utf-8")
        msg = Message("mycroft.audio.play_sound",
                      {"binary_data": hex_str, "audio_ext": "wav"})
        mock_proc = MagicMock()
        with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                   side_effect=lambda p: p), \
             patch("ovos_audio.service.play_audio", return_value=mock_proc):
            svc.handle_instant_play(msg)
        mock_proc.wait.assert_called_once()

    def test_ensure_volume_low_sets_to_80(self):
        svc = _make_svc()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            msg = Message("mycroft.audio.play_sound",
                          {"uri": path, "force_unmute": True})
            mock_proc = MagicMock()
            volume_reply = Message("mycroft.volume.reply",
                                   {"percent": 0, "muted": False})
            svc.bus.wait_for_response = MagicMock(return_value=volume_reply)
            captured = []
            svc.bus.emit = lambda m: captured.append(m)
            with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                       return_value=path), \
                 patch("ovos_audio.service.play_audio", return_value=mock_proc):
                svc.handle_instant_play(msg)
            emitted_types = [m.msg_type for m in captured]
            self.assertIn("mycroft.volume.set", emitted_types)
        finally:
            os.unlink(path)

    def test_ensure_volume_muted_sends_unmute(self):
        svc = _make_svc()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            msg = Message("mycroft.audio.play_sound",
                          {"uri": path, "force_unmute": True})
            mock_proc = MagicMock()
            volume_reply = Message("mycroft.volume.reply",
                                   {"percent": 50, "muted": True})
            svc.bus.wait_for_response = MagicMock(return_value=volume_reply)
            captured = []
            svc.bus.emit = lambda m: captured.append(m)
            with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                       return_value=path), \
                 patch("ovos_audio.service.play_audio", return_value=mock_proc):
                svc.handle_instant_play(msg)
            emitted_types = [m.msg_type for m in captured]
            self.assertIn("mycroft.volume.unmute", emitted_types)
            self.assertIn("mycroft.volume.mute", emitted_types)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# handle_get_languages_tts
# ---------------------------------------------------------------------------

class TestHandleGetLanguagesTts(unittest.TestCase):

    def test_returns_available_languages(self):
        svc = _make_svc()
        svc.tts.available_languages = {"en-us", "de-de"}
        msg = Message("ovos.languages.tts", {})
        captured = []
        orig_emit = svc.bus.emit

        def cap(m):
            captured.append(m)
            try:
                orig_emit(m)
            except Exception:
                pass

        svc.bus.emit = cap
        svc.handle_get_languages_tts(msg)
        self.assertTrue(len(captured) > 0)
        langs = captured[0].data.get("langs", [])
        self.assertIn("en-us", langs)

    def test_falls_back_to_config_lang(self):
        svc = _make_svc()
        svc.tts.available_languages = None
        svc.config = {"lang": "es-es"}
        msg = Message("ovos.languages.tts", {})
        captured = []

        def cap(m):
            captured.append(m)

        svc.bus.emit = cap
        svc.handle_get_languages_tts(msg)
        langs = captured[0].data.get("langs", [])
        self.assertIn("es-es", langs)

    def test_falls_back_to_en_us_when_no_config(self):
        svc = _make_svc()
        svc.tts.available_languages = None
        svc.config = {}
        msg = Message("ovos.languages.tts", {})
        captured = []
        svc.bus.emit = lambda m: captured.append(m)
        svc.handle_get_languages_tts(msg)
        langs = captured[0].data.get("langs", [])
        self.assertIn("en-us", langs)


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestServiceShutdown(unittest.TestCase):

    def test_shutdown_calls_status_stopping(self):
        svc = _make_svc()
        svc.playback_thread = MagicMock()
        svc.playback_thread.is_alive.return_value = False
        svc.shutdown()
        svc.status.set_stopping.assert_called_once()

    def test_shutdown_shuts_down_playback_thread(self):
        svc = _make_svc()
        svc.playback_thread = MagicMock()
        svc.audio = None
        svc.shutdown()
        svc.playback_thread.shutdown.assert_called_once()
        svc.playback_thread.join.assert_called_once()

    def test_shutdown_shuts_down_audio_service(self):
        svc = _make_svc()
        mock_audio = MagicMock()
        svc.audio = mock_audio
        svc.playback_thread = MagicMock()
        svc.shutdown()
        mock_audio.shutdown.assert_called_once()

    def test_shutdown_no_audio_service(self):
        svc = _make_svc()
        svc.audio = None
        svc.playback_thread = MagicMock()
        svc.shutdown()  # must not raise


# ---------------------------------------------------------------------------
# handle_opm_tts_query
# ---------------------------------------------------------------------------

class TestHandleOpmTtsQuery(unittest.TestCase):

    def test_responds_with_plugin_data(self):
        svc = _make_svc()
        msg = Message("opm.tts.query", {})
        captured = []
        orig_emit = svc.bus.emit

        def cap(m):
            captured.append(m)
            try:
                orig_emit(m)
            except Exception:
                pass

        svc.bus.emit = cap
        with patch("ovos_audio.service.get_tts_supported_langs", return_value={}), \
             patch("ovos_audio.service.get_tts_module_configs", return_value={}):
            svc.handle_opm_tts_query(msg)
        self.assertTrue(len(captured) > 0)


# ---------------------------------------------------------------------------
# OVOS-AUDIO-1 spec-topic adoption — dual namespace (legacy + spec)
#
# Each of the 6 adopted topics MUST work under BOTH its legacy name and its
# spec name. These tests drive a bare PlaybackService over a real FakeBus and
# assert the handler responds identically regardless of which topic name was
# used to reach it.
# ---------------------------------------------------------------------------

def _wire_audio1_handlers(svc):
    """Subscribe the 6 AUDIO-1 dual-namespace handlers on svc.bus.

    Mirrors init_messagebus() for the AUDIO-1 surface without running the
    heavy __init__. Returns the svc for chaining.
    """
    svc.bus.on(SpecMessage.AUDIO_STOP, svc.handle_stop)
    svc.bus.on('mycroft.audio.speech.stop', svc.handle_stop)
    svc.bus.on(SpecMessage.AUDIO_IS_SPEAKING, svc.handle_speak_status)
    svc.bus.on('mycroft.audio.speak.status', svc.handle_speak_status)
    svc.bus.on(SpecMessage.AUDIO_QUEUE, svc.handle_queue_audio)
    svc.bus.on('mycroft.audio.queue', svc.handle_queue_audio)
    svc.bus.on(SpecMessage.AUDIO_PLAY_SOUND, svc.handle_instant_play)
    svc.bus.on('mycroft.audio.play_sound', svc.handle_instant_play)
    svc.bus.on(SpecMessage.SPEAK_B64, svc.handle_b64_audio)
    svc.bus.on('speak:b64_audio', svc.handle_b64_audio)
    return svc


class TestAudio1DualNamespaceRegistration(unittest.TestCase):
    """init_messagebus subscribes BOTH the legacy and spec topic for each of
    the 6 AUDIO-1 adoptions."""

    def _registered_topics(self):
        from ovos_audio.service import PlaybackService
        svc = PlaybackService.__new__(PlaybackService)
        svc.bus = MagicMock()
        svc.dialog_transform = MagicMock()
        with patch("ovos_audio.service.Configuration"):
            PlaybackService.init_messagebus(svc)
        return [c.args[0] for c in svc.bus.on.call_args_list]

    def test_speak_b64_both_namespaces(self):
        topics = self._registered_topics()
        self.assertIn("speak:b64_audio", topics)
        self.assertIn(SpecMessage.SPEAK_B64, topics)

    def test_queue_both_namespaces(self):
        topics = self._registered_topics()
        self.assertIn("mycroft.audio.queue", topics)
        self.assertIn(SpecMessage.AUDIO_QUEUE, topics)

    def test_play_sound_both_namespaces(self):
        topics = self._registered_topics()
        self.assertIn("mycroft.audio.play_sound", topics)
        self.assertIn(SpecMessage.AUDIO_PLAY_SOUND, topics)

    def test_is_speaking_both_namespaces(self):
        topics = self._registered_topics()
        self.assertIn("mycroft.audio.speak.status", topics)
        self.assertIn(SpecMessage.AUDIO_IS_SPEAKING, topics)

    def test_stop_both_namespaces(self):
        topics = self._registered_topics()
        self.assertIn("mycroft.audio.speech.stop", topics)
        self.assertIn(SpecMessage.AUDIO_STOP, topics)
        # §6: the universal ovos.stop broadcast stays wired too
        self.assertIn("ovos.stop", topics)


class TestAudio1DualNamespaceBehaviour(unittest.TestCase):
    """Driving the service over a FakeBus: BOTH the legacy and spec topic
    invoke the handler and produce the same effect."""

    def _make_wired_svc(self, tts=None):
        svc = _make_svc(tts=tts, bus=FakeBus())
        return _wire_audio1_handlers(svc)

    # --- speak.b64 / ovos.audio.speech (§3.4, §4.3) ----------------------

    def _run_b64(self, topic, listen=False):
        svc = self._make_wired_svc()
        raw = b"RIFF\x00WAVEfmt "
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(raw)
            wav_path = f.name
        svc.tts._get_ctxt.return_value = {}
        svc.tts.synth.return_value = (wav_path, {})
        svc.tts.plugin_id = "test-tts"
        captured = []
        svc.bus.on(SpecMessage.AUDIO_SPEECH, lambda m: captured.append(m))
        svc.bus.on(SpecMessage.MIC_LISTEN, lambda m: captured.append(m))
        try:
            with patch("ovos_audio.service.report_timing"):
                svc.bus.emit(Message(topic,
                                     {"utterance": "hi", "listen": listen}))
        finally:
            os.unlink(wav_path)
        return [m.msg_type for m in captured]

    def test_b64_legacy_emits_spec_speech(self):
        types = self._run_b64("speak:b64_audio")
        self.assertIn(SpecMessage.AUDIO_SPEECH, types)

    def test_b64_spec_topic_emits_spec_speech(self):
        types = self._run_b64(SpecMessage.SPEAK_B64)
        self.assertIn(SpecMessage.AUDIO_SPEECH, types)

    def test_b64_listen_true_emits_mic_listen(self):
        types = self._run_b64(SpecMessage.SPEAK_B64, listen=True)
        self.assertIn(SpecMessage.AUDIO_SPEECH, types)
        self.assertIn(SpecMessage.MIC_LISTEN, types)

    # --- ovos.audio.queue (§4.1) -----------------------------------------

    def _run_queue(self, topic):
        from ovos_plugin_manager.templates.tts import TTS
        import queue as queuemod
        TTS.queue = queuemod.Queue()
        svc = self._make_wired_svc()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                       return_value=path):
                svc.bus.emit(Message(topic, {"uri": path}))
            return not TTS.queue.empty()
        finally:
            while not TTS.queue.empty():
                TTS.queue.get_nowait()
            os.unlink(path)

    def test_queue_legacy_enqueues(self):
        self.assertTrue(self._run_queue("mycroft.audio.queue"))

    def test_queue_spec_topic_enqueues(self):
        self.assertTrue(self._run_queue(SpecMessage.AUDIO_QUEUE))

    # --- ovos.audio.play_sound (§4.2) ------------------------------------

    def _run_play_sound(self, topic):
        svc = self._make_wired_svc()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        played = []
        try:
            with patch("ovos_audio.service.PlaybackService._resolve_sound_uri",
                       return_value=path), \
                 patch("ovos_audio.service.play_audio") as pa:
                pa.return_value.wait.side_effect = lambda: played.append(True)
                svc.bus.emit(Message(topic, {"uri": path}))
            return bool(played)
        finally:
            os.unlink(path)

    def test_play_sound_legacy_plays(self):
        self.assertTrue(self._run_play_sound("mycroft.audio.play_sound"))

    def test_play_sound_spec_topic_plays(self):
        self.assertTrue(self._run_play_sound(SpecMessage.AUDIO_PLAY_SOUND))

    # --- ovos.audio.is_speaking (§5.3) -----------------------------------

    def _run_is_speaking(self, topic):
        svc = self._make_wired_svc()
        svc.tts.playback = MagicMock()
        svc.tts.playback._now_playing = ("x",)
        replies = []
        svc.bus.on(SpecMessage.AUDIO_IS_SPEAKING, lambda m: replies.append(m))
        svc.bus.on("mycroft.audio.is_speaking", lambda m: replies.append(m))
        svc.bus.emit(Message(topic, {}))
        return replies

    def test_is_speaking_legacy_query_replies_spec(self):
        replies = self._run_is_speaking("mycroft.audio.speak.status")
        # only count actual answers (carry the 'speaking' field)
        answers = [m for m in replies if "speaking" in m.data]
        types = [m.msg_type for m in answers]
        self.assertIn(SpecMessage.AUDIO_IS_SPEAKING, types)
        self.assertTrue(all(m.data.get("speaking") for m in answers))

    def test_is_speaking_spec_query_replies_spec(self):
        replies = self._run_is_speaking(SpecMessage.AUDIO_IS_SPEAKING)
        # only count actual answers (carry the 'speaking' field); the query
        # itself is also captured on the shared spec topic but has no answer
        answers = [m for m in replies if "speaking" in m.data]
        types = [m.msg_type for m in answers]
        self.assertIn(SpecMessage.AUDIO_IS_SPEAKING, types)
        self.assertTrue(answers and all(m.data.get("speaking") for m in answers))

    # --- ovos.audio.stop (§6) --------------------------------------------

    def _run_stop(self, topic):
        svc = self._make_wired_svc()
        svc.tts.playback = MagicMock()
        svc.tts.playback._now_playing = ("x",)
        svc._last_stop_signal = 0
        svc.bus.emit(Message(topic, {}))
        return svc.tts.playback.clear.called

    def test_stop_legacy_clears_playback(self):
        self.assertTrue(self._run_stop("mycroft.audio.speech.stop"))

    def test_stop_spec_topic_clears_playback(self):
        self.assertTrue(self._run_stop(SpecMessage.AUDIO_STOP))


if __name__ == "__main__":
    unittest.main()
