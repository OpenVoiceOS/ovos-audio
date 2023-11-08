import binascii
import os
import os.path
import time
from hashlib import md5
from os.path import exists
from queue import Queue
from tempfile import gettempdir
from threading import Thread, Lock

from ovos_bus_client import Message, MessageBusClient
from ovos_bus_client.session import SessionManager
from ovos_config.config import Configuration
from ovos_plugin_manager.audio import get_audio_service_configs
from ovos_plugin_manager.g2p import get_g2p_lang_configs, get_g2p_supported_langs, get_g2p_module_configs
from ovos_plugin_manager.tts import TTS
from ovos_plugin_manager.tts import get_tts_supported_langs, get_tts_lang_configs, get_tts_module_configs
from ovos_utils.file_utils import resolve_resource_file
from ovos_utils.log import LOG
from ovos_utils.metrics import Stopwatch
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap
from ovos_utils.sound import play_audio

from ovos_audio.audio import AudioService
from ovos_audio.playback import PlaybackThread
from ovos_audio.transformers import DialogTransformersService
from ovos_audio.tts import TTSFactory
from ovos_audio.utils import report_timing, validate_message_context


def on_ready():
    LOG.info('Audio service is ready.')


def on_alive():
    LOG.info('Audio service is alive.')


def on_started():
    LOG.info('Audio service started.')


def on_error(e='Unknown'):
    LOG.error(f'Audio service failed to launch ({e}).')


def on_stopping():
    LOG.info('Audio service is shutting down...')


