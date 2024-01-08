from ovos_bus_client.message import Message

from ovos_config.config import Configuration
from ovos_plugin_manager.templates.media import RemoteVideoBackend
from ovos_utils.log import LOG
from .base import BaseMediaService


class WebService(BaseMediaService):
    """ Video Service class.
        Handles playback of web and selecting proper backend for the uri
        to be played.
    """

    def __init__(self, bus, config=None, autoload=True, validate_source=True):
        """
            Args:
                bus: Mycroft messagebus
        """
        config = config or Configuration().get("Web") or {}
        super().__init__(bus, config, autoload, validate_source)

    def _get_preferred_web_backend(self):
        """
        Check configuration and available backends to select a preferred backend

        NOTE - the bus api tells us what backends are loaded,however it does not
        provide "type", so we need to get that from config, we still hit the
        messagebus to account for loading failures, even if config claims
        backend is enabled it might not load
        """
        cfg = self.config["backends"]
        available = [k for k in self.available_backends().keys()
                     if cfg[k].get("type", "") != "ovos_common_play"]
        preferred = self.config.get("preferred_web_services") or ["qt5", "vlc"]
        for b in preferred:
            if b in available:
                return b
        LOG.error("Preferred web service backend not installed")
        return "simple"

    def load_services(self):
        """Method for loading services.

        Sets up the global service, default and registers the event handlers
        for the subsystem.
        """
        # TODO
        found_plugins = find_web_service_plugins()

        local = []
        remote = []
        for plugin_name, plugin_module in found_plugins.items():
            LOG.info(f'Loading web service plugin: {plugin_name}')
            s = setup_web_service(plugin_module, config=self.config, bus=self.bus)
            if not s:
                continue
            if isinstance(s, RemoteVideoBackend):
                remote += s
            else:
                local += s

        # Sort services so local services are checked first
        self.service = local + remote

        # Register end of track callback
        for s in self.service:
            s.set_track_start_callback(self.track_start)

        LOG.info('Finding default web backend...')
        self.default = self._get_preferred_web_backend()

        # Setup event handlers
        self.bus.on('ovos.web.service.play', self._play)
        self.bus.on('ovos.web.service.pause', self._pause)
        self.bus.on('ovos.web.service.resume', self._resume)
        self.bus.on('ovos.web.service.stop', self._stop)
        self.bus.on('ovos.web.service.track_info', self._track_info)
        self.bus.on('ovos.web.service.list_backends', self._list_backends)
        self.bus.on('ovos.web.service.set_track_position', self._set_track_position)
        self.bus.on('ovos.web.service.get_track_position', self._get_track_position)
        self.bus.on('ovos.web.service.get_track_length', self._get_track_length)
        self.bus.on('ovos.web.service.seek_forward', self._seek_forward)
        self.bus.on('ovos.web.service.seek_backward', self._seek_backward)
        self.bus.on('ovos.web.service.duck', self._lower_volume)
        self.bus.on('ovos.web.service.unduck', self._restore_volume)

        self._loaded.set()  # Report services loaded

        return self.service

    def track_start(self, track):
        """Callback method called from the services to indicate start of
        playback of a track or end of playlist.
        """
        if track:
            # Inform about the track about to start.
            LOG.debug('New track coming up!')
            self.bus.emit(Message('ovos.web.playing_track',
                                  data={'track': track}))
        else:
            # If no track is about to start last track of the queue has been
            # played.
            LOG.debug('End of playlist!')
            self.bus.emit(Message('ovos.web.queue_end'))

    def remove_listeners(self):
        self.bus.remove('ovos.web.service.play', self._play)
        self.bus.remove('ovos.web.service.pause', self._pause)
        self.bus.remove('ovos.web.service.resume', self._resume)
        self.bus.remove('ovos.web.service.stop', self._stop)
        self.bus.remove('ovos.web.service.track_info', self._track_info)
        self.bus.remove('ovos.web.service.get_track_position', self._get_track_position)
        self.bus.remove('ovos.web.service.set_track_position', self._set_track_position)
        self.bus.remove('ovos.web.service.get_track_length', self._get_track_length)
        self.bus.remove('ovos.web.service.seek_forward', self._seek_forward)
        self.bus.remove('ovos.web.service.seek_backward', self._seek_backward)
