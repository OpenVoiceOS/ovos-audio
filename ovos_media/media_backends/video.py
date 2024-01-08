from ovos_bus_client.message import Message

from ovos_config.config import Configuration
from ovos_plugin_manager.templates.media import RemoteVideoBackend
from ovos_utils.log import LOG
from .base import BaseMediaService


class VideoService(BaseMediaService):
    """ Video Service class.
        Handles playback of video and selecting proper backend for the uri
        to be played.
    """

    def __init__(self, bus, config=None, autoload=True, validate_source=True):
        """
            Args:
                bus: Mycroft messagebus
        """
        config = config or Configuration().get("Video") or {}
        super().__init__(bus, config, autoload, validate_source)

    def _get_preferred_video_backend(self):
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
        preferred = self.config.get("preferred_video_services") or ["qt5", "vlc"]
        for b in preferred:
            if b in available:
                return b
        LOG.error("Preferred video service backend not installed")
        return "simple"

    def load_services(self):
        """Method for loading services.

        Sets up the global service, default and registers the event handlers
        for the subsystem.
        """
        # TODO
        found_plugins = find_video_service_plugins()

        local = []
        remote = []
        for plugin_name, plugin_module in found_plugins.items():
            LOG.info(f'Loading video service plugin: {plugin_name}')
            s = setup_video_service(plugin_module, config=self.config, bus=self.bus)
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

        LOG.info('Finding default video backend...')
        self.default = self._get_preferred_video_backend()

        # Setup event handlers
        self.bus.on('ovos.video.service.play', self._play)
        self.bus.on('ovos.video.service.pause', self._pause)
        self.bus.on('ovos.video.service.resume', self._resume)
        self.bus.on('ovos.video.service.stop', self._stop)
        self.bus.on('ovos.video.service.track_info', self._track_info)
        self.bus.on('ovos.video.service.list_backends', self._list_backends)
        self.bus.on('ovos.video.service.set_track_position', self._set_track_position)
        self.bus.on('ovos.video.service.get_track_position', self._get_track_position)
        self.bus.on('ovos.video.service.get_track_length', self._get_track_length)
        self.bus.on('ovos.video.service.seek_forward', self._seek_forward)
        self.bus.on('ovos.video.service.seek_backward', self._seek_backward)
        self.bus.on('ovos.video.service.duck', self._lower_volume)
        self.bus.on('ovos.video.service.unduck', self._restore_volume)

        self._loaded.set()  # Report services loaded

        return self.service

    def track_start(self, track):
        """Callback method called from the services to indicate start of
        playback of a track or end of playlist.
        """
        if track:
            # Inform about the track about to start.
            LOG.debug('New track coming up!')
            self.bus.emit(Message('ovos.video.playing_track',
                                  data={'track': track}))
        else:
            # If no track is about to start last track of the queue has been
            # played.
            LOG.debug('End of playlist!')
            self.bus.emit(Message('ovos.video.queue_end'))

    def remove_listeners(self):
        self.bus.remove('ovos.video.service.play', self._play)
        self.bus.remove('ovos.video.service.pause', self._pause)
        self.bus.remove('ovos.video.service.resume', self._resume)
        self.bus.remove('ovos.video.service.stop', self._stop)
        self.bus.remove('ovos.video.service.track_info', self._track_info)
        self.bus.remove('ovos.video.service.get_track_position', self._get_track_position)
        self.bus.remove('ovos.video.service.set_track_position', self._set_track_position)
        self.bus.remove('ovos.video.service.get_track_length', self._get_track_length)
        self.bus.remove('ovos.video.service.seek_forward', self._seek_forward)
        self.bus.remove('ovos.video.service.seek_backward', self._seek_backward)
