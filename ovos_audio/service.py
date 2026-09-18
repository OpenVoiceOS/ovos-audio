import base64
import json
import os
import warnings
import os.path
from hashlib import md5
from os.path import exists
from queue import Queue
from tempfile import gettempdir
from threading import Thread, Lock
from typing import Optional

import binascii
import time
from ovos_bus_client import Message, MessageBusClient
from ovos_bus_client.session import SessionManager
from ovos_config.config import Configuration
from ovos_plugin_manager.g2p import get_g2p_lang_configs, get_g2p_supported_langs, get_g2p_module_configs
from ovos_plugin_manager.tts import TTS
from ovos_plugin_manager.tts import get_tts_supported_langs, get_tts_lang_configs, get_tts_module_configs
from ovos_spec_tools import SpecMessage
from ovos_utils.file_utils import resolve_resource_file
from ovos_utils.log import LOG, deprecated
from ovos_utils.metrics import Stopwatch
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap
from ovos_utils.skill_installer import ServiceInstaller
from ovos_utils.sound import play_audio

from ovos_audio.audio import AudioService
from ovos_audio.playback import PlaybackThread
from ovos_audio.transformers import DialogTransformersService
from ovos_audio.tts import TTSFactory
from ovos_audio.utils import report_timing, require_default_session


def on_ready():
    LOG.info('TTS service is ready.')


def on_alive():
    LOG.info('TTS service is alive.')


def on_started():
    LOG.info('TTS service started.')


def on_error(e='Unknown'):
    LOG.error(f'TTS service failed to launch ({e}).')


def on_stopping():
    LOG.info('TTS service is shutting down...')


def tts_config_hash(tts_config: dict, module: str) -> int:
    """Hash what decides whether a TTS engine has to be rebuilt.

    The plugin name takes part in the hash, not only its settings block. Two
    plugins that carry no settings of their own both hash to an empty block, so
    without the name a swap between them looks like no change and the old engine
    keeps speaking until the service restarts.
    """
    return hash(json.dumps({"module": module,
                            "config": tts_config.get(module, {})},
                           sort_keys=True))


