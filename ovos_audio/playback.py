import random
from ovos_audio.transformers import TTSTransformersService
from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.tts import TTS
from ovos_utils.log import LOG, log_deprecation
from ovos_utils.sound import play_audio
from queue import Empty
from threading import Thread, Event
from time import time


class PlaybackThread(Thread):
    """Thread class for playing back tts audio and sending
    viseme data to enclosure.
    """

    def __init__(self, queue=TTS.queue, bus=None):
        super(PlaybackThread, self).__init__(daemon=True)
        self.queue = queue or TTS.queue
        self._terminated = False
        self._processing_queue = False
        self._do_playback = Event()
        self.enclosure = None
        self.p = None
        self._tts = []
        self.bus = bus or None
        self._now_playing = None
        self.active_tts = None
        self._started = Event()
        self.tts_transform = TTSTransformersService(self.bus)

    @property
    def is_running(self):
        return self._started.is_set() and not self._terminated

    def activate_tts(self, tts_id):
        self.active_tts = tts_id
        tts = self.get_attached_tts()
        if tts:
            tts.begin_audio()

    def deactivate_tts(self):
        if self.active_tts:
            tts = self.get_attached_tts()
            if tts:
                tts.end_audio()
        self.active_tts = None

    def init(self, tts):
        """DEPRECATED! Init the TTS Playback thread."""
        self.attach_tts(tts)
        self.set_bus(tts.bus)

    def set_bus(self, bus):
        """Provide bus instance to the TTS Playback thread.
        Args:
            bus (MycroftBusClient): bus client
        """
        self.bus = bus
        self.tts_transform.set_bus(bus)

    @property
    def tts(self):
        tts = self.get_attached_tts()
        if not tts and self._tts:
            return self._tts[0]
        return tts

    @tts.setter
    def tts(self, val):
        self.attach_tts(val)

    @property
    def attached_tts(self):
        return self._tts

    def attach_tts(self, tts):
        """Add TTS to be cache checked."""
        if tts not in self.attached_tts:
            self.attached_tts.append(tts)

    def detach_tts(self, tts):
        """Remove TTS from cache check."""
        if tts in self.attached_tts:
            self.attached_tts.remove(tts)

    def get_attached_tts(self, tts_id=None):
        tts_id = tts_id or self.active_tts
        if not tts_id:
            return
        for tts in self.attached_tts:
            if hasattr(tts, "tts_id"):
                # opm plugin
                if tts.tts_id == tts_id:
                    return tts

        for tts in self.attached_tts:
            if not hasattr(tts, "tts_id"):
                # non-opm plugin
                if tts.tts_name == tts_id:
                    return tts

    def clear_queue(self):
        """Remove all pending playbacks."""
        while not self.queue.empty():
            self.queue.get()
        try:
            self.p.terminate()
        except Exception:
            pass

    def begin_audio(self, message=None):
        """Perform beginning of speech actions."""
        if self.bus:
            if not self.tts.config.get("pulse_duck", False):
                self.bus.emit(Message("ovos.common_play.duck"))
            message = message or Message("speak")
            self.bus.emit(message.forward("recognizer_loop:audio_output_start"))
        else:
            LOG.warning("Speech started before bus was attached.")

    def end_audio(self, listen, message=None):
        """Perform end of speech output actions.
        Will inform the system that speech has ended and trigger the TTS's
        cache checks. Listening will be triggered if requested.
        Args:
            listen (bool): True if listening event should be emitted
        """
        if self.bus:
            if not self.tts.config.get("pulse_duck", False):
                self.bus.emit(Message("ovos.common_play.unduck"))
            # Send end of speech signals to the system
            message = message or Message("speak")
            self.bus.emit(message.forward("recognizer_loop:audio_output_end"))
            if listen:
                self.bus.emit(message.forward('mycroft.mic.listen'))
        else:
            LOG.warning("Speech started before bus was attached.")

    def on_start(self, message=None):
        self.blink(0.5)
        if not self._processing_queue:
            self._processing_queue = True
            self.begin_audio(message)

    def on_end(self, listen=False, message=None):
        if self._processing_queue:
            self.end_audio(listen, message)
            self._processing_queue = False
        # Clear cache for all attached tts objects
        # This is basically the only safe time
        for tts in self.attached_tts:
            tts.cache.curate()
        self.blink(0.2)

    def _play(self):
        try:
            data, visemes, listen, tts_id, message = self._now_playing
            self.activate_tts(tts_id)
            self.on_start(message)

            data, message.context = self.tts_transform.transform(data, message.context)

            self.p = play_audio(data)
            if visemes:
                self.show_visemes(visemes)
            if self.p:
                self.p.communicate()
                self.p.wait()
            self.deactivate_tts()
            if self.queue.empty():
                self.on_end(listen, message)
        except Empty:
            pass
        except Exception as e:
            LOG.exception(e)
            if self._processing_queue:
                self.on_end()
        self._now_playing = None

    def run(self, cb=None):
        """Thread main loop. Get audio and extra data from queue and play.

        The queue messages is a tuple containing
        snd_type: 'mp3' or 'wav' telling the loop what format the data is in
        data: path to temporary audio data
        videmes: list of visemes to display while playing
        listen: if listening should be triggered at the end of the sentence.

        Playback of audio is started and the visemes are sent over the bus
        the loop then wait for the playback process to finish before starting
        checking the next position in queue.

        If the queue is empty the tts.end_audio() is called possibly triggering
        listening.
        """
        LOG.info("PlaybackThread started")
        self._do_playback.set()
        self._started.set()
        while not self._terminated:
            self._do_playback.wait()
            try:
                # HACK: we do these check to account for direct usages of TTS.queue singletons
                speech_data = self.queue.get(timeout=2)
                if len(speech_data) == 5 and isinstance(speech_data[-1], Message):
                    data, visemes, listen, tts_id, message = speech_data
                else:
                    log_deprecation(
                        "Direct modification of TTS.queue is not recommended!\n"
                        "expected=(data, visemes, listen, tts_id, message)",
                        "0.1.0")
                    if len(speech_data) == 6:
                        # old ovos backwards compat
                        _, data, visemes, ident, listen, tts_id = speech_data
                    elif len(speech_data) == 5:
                        # mycroft style
                        tts_id = None
                        _, data, visemes, ident, listen = speech_data
                    else:
                        # old mycroft style  TODO can this be deprecated? its very very old
                        listen = False
                        tts_id = None
                        _, data, visemes, ident = speech_data

                    message = Message("speak", context={"session": {"session_id": ident}})

                self._now_playing = (data, visemes, listen, tts_id, message)
                self._play()
            except Empty:
                pass
            except Exception as e:
                LOG.error(e)

    def show_visemes(self, pairs):
        """Send viseme data to enclosure

        Args:
            pairs (list): Visime and timing pair

        Returns:
            bool: True if button has been pressed.
        """
        if self.enclosure:
            self.enclosure.mouth_viseme(time(), pairs)

    def pause(self):
        """pause thread"""
        self._do_playback.clear()
        if self.p:
            self.p.terminate()

    def resume(self):
        """resume thread"""
        if self._now_playing:
            self._play()
        self._do_playback.set()

    def clear(self):
        """Clear all pending actions for the TTS playback thread."""
        self.clear_queue()

    def blink(self, rate=1.0):
        """Blink mycroft's eyes"""
        if self.enclosure and random.random() < rate:
            self.enclosure.eyes_blink("b")

    def stop(self):
        """Stop thread"""
        self._now_playing = None
        self._terminated = True
        self.clear_queue()

    def shutdown(self):
        self.stop()
        for tts in self.attached_tts:
            self.detach_tts(tts)

    def __del__(self):
        self.shutdown()
