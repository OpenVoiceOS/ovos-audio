import abc
import time
from threading import Lock

from ovos_bus_client.message import Message

from ovos_plugin_manager.templates.media import RemoteAudioBackend, RemoteVideoBackend
from ovos_utils.log import LOG
from ovos_utils.process_utils import MonotonicEvent
from ..utils import validate_message_context


class BaseMediaService:
    def __init__(self, bus, config=None, autoload=True, validate_source=True):
        """
            Args:
                bus: Mycroft messagebus
        """
        self.bus = bus
        self.config = config or {}
        self.service_lock = Lock()

        self.default = None
        self.service = []
        self.current = None
        self.play_start_time = 0
        self.volume_is_low = False
        self.validate_source = validate_source

        self._loaded = MonotonicEvent()
        if autoload:
            self.load_services()

    def available_backends(self):
        """Return available video backends.

        Returns:
            dict with backend names as keys
        """
        data = {}
        for s in self.service:
            info = {
                'supported_uris': s.supported_uris(),
                'default': s == self.default,
                'remote': isinstance(s, RemoteAudioBackend) or
                          isinstance(s, RemoteVideoBackend)
            }
            data[s.name] = info
        return data

    @abc.abstractmethod
    def load_services(self):
        """Method for loading services.

        Sets up the global service, default and registers the event handlers
        for the subsystem.
        """
        raise NotImplementedError

    def wait_for_load(self, timeout=3 * 60):
        """Wait for services to be loaded.

        Args:
            timeout (float): Seconds to wait (default 3 minutes)
        Returns:
            (bool) True if loading completed within timeout, else False.
        """
        return self._loaded.wait(timeout)

    def _pause(self, message=None):
        """
            Handler for ovos.video.service.pause. Pauses the current video
            service.

            Args:
                message: message bus message, not used but required
        """
        if not self._is_message_for_service(message):
            return
        if self.current:
            self.current.pause()
            self.current.ocp_pause()

    def _resume(self, message=None):
        """
            Handler for ovos.video.service.resume.

            Args:
                message: message bus message, not used but required
        """
        if not self._is_message_for_service(message):
            return
        if self.current:
            self.current.resume()
            self.current.ocp_resume()

    def _perform_stop(self, message=None):
        """Stop videoservice if active."""
        if not self._is_message_for_service(message):
            return
        if self.current:
            if self.current.stop():
                self.current.ocp_stop()  # emit ocp state events
                if message:
                    msg = message.reply("mycroft.stop.handled",
                                        {"by": "OCP"})
                else:
                    msg = Message("mycroft.stop.handled",
                                  {"by": "OCP"})
                self.bus.emit(msg)

        self.current = None

    def _stop(self, message=None):
        """
            Handler for mycroft.stop. Stops any playing service.

            Args:
                message: message bus message, not used but required
        """
        if not self._is_message_for_service(message):
            return
        if time.monotonic() - self.play_start_time > 1:
            LOG.debug('stopping all playing services')
            with self.service_lock:
                try:
                    self._perform_stop(message)
                except Exception as e:
                    LOG.exception(e)
                    LOG.error("failed to stop!")
        LOG.info('END Stop')

    def _lower_volume(self, message=None):
        """
            Is triggered when mycroft starts to speak and reduces the volume.

            Args:
                message: message bus message, not used but required
        """
        if not self._is_message_for_service(message):
            return
        if self.current and not self.volume_is_low:
            LOG.debug('lowering volume')
            self.current.lower_volume()
            self.volume_is_low = True

    def _restore_volume(self, message=None):
        """Triggered when mycroft is done speaking and restores the volume."""
        if not self._is_message_for_service(message):
            return
        if self.current and self.volume_is_low:
            LOG.debug('restoring volume')
            self.volume_is_low = False
            self.current.restore_volume()

    def play(self, uri, preferred_service):
        """
            play starts playing the video on the preferred service if it
            supports the uri. If not the next best backend is found.

            Args:
                uri: uri of track to play.
                preferred_service: indicates the service the user prefer to play
                                  the tracks.
        """
        self._perform_stop()

        uri_type = uri.split(':')[0]

        # check if user requested a particular service
        if preferred_service and uri_type in preferred_service.supported_uris():
            selected_service = preferred_service

        # check if default supports the uri
        elif self.default and uri_type in self.default.supported_uris():
            LOG.debug("Using default backend ({})".format(self.default.name))
            selected_service = self.default

        else:  # Check if any other service can play the media
            LOG.debug("Searching the services")
            for s in self.service:
                if uri_type in s.supported_uris():
                    LOG.debug("Service {} supports URI {}".format(s, uri_type))
                    selected_service = s
                    break
            else:
                LOG.info('No service found for uri_type: ' + uri_type)
                return

        selected_service.load_track(uri)
        selected_service.play()
        selected_service.ocp_start()
        self.current = selected_service
        self.play_start_time = time.monotonic()

    def _is_message_for_service(self, message):
        if not message or not self.validate_source:
            return True
        return validate_message_context(message)

    def _play(self, message):
        """
            Handler for ovos.video.service.play. Starts playback of a
            tracklist. Also  determines if the user requested a special
            service.

            Args:
                message: message bus message, not used but required
        """
        if not self._is_message_for_service(message):
            return
        with self.service_lock:
            tracks = message.data['tracks']

            # Find if the user wants to use a specific backend
            for s in self.service:
                try:
                    if ('utterance' in message.data and
                            s.name in message.data['utterance']):
                        preferred_service = s
                        LOG.debug(s.name + ' would be preferred')
                        break
                except Exception as e:
                    LOG.error(f"failed to parse video service name: {s}")
            else:
                preferred_service = None

            try:
                self.play(tracks, preferred_service)
                time.sleep(0.5)
            except Exception as e:
                LOG.exception(e)

    def _track_info(self, message):
        """
            Returns track info on the message bus.

            Args:
                message: message bus message, not used but required
        """
        if not self._is_message_for_service(message):
            return
        if self.current:
            track_info = self.current.track_info()
        else:
            track_info = {}
        self.bus.emit(message.response(track_info))

    def _list_backends(self, message):
        """ Return a dict of available backends. """
        if not self._is_message_for_service(message):
            return
        data = self.available_backends()
        self.bus.emit(message.response(data))

    def _get_track_length(self, message):
        """
        getting the duration of the video in milliseconds
        """
        if not self._is_message_for_service(message):
            return
        dur = None
        if self.current:
            dur = self.current.get_track_length()
        self.bus.emit(message.response({"length": dur}))

    def _get_track_position(self, message):
        """
        get current position in milliseconds
        """
        if not self._is_message_for_service(message):
            return
        pos = None
        if self.current:
            pos = self.current.get_track_position()
        self.bus.emit(message.response({"position": pos}))

    def _set_track_position(self, message):
        """
            Handle message bus command to go to position (in milliseconds)

            Args:
                message: message bus message
        """
        if not self._is_message_for_service(message):
            return
        milliseconds = message.data.get("position")
        if milliseconds and self.current:
            self.current.set_track_position(milliseconds)

    def _seek_forward(self, message):
        """
            Handle message bus command to skip X seconds

            Args:
                message: message bus message
        """
        if not self._is_message_for_service(message):
            return
        seconds = message.data.get("seconds", 1)
        if self.current:
            self.current.seek_forward(seconds)

    def _seek_backward(self, message):
        """
            Handle message bus command to rewind X seconds

            Args:
                message: message bus message
        """
        if not self._is_message_for_service(message):
            return
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
        self.remove_listeners()

    def remove_listeners(self):
        pass  # for extra logic to be called on shutdown