class PlaybackService(Thread):
    def __init__(self, ready_hook=on_ready, error_hook=on_error,
                 stopping_hook=on_stopping, alive_hook=on_alive,
                 started_hook=on_started, watchdog=lambda: None,
                 bus=None, disable_ocp=None, validate_source=True,
                 tts: Optional[TTS] = None,
                 disable_fallback: bool = False):
        super(PlaybackService, self).__init__()

        LOG.info("Starting Audio Service")
        callbacks = StatusCallbackMap(on_ready=ready_hook, on_error=error_hook,
                                      on_stopping=stopping_hook,
                                      on_alive=alive_hook,
                                      on_started=started_hook)
        self.playback_lock = Lock()
        self.status = ProcessStatus('audio', callback_map=callbacks)
        self.status.set_started()

        self.config = Configuration()
        self.tts: Optional[TTS] = tts
        self._tts_hash = None
        self.lock = Lock()
        self.disable_reload = tts is not None
        self.disable_fallback = disable_fallback
        self.fallback_tts: Optional[TTS] = None
        self._fallback_tts_hash = None
        self._last_stop_signal = 0
        self.validate_source = validate_source

        if not bus:
            bus = MessageBusClient()
            bus.run_in_thread()
        self.bus = bus
        self.status.bind(self.bus)
        self.init_messagebus()
        # Install/uninstall plugins into THIS service's environment when asked
        # over the bus (ovos.pip.install / ovos.pip.install.ovos-audio). Gated
        # by the 'skills.installer.allow_pip' config, off by default.
        self.installer = ServiceInstaller(self.bus, service_name="ovos_audio")
        self.dialog_transform = DialogTransformersService(self.bus)
        if TTS.queue is None:
            TTS.queue = Queue()
        self.playback_thread = PlaybackThread(TTS.queue, self.bus)
        self.playback_thread.start()

        try:
            self._maybe_reload_tts()
            if not self.disable_reload:
                Configuration.set_config_watcher(self._maybe_reload_tts)
        except Exception as e:
            LOG.exception(e)
            self.status.set_error(e)

        self.audio = None
        self.audio_enabled = self.config.get("enable_old_audioservice", True)  # TODO default to False soon
        if disable_ocp is None:
            disable_ocp = self.config.get("disable_ocp", False)  # TODO default to True soon
        self.disable_ocp = disable_ocp
        LOG.debug(f"legacy audio service enabled: {self.audio_enabled}")
        if self.audio_enabled:
            try:
                self.audio = AudioService(self.bus, disable_ocp=disable_ocp,
                                          validate_source=validate_source)
            except Exception as e:
                LOG.exception(e)

    @staticmethod
    def get_tts_lang_options(lang, blacklist=None):
        """ returns a list of options to be consumed by an external UI
        each dict contains metadata about the plugins

        eg:
          [{"engine": "ovos-tts-plugin-mimic3",
          "offline": True,
          "lang": "en-us",
          "gender": "male",
          "voice": "ap",
          "display_name": "Alan Pope",
          "plugin_name": 'OVOS TTS Plugin Mimic3'}]
        """
        blacklist = blacklist or []
        opts = []
        cfgs = get_tts_lang_configs(lang=lang, include_dialects=True)
        for engine, configs in cfgs.items():
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            for voice in configs:
                voice["plugin_name"] = plugin_display_name
                voice["engine"] = engine
                voice["lang"] = voice.get("lang") or lang
                opts.append(voice)
        return opts

    @staticmethod
    def get_g2p_lang_options(lang, blacklist=None):
        """ returns a list of options to be consumed by an external UI
        each dict contains metadata about the plugins

        eg:
          [{"engine": "ovos-g2p-plugin-mimic",
          "offline": True,
          "lang": "en-us",
          "native_alphabet": "ARPA",
          "display_name": "Mimic G2P",
          "plugin_name": 'OVOS G2P Plugin Mimic'}]
        """
        blacklist = blacklist or []
        opts = []
        cfgs = get_g2p_lang_configs(lang=lang, include_dialects=True)
        for engine, configs in cfgs.items():
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            for voice in configs:
                voice["plugin_name"] = plugin_display_name
                voice["engine"] = engine
                voice["lang"] = voice.get("lang") or lang
                opts.append(voice)
        return opts

    @staticmethod
    @deprecated("audio service moved to ovos-media", "0.1.0")
    def get_audio_options(blacklist=None):
        """ returns a list of options to be consumed by an external UI
        each dict contains metadata about the plugins

        eg:
          [{"type": "ovos_common_play",
          "active": True,
          "plugin_name": 'Ovos Common Play'}]
        """
        warnings.warn(
            "'get_audio_options' is deprecated and will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        opts = []
        return opts

    def handle_opm_tts_query(self, message):
        """ Responds to opm.tts.query with data about installed plugins

        Response message.data will contain:
        "langs" - list of supported languages
        "plugins" - {lang: [list_of_plugins]}
        "configs" - {plugin_name: {lang: [list_of_valid_configs]}}
        "options" - {lang: [list_of_valid_ui_metadata]}
        """
        plugs = get_tts_supported_langs()
        configs = {}
        opts = {}
        for lang, m in plugs.items():
            for p in m:
                configs[p] = get_tts_module_configs(p)
            opts[lang] = self.get_tts_lang_options(lang)

        data = {
            "plugins": plugs,
            "langs": list(plugs.keys()),
            "configs": configs,
            "options": opts
        }
        self.bus.emit(message.response(data))

    def handle_opm_g2p_query(self, message):
        """ Responds to opm.g2p.query with data about installed plugins

        Response message.data will contain:
        "langs" - list of supported languages
        "plugins" - {lang: [list_of_plugins]}
        "configs" - {plugin_name: {lang: [list_of_valid_configs]}}
        "options" - {lang: [list_of_valid_ui_metadata]}
        """
        plugs = get_g2p_supported_langs()
        configs = {}
        opts = {}
        for lang, m in plugs.items():
            for p in m:
                configs[p] = get_g2p_module_configs(p)
            opts[lang] = self.get_g2p_lang_options(lang)

        data = {
            "plugins": plugs,
            "langs": list(plugs.keys()),
            "configs": configs,
            "options": opts
        }
        self.bus.emit(message.response(data))

    @deprecated("audio service moved to ovos-media", "0.1.0")
    def handle_opm_audio_query(self, message):
        """ Responds to opm.audio.query with data about installed plugins

        Response message.data will contain:
        "plugins" - [list_of_plugins]
        "configs" - {backend_name: backend_cfg}}
        "options" - {lang: [list_of_valid_ui_metadata]}
        """
        warnings.warn(
            "'handle_opm_audio_query' is deprecated and will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        data = {
            "plugins": [],
            "configs": {},
            "options": {}
        }
        self.bus.emit(message.response(data))

    def run(self):
        self.status.set_alive()
        if self.audio_enabled:
            LOG.info("Legacy AudioService enabled")
            if not self.disable_ocp:
                LOG.warning("OCP has moved to ovos-media, if you already migrated to ovos-media "
                            'set "disable_ocp": true in mycroft.conf')
            if self.audio.wait_for_load():
                if len(self.audio.service) == 0:
                    LOG.warning('No audio backends loaded! '
                                'Audio playback is not available')
                    LOG.info("Running audio service in TTS only mode")
        # If at least TTS exists, report ready
        if self.tts:
            self.status.set_ready()
        else:
            self.status.set_error('No TTS loaded')

    def handle_b64_audio(self, message):
        """synthesizes speech, but instead of queuing for playback
        returns it b64 encoded in the bus
        allows 3rd party integrations to use OVOS as a TTS service

        OVOS-AUDIO-1 §3.4: this is the remote-client rendering mode. It is
        reached via the spec topic 'ovos.utterance.speak.b64'
        (SpecMessage.SPEAK_B64) and the legacy 'speak:b64_audio'. The
        synthesised audio is emitted as 'ovos.audio.speech'
        (SpecMessage.AUDIO_SPEECH, §4.3) instead of being enqueued for local
        playback. When the originating Message carries listen=True, the
        service emits 'ovos.mic.listen' after 'ovos.audio.speech'.
        """
        sess = SessionManager.get(message)
        stopwatch = Stopwatch()
        stopwatch.start()
        utterance = message.data['utterance']
        listen = message.data.get("listen", False)

        ctxt = self.tts._get_ctxt({"message": message})
        wav, _ = self.tts.synth(utterance, ctxt)
        # cast to str() to get a path, as it is a AudioFile object from tts cache
        with open(str(wav), "rb") as f:
            audio = f.read()

        b64_audio = base64.b64encode(audio).decode("utf-8")
        payload = {"audio": b64_audio,
                   "listen": listen,
                   'tts_id': self.tts.plugin_id,
                   "utterance": utterance}
        # OVOS-AUDIO-1 §3.4/§4.3: emit the spec topic only. The bus client's
        # emit_legacy flag mirrors it onto the legacy speak:b64_audio.response
        # (ovos-spec-tools MIGRATION_MAP), so hand-emitting the legacy reply
        # here too would put it on the wire twice.
        self.bus.emit(message.forward(SpecMessage.AUDIO_SPEECH, payload))
        # OVOS-AUDIO-1 §3.4: re-open the remote client's input channel
        if listen:
            self.bus.emit(message.forward(SpecMessage.MIC_LISTEN))

        stopwatch.stop()
        report_timing(sess.session_id, stopwatch,
                      {'utterance': utterance,
                       'tts': self.tts.plugin_id})

    @require_default_session()
    def handle_speak(self, message):
        """Handle "speak" message

        Parse sentences and invoke text to speech service.
        """
        # NOTE: lock is needed to avoid race conditions,
        # dont allow queuing until TTS synth finishes
        with self.playback_lock:
            # if the message is targeted and audio is not the target don't
            # don't synthesise speech
            message.context = message.context or {}

            # Get conversation ID
            if 'ident' in message.context:
                LOG.warning("'ident' context metadata is deprecated, use session_id instead")

            sess = SessionManager.get(message)

            stopwatch = Stopwatch()
            stopwatch.start()

            utterance = message.data.get('utterance')

            # allow dialog transformers to rewrite speech
            skill_id = message.data.get("meta", {}).get("skill") or message.context.get("skill_id")
            if skill_id and skill_id not in self.dialog_transform.blacklisted_skills:
                utt2, message.context = self.dialog_transform.transform(dialog=utterance,
                                                                        context=message.context,
                                                                        sess=sess)
                if utterance != utt2:
                    LOG.debug(f"original dialog: {utterance}")
                    LOG.info(f"dialog transformed to: {utt2}")
                    utterance = utt2

            listen = message.data.get('expect_response', False)
            self.execute_tts(utterance, sess.session_id, listen, message)

            stopwatch.stop()
            plugin_id = self.tts.plugin_id if self.tts else ""
            report_timing(sess.session_id, stopwatch,
                          {'utterance': utterance,
                           'tts': plugin_id})

    def _maybe_reload_tts(self):
        """
        Load TTS modules if not yet loaded or if configuration has changed.
        Optionally pre-loads fallback TTS if configured
        """
        if self.disable_reload:
            LOG.debug("skipping TTS reload")
            return

        config = Configuration().get("tts", {})
        tts_m = config.get("module", "")
        ftts_m = config.get("fallback_module", "")
        _tts_hash = tts_config_hash(config, tts_m)
        _ftts_hash = tts_config_hash(config, ftts_m)

        # update TTS object if configuration has changed
        if not self._tts_hash or self._tts_hash != _tts_hash:
            with self.lock:
                if self.tts:
                    self.tts.shutdown()
                # Create new tts instance
                LOG.info("(re)loading TTS engine")
                self.tts = TTSFactory.create(config)
                self.tts.init(self.bus, self.playback_thread)
                self._tts_hash = _tts_hash

        if self.disable_fallback:
            LOG.debug("skipping fallback TTS reload")
            return

        # if fallback TTS is the same as main TTS dont load it
        if config.get("module", "") == config.get("fallback_module", "") or not config.get("fallback_module", ""):
            LOG.debug("Skipping fallback TTS init, fallback is empty or same as main TTS")
            return

        if not config.get('preload_fallback', True):
            LOG.debug("Skipping fallback TTS init")
            return

        if not self._fallback_tts_hash or \
                self._fallback_tts_hash != _ftts_hash:
            with self.lock:
                if self.fallback_tts:
                    self.fallback_tts.shutdown()
                    # _get_tts_fallback only builds an engine when there is
                    # none, and shutdown does not clear the attribute, so the
                    # old one has to go or the reload hands back the engine it
                    # just shut down.
                    self.fallback_tts = None
                # Create new tts instance
                LOG.info("(re)loading fallback TTS engine")
                self._get_tts_fallback()
                self._fallback_tts_hash = _ftts_hash

    def execute_tts(self, utterance, ident, listen=False, message: Message = None):
        """Mute mic and start speaking the utterance using selected tts backend.

        Args:
            utterance:  The sentence to be spoken
            ident:      Ident tying the utterance to the source query
            listen:     True if a user response is expected
        """
        LOG.info("Speak: " + utterance)
        with self.lock:
            try:
                self.tts.execute(utterance, ident, listen,
                                 message=message)  # accepts random kwargs
            except Exception as e:
                LOG.exception(f"TTS synth failed! {e}")
                if self._tts_hash != self._fallback_tts_hash:
                    self.execute_fallback_tts(utterance, ident, listen, message)

    def _get_tts_fallback(self) -> Optional[TTS]:
        """Lazily initializes the fallback TTS if needed."""
        if not self.fallback_tts:
            config = Configuration()
            engine = config.get('tts', {}).get("fallback_module", "")
            if not engine:
                return
            cfg = {"tts": {"module": engine,
                           engine: config.get('tts', {}).get(engine, {})}}
            self.fallback_tts = TTSFactory.create(cfg)
            self.fallback_tts.validator.validate()
            self.fallback_tts.init(self.bus, self.playback_thread)

        return self.fallback_tts

    def execute_fallback_tts(self, utterance, ident, listen, message: Message = None):
        """Speak utterance using fallback TTS if connection is lost.

        Args:
            utterance (str): sentence to speak
            ident (str): interaction id for metrics
            listen (bool): True if interaction should end with mycroft listening
        """
        try:
            tts = self._get_tts_fallback()
            if tts is None:
                LOG.error("No fallback TTS available and main TTS failed!")
                return
            LOG.debug("TTS fallback, utterance : " + str(utterance))
            tts.execute(utterance, ident, listen,
                        message=message)  # accepts random kwargs
            return
        except Exception as e:
            LOG.error(e)
            LOG.exception(f"TTS FAILURE! utterance : {utterance}")

    @property
    def is_speaking(self) -> bool:
        return self.tts.playback is not None and \
            self.tts.playback._now_playing is not None

    def handle_speak_status(self, message: Message):
        """OVOS-AUDIO-1 §5.3: answer a speaking-status query.

        Reachable via the spec query topic 'ovos.audio.is_speaking'
        (SpecMessage.AUDIO_IS_SPEAKING) and the legacy
        'mycroft.audio.speak.status'. The reply carries {"speaking": bool}
        on the spec topic; the legacy topic name is kept for back-compat.
        """
        # The spec query topic and the spec reply topic share the name
        # 'ovos.audio.is_speaking' (§5.3). Since this handler also subscribes
        # to that topic, ignore messages that already carry the answer so the
        # service never replies to its own reply.
        if "speaking" in message.data:
            return
        speaking = self.is_speaking
        # spec reply (OVOS-AUDIO-1 §5.3)
        self.bus.emit(message.reply(SpecMessage.AUDIO_IS_SPEAKING,
                                    {"speaking": speaking}))
        # legacy reply name for back-compat
        self.bus.emit(message.reply("mycroft.audio.is_speaking",
                                    {"speaking": speaking}))

    def handle_stop(self, message: Message):
        """Handle stop message.

        Shutdown any speech.
        """
        # check PlaybackThread
        if self.is_speaking:
            self._last_stop_signal = time.time()
            self.tts.playback.clear()  # Clear here to get instant stop
            self.bus.emit(message.forward("mycroft.stop.handled", {"by": "TTS"}))

    @staticmethod
    def _resolve_sound_uri(uri: str) -> Optional[str]:
        """ helper to resolve sound files full path"""
        if uri is None:
            return None
        if uri.startswith("snd/") or uri.startswith("snd\\"):
            local_uri = os.path.join(os.path.dirname(__file__), "res", uri)
            if os.path.isfile(local_uri):
                return local_uri
        audio_file = resolve_resource_file(uri)
        if audio_file is None or not exists(audio_file):
            raise FileNotFoundError(f"could not resolve sound uri: {uri}")
        return audio_file

    @staticmethod
    def _path_from_hexdata(hex_audio, audio_ext=None) -> str:
        """ hex_audio contains hex string encoded bytes
         audio_ext if not provided assumed to be wav

        recommended encoding via binascii.hexlify(byte_data).decode('utf-8')
        """
        fname = md5(hex_audio.encode("utf-8")).hexdigest()
        bindata = binascii.unhexlify(hex_audio)
        if not audio_ext:
            LOG.warning("audio extension not sent, assuming wav")
            audio_ext = "wav"

        audio_file = f"{gettempdir()}/{fname}.{audio_ext}"
        with open(audio_file, "wb") as f:
            f.write(bindata)
        return audio_file

    @require_default_session()
    def handle_queue_audio(self, message):
        """ Queue a sound file to play in speech thread
         ensures it doesnt play over TTS """
        with self.playback_lock:
            viseme = message.data.get("viseme")
            audio_file = message.data.get("uri") or \
                         message.data.get("filename")  # backwards compat
            hex_audio = message.data.get("binary_data")
            audio_ext = message.data.get("audio_ext")
            if hex_audio:
                audio_file = self._path_from_hexdata(hex_audio, audio_ext)

            if not audio_file:
                LOG.warning(f"{SpecMessage.AUDIO_QUEUE} message.data needs to provide "
                            f"'uri' or 'binary_data': {message.data}")
                return
            try:
                audio_file = self._resolve_sound_uri(audio_file)
            except FileNotFoundError as e:
                LOG.warning(f"{SpecMessage.AUDIO_QUEUE} could not resolve sound uri: {e}")
                return

            listen = message.data.get("listen", False)

            # expected queue contents: (data, visemes, listen, tts_id, message)
            # a sound does not have a tts_id, assign that to "sounds"
            TTS.queue.put((str(audio_file), viseme, listen, "sounds", message))

    @require_default_session()
    def handle_instant_play(self, message):
        """ play a sound file immediately (may play over TTS) """
        audio_file = message.data.get("uri")
        hex_audio = message.data.get("binary_data")
        audio_ext = message.data.get("audio_ext")
        if hex_audio:
            audio_file = self._path_from_hexdata(hex_audio, audio_ext)
        if not audio_file:
            LOG.warning(f"{SpecMessage.AUDIO_PLAY_SOUND} message.data needs to provide "
                        f"'uri' or 'binary_data': {message.data}")
            return

        try:
            audio_file = self._resolve_sound_uri(audio_file)
        except FileNotFoundError as e:
            LOG.warning(f"{SpecMessage.AUDIO_PLAY_SOUND} could not resolve sound uri: {e}")
            return

        # volume handling and audio service ducking
        ensure_volume = message.data.get("force_unmute", False)
        duck_pulse_handled = bool(self.tts and self.tts.config.get("pulse_duck"))
        if ensure_volume:
            volume_poll: Message = self.bus.wait_for_response(Message("mycroft.volume.get"), timeout=0.3)
            volume = volume_poll.data.get("percent", 0) if volume_poll else 80
            muted = volume_poll.data.get("muted", False) if volume_poll else False
            volume_changed = False
            if volume == 0:
                self.bus.emit(Message("mycroft.volume.set", {"percent": 80,
                                                             "play_sound": False}))
                volume_changed = True
            elif muted:
                self.bus.emit(Message("mycroft.volume.unmute"))

        play_audio(audio_file).wait()

        if ensure_volume:
            if volume_changed:
                self.bus.emit(Message("mycroft.volume.set", {"percent": volume,
                                                             "play_sound": False}))
            if muted:
                self.bus.emit(Message("mycroft.volume.mute"))

        # OVOS-AUDIO-1 §4.2: reply on the incoming topic's own '.response'
        # suffix. The generic '<topic>.response' derivation is NOT one of the
        # ovos-spec-tools MIGRATION_MAP pairs (only base request topics are
        # mapped, not their derived replies), so the namespace bridge does not
        # mirror it: a caller that reached this handler via the legacy
        # 'mycroft.audio.play_sound' request would otherwise never see a
        # response. Emit both spellings explicitly, matching
        # handle_speak_status's hand-mirrored reply.
        self.bus.emit(message.response({}))
        self.bus.emit(message.reply("mycroft.audio.play_sound.response", {}))

    def handle_get_languages_tts(self, message):
        """
        Handle a request for supported TTS languages
        :param message: ovos.languages.tts request
        """
        tts_langs = self.tts.available_languages or \
                    [self.config.get('lang') or 'en-us']
        LOG.debug(f"Got tts_langs: {tts_langs}")
        self.bus.emit(message.response({'langs': list(tts_langs)}))

    def shutdown(self):
        """Shutdown the audio service cleanly.

        Stop any playing audio and make sure threads are joined correctly.
        """
        self.status.set_stopping()
        if getattr(self, "installer", None):
            self.installer.shutdown()
        if self.playback_thread:
            self.playback_thread.shutdown()
            self.playback_thread.join()
        if self.audio:
            self.audio.shutdown()

    def init_messagebus(self):
        """
        Start speech related handlers.
        """
        Configuration.set_config_update_handlers(self.bus)
        # OVOS-STOP-1 §5.3: a non-skill component with user-visible activity MUST
        # cease on the universal stop broadcast. The legacy 'mycroft.stop' topic
        # is mirrored onto 'ovos.stop' by the bus-client compat boundary
        # (ovos-bus-client's namespace bridge, client.py), so a single
        # spec-namespace subscription suffices here.
        self.bus.on('ovos.stop', self.handle_stop)
        # OVOS-AUDIO-1 §6: 'ovos.audio.stop' is the spec stop-audio topic. The
        # legacy 'mycroft.audio.speech.stop' is mirrored onto it by the
        # bus-client compat boundary; no separate legacy subscription needed.
        self.bus.on(SpecMessage.AUDIO_STOP, self.handle_stop)
        # OVOS-AUDIO-1 §5.3: 'ovos.audio.is_speaking' is the spec speaking-status
        # query topic. The legacy 'mycroft.audio.speak.status' is mirrored onto
        # it by the bus-client compat boundary; no separate legacy subscription
        # needed.
        self.bus.on(SpecMessage.AUDIO_IS_SPEAKING, self.handle_speak_status)
        # OVOS-AUDIO-1 §4.1: 'ovos.audio.queue' is the spec queued-sound topic.
        # The legacy 'mycroft.audio.queue' is mirrored onto it by the bus-client
        # compat boundary; no separate legacy subscription needed.
        self.bus.on(SpecMessage.AUDIO_QUEUE, self.handle_queue_audio)
        # OVOS-AUDIO-1 §4.2: 'ovos.audio.play_sound' is the spec instant-sound
        # topic. The legacy 'mycroft.audio.play_sound' is mirrored onto it by
        # the bus-client compat boundary; no separate legacy subscription
        # needed.
        self.bus.on(SpecMessage.AUDIO_PLAY_SOUND, self.handle_instant_play)
        # OVOS-PIPELINE-1 §9.6: consume the spec-named natural-language response
        # topic. The bus client's modernize flag routes legacy 'speak' emitters
        # to this listener, so a single spec-namespace subscription suffices.
        self.bus.on(SpecMessage.SPEAK, self.handle_speak)
        # OVOS-AUDIO-1 §3.4: 'ovos.utterance.speak.b64' is the spec remote-client
        # rendering topic. The legacy 'speak:b64_audio' is mirrored onto it by
        # the bus-client compat boundary; no separate legacy subscription
        # needed.
        self.bus.on(SpecMessage.SPEAK_B64, self.handle_b64_audio)
        self.bus.on('ovos.languages.tts', self.handle_get_languages_tts)
        self.bus.on("opm.tts.query", self.handle_opm_tts_query)
        self.bus.on("opm.audio.query", self.handle_opm_audio_query)
        self.bus.on("opm.g2p.query", self.handle_opm_g2p_query)
