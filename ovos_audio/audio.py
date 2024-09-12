# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time
from threading import Lock
from typing import List, Tuple, Union, Optional

from ovos_audio.utils import require_native_source
from ovos_bus_client.message import Message
from ovos_bus_client.message import dig_for_message
from ovos_config.config import Configuration
from ovos_plugin_manager.audio import find_audio_service_plugins, \
    setup_audio_service
from ovos_plugin_manager.ocp import load_stream_extractors
from ovos_plugin_manager.templates.audio import RemoteAudioBackend
from ovos_utils.log import LOG
from ovos_utils.process_utils import MonotonicEvent

try:
    from ovos_utils.ocp import MediaState
except ImportError:
    LOG.warning("Please update to ovos-utils~=0.1.")
    from enum import IntEnum


    class MediaState(IntEnum):
        # https://doc.qt.io/qt-5/qmediaplayer.html#MediaStatus-enum
        # The status of the media cannot be determined.
        UNKNOWN = 0
        # There is no current media. PlayerState == STOPPED
        NO_MEDIA = 1
        # The current media is being loaded. The player may be in any state.
        LOADING_MEDIA = 2
        # The current media has been loaded. PlayerState== STOPPED
        LOADED_MEDIA = 3
        # Playback of the current media has stalled due to
        # insufficient buffering or some other temporary interruption.
        # PlayerState != STOPPED
        STALLED_MEDIA = 4
        # The player is buffering data but has enough data buffered
        # for playback to continue for the immediate future.
        # PlayerState != STOPPED
        BUFFERING_MEDIA = 5
        # The player has fully buffered the current media. PlayerState != STOPPED
        BUFFERED_MEDIA = 6
        # Playback has reached the end of the current media. PlayerState == STOPPED
        END_OF_MEDIA = 7
        # The current media cannot be played. PlayerState == STOPPED
        INVALID_MEDIA = 8

MINUTES = 60  # Seconds in a minute