class PlaybackService(Thread):
    def __init__(self, ready_hook=on_ready, error_hook=on_error,
                 stopping_hook=on_stopping, alive_hook=on_alive,
                 started_hook=on_started, watchdog=lambda: None,
                 bus=None, disable_ocp=False, validate_source=True):
        super(PlaybackService, self).__init__()

        LOG.info("Starting Audio Service")
        callbacks = StatusCallbackMap(on_ready=ready_hook, on_error=error_hook,
                                      on_stopping=stopping_hook,
                                      on_alive=alive_hook,
                                      on_started=started_hook)
        self.status = ProcessStatus('audio', callback_map=callbacks)
        self.status.set_started()

        self.config = Configuration()
        self.native_sources = self.config["Audio"].get("native_sources",
                                                       ["debug_cli", "audio"]) or []
        self.tts = None
        self._tts_hash = None
        self.lock = Lock()
        self.fallback_tts = None
        self._fallback_tts_hash = None
        self._last_stop_signal = 0
        self.validate_source = validate_source

        if not bus:
            bus = MessageBusClient()
            bus.run_in_thread()
        self.bus = bus
        self.status.bind(self.bus)
        self.init_messagebus()
        self.dialog_transform = DialogTransformersService(self.bus)
        if TTS.queue is None:
            TTS.queue = Queue()
        self.playback_thread = PlaybackThread(TTS.queue, self.bus)
        self.playback_thread.start()

        try:
            self._maybe_reload_tts()
            Configuration.set_config_watcher(self._maybe_reload_tts)
        except Exception as e:
            LOG.exception(e)
            self.status.set_error(e)

        try:
            self.audio = AudioService(self.bus, disable_ocp=disable_ocp, validate_source=validate_source)
        except Exception as e:
            LOG.exception(e)
            self.status.set_error(e)

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
    def get_audio_options(blacklist=None):
        """ returns a list of options to be consumed by an external UI
        each dict contains metadata about the plugins

        eg:
          [{"type": "ovos_common_play",
          "active": True,
          "plugin_name": 'Ovos Common Play'}]
        """
        blacklist = blacklist or []
        opts = []
        cfgs = get_audio_service_configs()
        for name, config in cfgs.items():
            engine = config["type"]
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            config["plugin_name"] = plugin_display_name
            opts.append(config)
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

    def handle_opm_audio_query(self, message):
        """ Responds to opm.audio.query with data about installed plugins

        Response message.data will contain:
        "plugins" - [list_of_plugins]
        "configs" - {backend_name: backend_cfg}}
        "options" - {lang: [list_of_valid_ui_metadata]}
        """
        cfgs = get_audio_service_configs()
        data = {
            "plugins": list(cfgs.keys()),
            "configs": cfgs,
            "options": self.get_audio_options()
        }
        self.bus.emit(message.response(data))

    def run(self):
        self.status.set_alive()
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

    def handle_speak(self, message):
        """Handle "speak" message

        Parse sentences and invoke text to speech service.
        """

        # if the message is targeted and audio is not the target don't
        # don't synthesise speech
        message.context = message.context or {}
        if self.validate_source and not validate_message_context(message, self.native_sources):
            LOG.debug("ignoring speak from non-native source, playback handled directly by client")
            return

        # Get conversation ID
        if 'ident' in message.context:
            LOG.warning("'ident' context metadata is deprecated, use session_id instead")

        sess = SessionManager.get(message)

        stopwatch = Stopwatch()
        stopwatch.start()

        utterance = message.data['utterance']

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
        report_timing(sess.session_id, stopwatch,
                      {'utterance': utterance,
                       'tts': self.tts.__class__.__name__})

    def _maybe_reload_tts(self):
        """
        Load TTS modules if not yet loaded or if configuration has changed.
        Optionally pre-loads fallback TTS if configured
        """
        config = self.config.get("tts", {})

        # update TTS object if configuration has changed
        if not self._tts_hash or self._tts_hash != config.get("module", ""):
            with self.lock:
                if self.tts:
                    self.tts.shutdown()
                # Create new tts instance
                LOG.info("(re)loading TTS engine")
                self.tts = TTSFactory.create(config)
                self.tts.init(self.bus, self.playback_thread)
                self._tts_hash = config.get("module", "")

        # if fallback TTS is the same as main TTS dont load it
        if config.get("module", "") == config.get("fallback_module", ""):
            return

        if not config.get('preload_fallback', True):
            LOG.debug("Skipping fallback TTS init")
            return

        if not self._fallback_tts_hash or \
                self._fallback_tts_hash != config.get("fallback_module", ""):
            with self.lock:
                if self.fallback_tts:
                    self.fallback_tts.shutdown()
                # Create new tts instance
                LOG.info("(re)loading fallback TTS engine")
                self._get_tts_fallback()
                self._fallback_tts_hash = config.get("fallback_module", "")

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

    def _get_tts_fallback(self):
        """Lazily initializes the fallback TTS if needed."""
        if not self.fallback_tts:
            config = Configuration()
            engine = config.get('tts', {}).get("fallback_module", "mimic")
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
            LOG.debug("TTS fallback, utterance : " + str(utterance))
            tts.execute(utterance, ident, listen,
                        message=message)  # accepts random kwargs
            return
        except Exception as e:
            LOG.error(e)
            LOG.exception(f"TTS FAILURE! utterance : {utterance}")

    @property
    def is_speaking(self):
        return self.tts.playback is not None and \
            self.tts.playback._now_playing is not None

    def handle_speak_status(self, message: Message):
        self.bus.emit(message.reply("mycroft.audio.is_speaking",
                                    {"speaking": self.is_speaking}))

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
    def _resolve_sound_uri(uri: str):
        """ helper to resolve sound files full path"""
        if uri is None:
            return None
        if uri.startswith("snd/"):
            local_uri = f"{os.path.dirname(__file__)}/res/{uri}"
            if os.path.isfile(local_uri):
                return local_uri
        audio_file = resolve_resource_file(uri)
        if audio_file is None or not exists(audio_file):
            raise FileNotFoundError(f"{audio_file} does not exist")
        return audio_file

    @staticmethod
    def _path_from_hexdata(hex_audio, audio_ext=None):
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

    def handle_queue_audio(self, message):
        """ Queue a sound file to play in speech thread
         ensures it doesnt play over TTS """
        if self.validate_source and not validate_message_context(message):
            LOG.debug("ignoring playback, message is not from a native source")
            return
        viseme = message.data.get("viseme")
        audio_file = message.data.get("uri") or \
                     message.data.get("filename")  # backwards compat
        hex_audio = message.data.get("binary_data")
        audio_ext = message.data.get("audio_ext")
        if hex_audio:
            audio_file = self._path_from_hexdata(hex_audio, audio_ext)

        if not audio_file:
            raise ValueError(f"message.data needs to provide 'uri' or 'binary_data': {message.data}")
        audio_file = self._resolve_sound_uri(audio_file)

        listen = message.data.get("listen", False)

        # expected queue contents: (data, visemes, listen, tts_id, message)
        # a sound does not have a tts_id, assign that to "sounds"
        TTS.queue.put((str(audio_file), viseme, listen, "sounds", message))

    def handle_instant_play(self, message):
        """ play a sound file immediately (may play over TTS) """
        if self.validate_source and not validate_message_context(message):
            LOG.debug("ignoring playback, message is not from a native source")
            return

        audio_file = message.data.get("uri")
        hex_audio = message.data.get("binary_data")
        audio_ext = message.data.get("audio_ext")
        if hex_audio:
            audio_file = self._path_from_hexdata(hex_audio, audio_ext)
        if not audio_file:
            raise ValueError(f"message.data needs to provide 'uri' or 'binary_data': {message.data}")
        audio_file = self._resolve_sound_uri(audio_file)

        # volume handling and audio service ducking
        ensure_volume = message.data.get("force_unmute", False)
        duck_pulse_handled = bool(self.tts and self.tts.config.get("pulse_duck"))
        if ensure_volume:
            volume_poll: Message = self.bus.wait_for_response(Message("mycroft.volume.get"))
            volume = volume_poll.data.get("percent", 0) if volume_poll else 80
            muted = volume_poll.data.get("muted", False) if volume_poll else False
            volume_changed = False
            if volume == 0:
                self.bus.emit(Message("mycroft.volume.set", {"percent": 80,
                                                             "play_sound": False}))
                volume_changed = True
            elif muted:
                self.bus.emit(Message("mycroft.volume.unmute"))
        if self.audio.current and not duck_pulse_handled:
            self.audio.current.lower_volume()

        play_audio(audio_file).wait()

        # return to previous state
        if self.audio.current and not duck_pulse_handled:
            self.audio.current.restore_volume()
        if ensure_volume:
            if volume_changed:
                self.bus.emit(Message("mycroft.volume.set", {"percent": volume,
                                                             "play_sound": False}))
            if muted:
                self.bus.emit(Message("mycroft.volume.mute"))

        self.bus.emit(message.response({}))

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
        if self.tts.playback:
            self.tts.playback.shutdown()
            self.tts.playback.join()
        self.audio.shutdown()

    def init_messagebus(self):
        """
        Start speech related handlers.
        """
        Configuration.set_config_update_handlers(self.bus)
        self.bus.on('mycroft.stop', self.handle_stop)
        self.bus.on('mycroft.audio.speech.stop', self.handle_stop)
        self.bus.on('mycroft.audio.speak.status', self.handle_speak_status)
        self.bus.on('mycroft.audio.queue', self.handle_queue_audio)
        self.bus.on('mycroft.audio.play_sound', self.handle_instant_play)
        self.bus.on('speak', self.handle_speak)
        self.bus.on('ovos.languages.tts', self.handle_get_languages_tts)
        self.bus.on("opm.tts.query", self.handle_opm_tts_query)
        self.bus.on("opm.audio.query", self.handle_opm_audio_query)
        self.bus.on("opm.g2p.query", self.handle_opm_g2p_query)