class AudioService:
    """ Audio Service class.
        Handles playback of audio and selecting proper backend for the uri
        to be played.
    """

    def __init__(self, bus, autoload=True, disable_ocp=False,
                 validate_source=True, native_sources=None):
        """
            Args:
                bus: Mycroft messagebus
        """
        self.bus = bus
        self.config = Configuration().get("Audio") or {}
        self.service_lock = Lock()

        self.default = None
        self.ocp = None
        self.service = []
        self.current = None
        self.play_start_time = 0
        self.volume_is_low = False
        self.volume_is_speaking = False
        self.disable_ocp = disable_ocp
        self.validate_source = validate_source
        self.native_sources = native_sources or self.config.get("native_sources",
                                                                ["debug_cli", "audio"])

        self._loaded = MonotonicEvent()
        if autoload:
            self.load_services()

    def find_ocp(self):
        if self.disable_ocp:
            LOG.info("classic OCP is disabled in config, OCP bus api not available!")
            # NOTE: ovos-core should detect this and use the classic audio service api automatically
            return

        try:
            from ovos_plugin_common_play import OCPAudioBackend
        except ImportError:
            LOG.debug("classic OCP not installed")
            return False
        # config from legacy location in default mycroft.conf
        ocp_config = Configuration().get("Audio", {}).get("backends", {}).get("OCP", {})
        self.ocp = OCPAudioBackend(ocp_config, bus=self.bus)
        try:
            self.ocp.player.validate_source = self.validate_source
            self.ocp.player.native_sources = self.native_sources
        except Exception as e:
            # handle older OCP plugin versions
            LOG.warning("old OCP version detected! please update 'ovos_plugin_common_play'")

    def find_default(self):
        if not self.service:
            LOG.error("No audio player plugins found!")
            return False
        # Find default backend
        default_name = self.config.get('default-backend', '')
        LOG.info('Finding default audio backend...')
        for s in self.service:
            if s.name == default_name:
                self.default = s
                LOG.info('Found ' + self.default.name)
                return True
        else:
            self.default = self.service[0]
            LOG.info(f'preferred audio player not configured, defaulting to {self.default}')

    def load_services(self):
        """Method for loading services.

        Sets up the global service, default and registers the event handlers
        for the subsystem.
        """
        found_plugins = find_audio_service_plugins()
        if 'ovos_common_play' in found_plugins:
            found_plugins.pop('ovos_common_play')

        local = []
        remote = []
        for plugin_name, plugin_module in found_plugins.items():
            LOG.info(f'Found audio service plugin: {plugin_name}')
            s = setup_audio_service(plugin_module, config=self.config, bus=self.bus)
            if not s:
                LOG.debug(f"{plugin_name} not loaded! config: {self.config}")
                continue
            if isinstance(s, RemoteAudioBackend):
                remote += s
            else:
                local += s

        # Sort services so local services are checked first
        self.service = local + remote

        # Register end of track callback
        for s in self.service:
            s.set_track_start_callback(self.track_start)

        # load OCP
        # NOTE: this will be replace by ovos-media in a future release
        # and can be disabled in config
        self.find_ocp()

        # load audio playback plugins (vlc, mpv, spotify ...)
        self.find_default()

        # Setup event handlers
        self.bus.on('mycroft.audio.service.play', self._play)
        self.bus.on('mycroft.audio.service.queue', self._queue)
        self.bus.on('mycroft.audio.service.pause', self._pause)
        self.bus.on('mycroft.audio.service.resume', self._resume)
        self.bus.on('mycroft.audio.service.stop', self._stop)
        self.bus.on('mycroft.audio.service.next', self._next)
        self.bus.on('mycroft.audio.service.prev', self._prev)
        self.bus.on('mycroft.audio.service.track_info', self._track_info)
        self.bus.on('mycroft.audio.service.list_backends', self._list_backends)
        self.bus.on('mycroft.audio.service.set_track_position', self._set_track_position)
        self.bus.on('mycroft.audio.service.get_track_position', self._get_track_position)
        self.bus.on('mycroft.audio.service.get_track_length', self._get_track_length)
        self.bus.on('mycroft.audio.service.seek_forward', self._seek_forward)
        self.bus.on('mycroft.audio.service.seek_backward', self._seek_backward)

        # audio ducking events
        self.bus.on('recognizer_loop:audio_output_start', self._lower_volume_on_speak)
        self.bus.on('recognizer_loop:audio_output_end', self._restore_volume_on_speak)
        self.bus.on('recognizer_loop:record_begin', self._lower_volume_on_record)
        self.bus.on('recognizer_loop:record_end', self._restore_volume_after_record)
        self.bus.on('ovos.utterance.handled', self._restore_volume_on_handled)

        self._loaded.set()  # Report services loaded

        return self.service

    def wait_for_load(self, timeout=3 * MINUTES):
        """Wait for services to be loaded.

        Args:
            timeout (float): Seconds to wait (default 3 minutes)
        Returns:
            (bool) True if loading completed within timeout, else False.
        """
        return self._loaded.wait(timeout)

    def track_start(self, track):
        """Callback method called from the services to indicate start of
        playback of a track or end of playlist.
        """
        m = dig_for_message() or Message("")
        if track:
            # Inform about the track about to start.
            LOG.debug('New track coming up!')
            self.bus.emit(m.forward('mycroft.audio.playing_track',
                                    data={'track': track}))
            self.current.ocp_start()
        else:
            # If no track is about to start last track of the queue has been
            # played.
            LOG.debug(f'End of track! {self.current} finished playback')
            self.bus.emit(m.forward('mycroft.audio.queue_end'))
            self.current.ocp_stop()

    @require_native_source()
    def _pause(self, message=None):
        """
            Handler for mycroft.audio.service.pause. Pauses the current audio
            service.

            Args:
                message: message bus message, not used but required
        """
        if self.current:
            self.current.pause()
            self.current.ocp_pause()

    @require_native_source()
    def _resume(self, message=None):
        """
            Handler for mycroft.audio.service.resume.

            Args:
                message: message bus message, not used but required
        """
        if self.current:
            self.current.resume()
            self.current.ocp_resume()

    @require_native_source()
    def _next(self, message=None):
        """
            Handler for mycroft.audio.service.next. Skips current track and
            starts playing the next.

            Args:
                message: message bus message, not used but required
        """
        if self.current:
            self.current.next()

    @require_native_source()
    def _prev(self, message=None):
        """
            Handler for mycroft.audio.service.prev. Starts playing the previous
            track.

            Args:
                message: message bus message, not used but required
        """
        if self.current:
            self.current.previous()

    @require_native_source()
    def _perform_stop(self, message=None):
        """Stop audioservice if active."""
        if self.current:
            name = self.current.name
            if self.current.stop():
                self.current.ocp_stop()
                if message:
                    msg = message.reply("mycroft.stop.handled",
                                        {"by": "audio:" + name})
                else:
                    msg = Message("mycroft.stop.handled",
                                  {"by": "audio:" + name})
                self.bus.emit(msg)

            # ensure we don't leave the volume ducked
            self.current.restore_volume()
            self.volume_is_low = False

        self.current = None

    @require_native_source()
    def _stop(self, message=None):
        """
            Handler for mycroft.stop. Stops any playing service.

            Args:
                message: message bus message, not used but required
        """
        if time.monotonic() - self.play_start_time > 1:
            LOG.debug('stopping all playing services')
            with self.service_lock:
                try:
                    self._perform_stop(message)
                except Exception as e:
                    LOG.exception(e)
                    LOG.error("failed to stop!")
        LOG.info('END Stop')

    @require_native_source()
    def _lower_volume_on_speak(self, message=None):
        """
            Is triggered when mycroft starts to speak and reduces the volume.

            Args:
                message: message bus message, not used but required
        """
        self.volume_is_speaking = True
        if self.current and not self.volume_is_low:
            LOG.debug('lowering volume')
            self.current.lower_volume()
            self.volume_is_low = True

    @require_native_source()
    def _restore_volume_on_speak(self, message=None):
        """Triggered when OVOS is done speaking and restores the volume."""
        self.volume_is_speaking = False
        if self.current and self.volume_is_low:
            LOG.debug('restoring volume')
            self.volume_is_low = False
            self.current.restore_volume()

    @require_native_source()
    def _restore_volume_on_handled(self, message=None):
        """Triggered when OVOS is done handling an utterance
        (speech might still be happening)"""
        if self.current and self.volume_is_low and not self.volume_is_speaking:
            # if speech is not happening, restore volume
            # intent has been handled and
            # no more speak messages are coming -> vol won't be restored otherwise
            LOG.debug('restoring volume')
            self.volume_is_low = False
            self.current.restore_volume()

    @require_native_source()
    def _lower_volume_on_record(self, message=None):
        """
            Is triggered when OVOS starts to record audio and reduces the volume.

            Args:
                message: message bus message, not used but required
        """
        if self.current and not self.volume_is_low:
            LOG.debug('lowering volume')
            self.current.lower_volume()
            self.volume_is_low = True

    @require_native_source()
    def _restore_volume_after_record(self, message=None):
        """
            Restores the volume when OVOS is done recording.
            If no utterance detected, restore immediately.
            If no response is made in reasonable time, then also restore.

            Args:
                message: message bus message, not used but required
        """

        def restore_volume(msg=message):
            if self.volume_is_low and self.current:
                LOG.debug('restoring volume')
                self.current.restore_volume()

        if self.current:
            self.bus.on('recognizer_loop:speech.recognition.unknown',
                        restore_volume)
            speak_msg_detected = self.bus.wait_for_message('speak',
                                                           timeout=8.0)
            if not speak_msg_detected:
                restore_volume()
            self.bus.remove('recognizer_loop:speech.recognition.unknown',
                            restore_volume)
        else:
            LOG.debug("No audio service to restore volume of")

    def _extract(self, tracks: Union[List[str], List[Tuple[str, str]]]) -> List[str]:
        """convert uris into real streams that can be played, eg. handle youtube urls"""
        xtracted = []
        xtract = load_stream_extractors()  # @lru_cache, its a lazy loaded singleton
        for t in tracks:
            if isinstance(t, str):
                xtracted.append(xtract.extract_stream(t, video=False)["uri"])
            else:  # (uri, mime)
                xtracted.append(xtract.extract_stream(t[0], video=False)["uri"])
        return xtracted

    def play(self, tracks: Union[List[str], List[Tuple[str, str]]],
             prefered_service: Optional[str], repeat: bool =False):
        """
            play starts playing the audio on the prefered service if it
            supports the uri. If not the next best backend is found.

            Args:
                tracks: list of tracks to play.
                repeat: should the playlist repeat
                prefered_service: indecates the service the user prefer to play
                                  the tracks.
        """
        self._perform_stop()

        if isinstance(tracks[0], str):
            uri_type = tracks[0].split(':')[0]
        else:
            uri_type = tracks[0][0].split(':')[0]

        LOG.debug(f"track uri type: {uri_type}")

        tracks = self._extract(tracks)  # ensure playable streams

        # check if user requested a particular service
        if prefered_service and uri_type in prefered_service.supported_uris():
            selected_service = prefered_service
        # check if default supports the uri
        elif self.default and uri_type in self.default.supported_uris():
            LOG.debug(f"Using default backend ({self.default.name})")
            selected_service = self.default
        else:  # Check if any other service can play the media
            LOG.debug("Searching the services")
            for s in self.service:
                if uri_type in s.supported_uris():
                    LOG.debug(f"Service {s.name} supports URI {uri_type}")
                    selected_service = s
                    break
            else:
                LOG.info('No service found for uri_type: ' + uri_type)
                self.bus.emit(Message("ovos.common_play.media.state",
                                      {"state": MediaState.INVALID_MEDIA}))
                return
        if not selected_service.supports_mime_hints:
            tracks = [t[0] if isinstance(t, list) else t for t in tracks]

        LOG.info(f"Selected player: {selected_service.name}")
        self.current = selected_service
        self.current.clear_list()
        self.current.add_list(tracks)

        try:
            self.current.play(repeat)
            self.current.ocp_start()
        except Exception as e:
            LOG.exception(f"failed to play with {self.current}")
            self.current.ocp_error()
        self.play_start_time = time.monotonic()

    @require_native_source()
    def _queue(self, message):
        if self.current:
            with self.service_lock:
                try:
                    tracks = message.data['tracks']
                    self.current.add_list(tracks)
                except Exception as e:
                    LOG.exception(e)
                    LOG.error("failed to queue tracks!")
        else:
            self._play(message)

    @require_native_source()
    def _play(self, message):
        """
            Handler for mycroft.audio.service.play. Starts playback of a
            tracklist. Also  determines if the user requested a special
            service.

            Args:
                message: message bus message, not used but required
        """
        with self.service_lock:
            tracks = message.data['tracks']
            repeat = message.data.get('repeat', False)
            # Find if the user wants to use a specific backend
            for s in self.service:
                try:
                    if ('utterance' in message.data and
                            s.name in message.data['utterance']):
                        prefered_service = s
                        LOG.debug(s.name + ' would be preferred')
                        break
                except Exception as e:
                    LOG.error(f"failed to parse audio service name: {s}")
            else:
                prefered_service = None
            try:
                self.play(tracks, prefered_service, repeat)
                # time.sleep(0.5)  # TODO: Was this hard-coded delay necessary?
            except Exception as e:
                LOG.exception(e)

    @require_native_source()
    def _track_info(self, message):
        """
            Returns track info on the message bus.

            Args:
                message: message bus message, not used but required
        """
        if self.current:
            track_info = self.current.track_info()
        else:
            track_info = {}
        self.bus.emit(message.reply('mycroft.audio.service.track_info_reply',
                                    data=track_info))

    @require_native_source()
    def _list_backends(self, message):
        """ Return a dict of available backends. """
        data = {}
        for s in self.service:
            info = {
                'supported_uris': s.supported_uris(),
                'default': s == self.default,
                'remote': isinstance(s, RemoteAudioBackend)
            }
            data[s.name] = info
        self.bus.emit(message.response(data))

    @require_native_source()
    def _get_track_length(self, message):
        """
        getting the duration of the audio in milliseconds
        """
        dur = None
        if self.current:
            dur = self.current.get_track_length()
        self.bus.emit(message.response({"length": dur}))

    @require_native_source()
    def _get_track_position(self, message):
        """
        get current position in milliseconds
        """
        pos = None
        if self.current:
            pos = self.current.get_track_position()
        self.bus.emit(message.response({"position": pos}))

    @require_native_source()
    def _set_track_position(self, message):
        """
            Handle message bus command to go to position (in milliseconds)

            Args:
                message: message bus message
        """
        milliseconds = message.data.get("position")
        if milliseconds and self.current:
            self.current.set_track_position(milliseconds)

    @require_native_source()
    def _seek_forward(self, message):
        """
            Handle message bus command to skip X seconds

            Args:
                message: message bus message
        """
        seconds = message.data.get("seconds", 1)
        if self.current:
            self.current.seek_forward(seconds)

    @require_native_source()
    def _seek_backward(self, message):
        """
            Handle message bus command to rewind X seconds

            Args:
                message: message bus message
        """
        seconds = message.data.get("seconds", 1)
        if self.current:
            self.current.seek_backward(seconds)

    def shutdown(self):
        for s in self.service:
            try:
                LOG.info('shutting down ' + s.name)
                s.shutdown()
            except Exception as e:
                LOG.error('shutdown of ' + s.name + ' failed: ' + repr(e))

        # remove listeners
        self.bus.remove('mycroft.audio.service.play', self._play)
        self.bus.remove('mycroft.audio.service.queue', self._queue)
        self.bus.remove('mycroft.audio.service.pause', self._pause)
        self.bus.remove('mycroft.audio.service.resume', self._resume)
        self.bus.remove('mycroft.audio.service.stop', self._stop)
        self.bus.remove('mycroft.audio.service.next', self._next)
        self.bus.remove('mycroft.audio.service.prev', self._prev)
        self.bus.remove('mycroft.audio.service.track_info', self._track_info)
        self.bus.remove('mycroft.audio.service.get_track_position', self._get_track_position)
        self.bus.remove('mycroft.audio.service.set_track_position', self._set_track_position)
        self.bus.remove('mycroft.audio.service.get_track_length', self._get_track_length)
        self.bus.remove('mycroft.audio.service.seek_forward', self._seek_forward)
        self.bus.remove('mycroft.audio.service.seek_backward', self._seek_backward)
        self.bus.remove('recognizer_loop:audio_output_start', self._lower_volume_on_speak)
        self.bus.remove('recognizer_loop:record_begin', self._lower_volume_on_record)
        self.bus.remove('recognizer_loop:audio_output_end', self._restore_volume_on_speak)
        self.bus.remove('recognizer_loop:record_end', self._restore_volume_after_record)
        self.bus.remove('ovos.utterance.handled', self._restore_volume_on_handled)
