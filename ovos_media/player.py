import random
import time
from os.path import join, dirname
from threading import RLock
from typing import List, Union

from ovos_plugin_manager.ocp import StreamHandler
from ovos_utils.gui import is_gui_connected, is_gui_running
from ovos_utils.log import LOG
from ovos_utils.messagebus import Message
from ovos_utils.ocp import MediaType, Playlist
from ovos_utils.ocp import OCP_ID, PlayerState, LoopState, PlaybackType, PlaybackMode, TrackState, MediaState, \
    MediaEntry
from ovos_workshop import OVOSAbstractApplication
from .media_backends import AudioService,VideoService,WebService
from ovos_plugin_manager.templates.media import MediaBackend
from .mpris import MprisPlayerCtl


class OCPMediaCatalog:
    def __init__(self, bus, config):
        self.bus = bus
        self.search_playlist = Playlist()
        self.ocp_skills = {}
        self.featured_skills = {}
        self.search_lock = RLock()
        self.config = config or {}
        self.bus.on("ovos.common_play.skills.detach", self.handle_ocp_skill_detach)
        self.bus.on("ovos.common_play.announce", self.handle_skill_announce)
        # TODO - add search results clear/replace events

    def shutdown(self):
        self.bus.remove("ovos.common_play.announce")
        self.bus.remove("ovos.common_play.skills.detach")

    def handle_skill_announce(self, message):
        skill_id = message.data.get("skill_id")
        skill_name = message.data.get("skill_name") or skill_id
        img = message.data.get("thumbnail")
        has_featured = bool(message.data.get("featured_tracks"))
        media_type = message.data.get("media_type") or [MediaType.GENERIC]

        if skill_id not in self.ocp_skills:
            LOG.debug(f"Registered {skill_id}")
            self.ocp_skills[skill_id] = []

        if has_featured:
            LOG.debug(f"Found skill with featured media: {skill_id}")
            self.featured_skills[skill_id] = {
                "skill_id": skill_id,
                "skill_name": skill_name,
                "thumbnail": img,
                "media_type": media_type
            }

    def handle_ocp_skill_detach(self, message):
        skill_id = message.data["skill_id"]
        if skill_id in self.ocp_skills:
            self.ocp_skills.pop(skill_id)
        if skill_id in self.featured_skills:
            self.featured_skills.pop(skill_id)

    def get_featured_skills(self, adult=False):
        # trigger a presence announcement from all loaded ocp skills
        self.bus.emit(Message("ovos.common_play.skills.get"))
        time.sleep(0.2)
        skills = list(self.featured_skills.values())
        if adult:
            return skills
        return [s for s in skills
                if MediaType.ADULT not in s["media_type"] and
                MediaType.HENTAI not in s["media_type"]]

    def clear(self):
        self.search_playlist.clear()

    def replace(self, playlist):
        self.search_playlist.replace(playlist)


class NowPlaying(MediaEntry):
    """ Live Tracking of currently playing media via bus events """

    def __init__(self, bus, *args, **kwargs):
        self.bus = bus
        self.stream_xtract = StreamHandler()
        self.position = 0
        super().__init__(*args, **kwargs)
        self.bus.on("ovos.common_play.track.state", self.handle_track_state_change)
        self.bus.on("ovos.common_play.media.state", self.handle_media_state_change)
        self.bus.on("ovos.common_play.play", self.handle_external_play)
        self.bus.on("ovos.common_play.playback_time", self.handle_sync_seekbar)

    def as_entry(self) -> MediaEntry:
        """
        Return a MediaEntry representation of this object
        """
        return MediaEntry(**self.as_dict)

    def shutdown(self):
        """
        Remove NowPlaying events from the MessageBusClient
        """
        self.bus.remove("ovos.common_play.track.state")
        self.bus.remove("ovos.common_play.media.state")
        self.bus.remove('ovos.common_play.play')
        self.bus.remove('ovos.common_play.playback_time')

    def reset(self):
        """
        Reset the NowPlaying MediaEntry to default parameters
        """
        LOG.debug("Resetting NowPlaying")
        self.title = ""
        self.artist = ""
        self.skill_id = ""
        self.position = 0
        self.length = 0
        self.javascript = ""
        self.playback = PlaybackType.UNDEFINED
        self.status = TrackState.DISAMBIGUATION
        self.media_type = MediaType.GENERIC
        self.skill_icon = ""
        self.image = ""

    def update(self, entry: dict, skipkeys: list = None, newonly: bool = False):
        """
        Update this MediaEntry
        @param entry: dict or MediaEntry object to update this object with
        @param skipkeys: list of keys to not change
        @param newonly: if True, only adds new keys; existing keys are unchanged
        """
        if isinstance(entry, MediaEntry):
            entry = entry.as_dict
        super().update(entry, skipkeys, newonly)
        # uri updates should not be skipped
        if newonly and entry.get("uri"):
            super().update({"uri": entry["uri"]})

    def extract_stream(self):
        """
        Get metadata from ocp_plugins and add it to this MediaEntry
        """
        uri = self.uri
        if not uri:
            raise ValueError("No URI to extract stream from")
        if self.playback == PlaybackType.VIDEO:
            video = True
        else:
            video = False
        meta = self.stream_xtract.extract_stream(uri, video)
        # update media entry with new data
        if meta:
            LOG.info(f"OCP plugins metadata: {meta}")
            self.update(meta, newonly=True)
        elif not any((uri.startswith(s) for s in ["http", "file", "/"])):
            LOG.info(f"OCP WARNING: plugins returned no metadata for uri {uri}")

    # bus api
    def handle_external_play(self, message):
        """
        Handle 'ovos.common_play.play' Messages. Update the metadata with new
        data received unconditionally, otherwise previous song keys might
        bleed into the new track
        @param message: Message associated with request
        """
        if message.data.get("tracks"):
            # backwards compat / old style
            playlist = message.data["tracks"]
            media = playlist[0]
        else:
            media = message.data.get("media", {})
        if media:
            self.update(media, newonly=False)

    # events from media services
    def handle_track_state_change(self, message):
        """
        Handle 'ovos.common_play.track.state' Messages. Update status
        @param message: Message with updated `state` data
        @return:
        """
        state = message.data.get("state")
        if state is None:
            raise ValueError(f"Got state update message with no state: "
                             f"{message}")
        if isinstance(state, int):
            state = TrackState(state)
        if not isinstance(state, TrackState):
            raise ValueError(f"Expected int or TrackState, but got: {state}")

        if state == self.status:
            return
        self.status = state
        LOG.info(f"TrackState changed: {repr(state)}")

        if state == TrackState.PLAYING_SKILL:
            # skill is handling playback internally
            pass
        elif state == TrackState.PLAYING_VIDEO:
            # ovos common play is handling playback in GUI
            pass
        elif state == TrackState.PLAYING_AUDIO:
            # ovos common play is handling playback in GUI
            pass

        elif state == TrackState.DISAMBIGUATION:
            # alternative results list
            pass
        elif state in [TrackState.QUEUED_SKILL,
                       TrackState.QUEUED_VIDEO,
                       TrackState.QUEUED_AUDIO]:
            # audio service is handling playback and this is in playlist
            pass

    def handle_media_state_change(self, message):
        """
        Handle 'ovos.common_play.media.state' Messages. If ended, reset.
        @param message: Message with updated MediaState
        """
        state = message.data.get("state")
        if state is None:
            raise ValueError(f"Got state update message with no state: "
                             f"{message}")
        if isinstance(state, int):
            state = MediaState(state)
        if not isinstance(state, MediaState):
            raise ValueError(f"Expected int or TrackState, but got: {state}")
        # Don't do anything. Let OCP manage this object's state
        # if state == MediaState.END_OF_MEDIA:
        #     # playback ended, allow next track to change metadata again
        #     self.reset()

    def handle_sync_seekbar(self, message):
        """
        Handle 'ovos.common_play.playback_time' Messages sent by audio backend
        @param message: Message with 'length' and 'position' data
        """
        self.length = message.data["length"]
        self.position = message.data["position"]

    def handle_sync_trackinfo(self, message):
        """
        Handle 'mycroft.audio.service.track_info_reply' Messages with current
        media defined in message.data
        @param message: Message with dict MediaEntry data
        """
        self.update(message.data)


class OCPMediaPlayer(OVOSAbstractApplication):
    """OCP Virtual Media Player

    for OVOS this is all that exists and represents all loaded and currently playing media

    "now playing" is tracked and managed by this interface
    """

    def __init__(self, bus=None, settings=None, lang=None, gui=None,
                 resources_dir=None, skill_id=OCP_ID, **kwargs):
        resources_dir = resources_dir or join(dirname(__file__), "res")

        self.state: PlayerState = PlayerState.STOPPED
        self.loop_state: LoopState = LoopState.NONE
        self.media_state: MediaState = MediaState.NO_MEDIA
        self.playlist: Playlist = Playlist()
        self.shuffle: bool = False
        self.track_history = {}  # Dict of track URI to play count

        # Define things referenced in `bind`
        self.now_playing: NowPlaying = None
        self.media: OCPMediaCatalog = None
        self.audio_service = None
        self.video_service = None
        self.web_service = None
        self.current: MediaBackend = None

        super().__init__(skill_id=skill_id, bus=bus, resources_dir=resources_dir,
                         lang=lang, **kwargs)
        if settings:
            self.settings.merge(settings)

        self._paused_on_duck = False

        # mpris settings
        manage_players = self.settings.get("manage_external_players", False)
        if self.settings.get('disable_mpris'):
            LOG.info("MPRIS integration is disabled")
            self.mpris = None
        else:
            self.mpris = MprisPlayerCtl(self, manage_players=manage_players)

    def bind(self, bus=None):
        """
        Initialize components that need a MessageBusClient or instance of this
        object.
        @param bus: MessageBusClient object to register events on
        """
        super(OCPMediaPlayer, self).bind(bus)
        self.now_playing = NowPlaying(bus)
        self.media = OCPMediaCatalog(self.bus, self.settings)
        self.audio_service = AudioService(self.bus)
        self.video_service = VideoService(self.bus)
        self.web_service = WebService(self.bus)
        self.register_bus_handlers()

    def register_bus_handlers(self):
        # ovos common play bus api
        self.add_event('ovos.common_play.player.state', self.handle_player_state_update)
        self.add_event('ovos.common_play.media.state', self.handle_player_media_update)
        self.add_event('ovos.common_play.play', self.handle_play_request)
        self.add_event('ovos.common_play.pause', self.handle_pause_request)
        self.add_event('ovos.common_play.resume', self.handle_resume_request)
        self.add_event('ovos.common_play.stop', self.handle_stop_request)
        self.add_event('ovos.common_play.next', self.handle_next_request)
        self.add_event('ovos.common_play.previous', self.handle_prev_request)
        self.add_event('ovos.common_play.seek', self.handle_seek_request)
        self.add_event('ovos.common_play.get_track_length', self.handle_track_length_request)
        self.add_event('ovos.common_play.set_track_position', self.handle_set_track_position_request)
        self.add_event('ovos.common_play.get_track_position', self.handle_track_position_request)
        self.add_event('ovos.common_play.track_info', self.handle_track_info_request)
        self.add_event('ovos.common_play.list_backends', self.handle_list_backends_request)
        self.add_event('ovos.common_play.playlist.set', self.handle_playlist_set_request)
        self.add_event('ovos.common_play.playlist.clear', self.handle_playlist_clear_request)
        self.add_event('ovos.common_play.playlist.queue', self.handle_playlist_queue_request)
        self.add_event('ovos.common_play.duck', self.handle_duck_request)
        self.add_event('ovos.common_play.unduck', self.handle_unduck_request)
        self.add_event('ovos.common_play.cork', self.handle_cork_request)
        self.add_event('ovos.common_play.uncork', self.handle_uncork_request)
        self.add_event('ovos.common_play.shuffle.set', self.handle_set_shuffle)
        self.add_event('ovos.common_play.shuffle.unset', self.handle_unset_shuffle)
        self.add_event('ovos.common_play.repeat.set', self.handle_set_repeat)
        self.add_event('ovos.common_play.repeat.unset', self.handle_unset_repeat)

    @property
    def active_skill(self) -> str:
        """
        Return the skill_id of the skill providing the current media
        """
        return self.now_playing.skill_id

    @property
    def active_backend(self) -> PlaybackType:
        """
        Return the PlaybackType for the current media
        """
        return self.now_playing.playback

    @property
    def tracks(self) -> List[MediaEntry]:
        """
        Return the current queue as a list of MediaEntry objects
        """
        return self.playlist.entries

    @property
    def disambiguation(self) -> List[MediaEntry]:
        """
        Return a list of the previous search results as MediaEntry objects
        """
        return self.media.search_playlist.entries

    @property
    def can_prev(self) -> bool:
        """
        Return true if there is a previous track in the queue to skip to
        """
        if self.active_backend != PlaybackType.MPRIS and \
                self.playlist.is_first_track:
            return False
        return True

    @property
    def can_next(self) -> bool:
        """
        Return true if there is a next track in the queue to skip to
        """
        if self.loop_state != LoopState.NONE or \
                self.shuffle or \
                self.active_backend == PlaybackType.MPRIS:
            return True
        elif self.settings.get("merge_search", True) and \
                not self.media.search_playlist.is_last_track:
            return True
        elif not self.playlist.is_last_track:
            return True
        return False

    # state
    def set_media_state(self, state: MediaState):
        """
        Set self.media_state and emit an event announcing this state change.
        @param state: New MediaState
        """
        if not isinstance(state, MediaState):
            raise TypeError(f"Expected MediaState and got: {state}")
        if state == self.media_state:
            return
        self.media_state = state
        self.bus.emit(Message("ovos.common_play.media.state",
                              {"state": self.media_state}))

    def set_player_state(self, state: PlayerState):
        """
        Set self.state, update the GUI and MPRIS (if available), and emit an
        event announcing this state change.
        @param state: New PlayerState
        """
        if not isinstance(state, PlayerState):
            raise TypeError(f"Expected PlayerState and got: {state}")
        if state == self.state:
            return
        self.state = state
        state2str = {PlayerState.PLAYING: "Playing",
                     PlayerState.PAUSED: "Paused",
                     PlayerState.STOPPED: "Stopped"}
        if self.mpris:
            self.mpris.update_props({"CanPause": self.state == PlayerState.PLAYING,
                                     "CanPlay": self.state == PlayerState.PAUSED,
                                     "PlaybackStatus": state2str[state]})
        self.bus.emit(Message("ovos.common_play.player.state",
                              {"state": self.state}))

    def set_now_playing(self, track: Union[dict, MediaEntry, Playlist]):
        """
        Set `track` as the currently playing media, update the playlist, and
        notify any GUI or MPRIS clients. Adds `track` to `playlist`
        @param track: MediaEntry or dict representation of a MediaEntry to play
        """
        LOG.debug(f"Playing: {track}")
        if isinstance(track, dict):
            LOG.debug("Handling dict track")
            track = MediaEntry(**track)
        if not isinstance(track, MediaEntry):
            raise ValueError(f"Expected MediaEntry, but got: {track}")
        self.now_playing.reset()  # reset now_playing to remove old metadata
        if isinstance(track, MediaEntry):
            # single track entry (MediaEntry)
            self.now_playing.update(track)
            # copy now_playing (without event handlers) to playlist
            # entry = self.now_playing.as_entry()
            if track not in self.playlist:  # compared by uri
                self.playlist.add_entry(track)

        elif isinstance(track, Playlist):
            # this is a playlist result (list of dicts)
            self.playlist.clear()
            for entry in track:
                self.playlist.add_entry(entry)
            self.now_playing.update(self.playlist[0])

        # sync playlist position
        self.playlist.goto_track(self.now_playing)

        if self.mpris:
            self.mpris.update_props(
                {"Metadata": self.now_playing.mpris_metadata}
            )

    # stream handling
    def validate_stream(self) -> bool:
        """
        Validate that self.now_playing is playable and update the GUI if it is
        @return: True if the `now_playing` stream can be handled
        """
        if self.active_backend not in [PlaybackType.SKILL,
                                       PlaybackType.UNDEFINED,
                                       PlaybackType.MPRIS]:
            try:
                self.now_playing.extract_stream()
            except Exception as e:
                LOG.exception(e)
                return False
            # check for is_gui_running is much faster as it doesnt need bus messages back and forth
            has_gui = is_gui_running() or is_gui_connected(self.bus)
            if not has_gui or self.settings.get("force_audioservice", False) or \
                    self.settings.get("playback_mode") == PlaybackMode.FORCE_AUDIO:
                # No gui, so lets force playback to use audio only
                self.now_playing.playback = PlaybackType.AUDIO

        return True

    def on_invalid_media(self):
        """
        Handle media playback errors. Show an error and play the next track.
        """
        LOG.warning(f"Failed to play: {self.now_playing}")
        self.play_next()

    # media controls
    def play_media(self, track: Union[dict, MediaEntry],
                   disambiguation: List[Union[dict, MediaEntry]] = None,
                   playlist: List[Union[dict, MediaEntry]] = None):
        """
        Start playing the requested media, replacing any current playback.
        @param track: dict or MediaEntry to start playing
        @param disambiguation: list of tracks returned from search
        @param playlist: list of tracks in the current playlist
        """
        if isinstance(track, dict):
            track = MediaEntry(**track)
        if not isinstance(track, MediaEntry):
            raise TypeError(f"Expected MediaEntry, got: {track}")
        if self.mpris:
            self.mpris.stop()
        if self.state == PlayerState.PLAYING:
            self.pause()  # make it more responsive
        if disambiguation:
            self.media.search_playlist.replace([t for t in disambiguation
                                                if t not in self.media.search_playlist])
            self.media.search_playlist.sort_by_conf()
            self.media.search_playlist.insert(0, track)
        if playlist:
            self.playlist.replace(playlist)
        if track in self.playlist:
            self.playlist.goto_track(track)
        self.set_now_playing(track)
        self.play()

    def play(self):
        """
        Start playback of the current `now_playing` MediaEntry. Displays the GUI
        player, updates track history, emits events for any listeners, and
        updates mpris (if configured).
        """
        # stop any external media players
        if self.mpris and not self.mpris.stop_event.is_set():
            LOG.info("Requested playback with mpris not stopped")
            self.mpris.stop()

        # validate new stream
        if not self.validate_stream():
            LOG.warning("Stream Validation Failed")
            self.on_invalid_media()
            return

        self.track_history.setdefault(self.now_playing.uri, 0)
        self.track_history[self.now_playing.uri] += 1

        LOG.debug(f"Requesting playback: {repr(self.active_backend)}")

        if self.active_backend == PlaybackType.AUDIO:
            LOG.debug("Handling playback via audio_service")
            # we explicitly want to use an audio backend for audio only output
            self.audio_service.play(self.now_playing.uri)
            self.bus.emit(Message("ovos.common_play.track.state",
                                  {"state": TrackState.PLAYING_AUDIO}))
            self.set_player_state(PlayerState.PLAYING)

        elif self.active_backend == PlaybackType.SKILL:
            LOG.debug("Requesting playback: PlaybackType.SKILL")
            self.bus.emit(Message(f'ovos.common_play.{self.now_playing.skill_id}.play',
                                  self.now_playing.info))
            self.bus.emit(Message("ovos.common_play.track.state",
                                  {"state": TrackState.PLAYING_SKILL}))

        elif self.active_backend == PlaybackType.VIDEO:
            LOG.debug("Requesting playback: PlaybackType.VIDEO")
            # handle video natively in mycroft-gui
            self.video_service.play(self.now_playing.uri)
            self.bus.emit(Message("ovos.common_play.track.state",
                                  {"state": TrackState.PLAYING_VIDEO}))

        elif self.active_backend == PlaybackType.WEBVIEW:
            LOG.debug("Requesting playback: PlaybackType.WEBVIEW")
            # open a url in native webview in mycroft-gui
            self.bus.emit(Message("ovos.common_play.track.state",
                                  {"state": TrackState.PLAYING_WEBVIEW}))

        else:
            raise ValueError("invalid playback request")

        if self.mpris:
            self.mpris.update_props({"CanGoNext": self.can_next})
            self.mpris.update_props({"CanGoPrevious": self.can_prev})
        LOG.debug(f"self.active_backend={repr(self.active_backend)}")

    def play_shuffle(self):
        """
        Go to a random position in the playlist and set that MediaEntry as
        'now_playing` (does NOT call 'play').
        """
        LOG.debug("Shuffle == True")
        if len(self.playlist) > 1 and not self.playlist.is_last_track:
            # TODO: does the 'last track' matter in this case?
            self.playlist.set_position(random.randint(0, len(self.playlist)))
            self.set_now_playing(self.playlist.current_track)
        else:
            self.media.search_playlist.next_track()
            self.set_now_playing(self.media.search_playlist.current_track)

    def play_next(self):
        """
        Play the next track in the playlist or search results.
        End playback if there is no next track, accounting for repeat and
        shuffle settings.
        """
        if self.active_backend == PlaybackType.UNDEFINED:
            LOG.error("self.active_backend is undefined")
        elif self.active_backend in [PlaybackType.MPRIS]:
            if self.mpris:
                self.mpris.play_next()
            return
        elif self.active_backend in [PlaybackType.SKILL]:
            LOG.debug(f"Defer playing next track to skill")
            self.bus.emit(Message(f'ovos.common_play.{self.now_playing.skill_id}.next'))
            return
        self.pause()  # make more responsive

        if self.loop_state == LoopState.REPEAT_TRACK:
            LOG.debug("Repeating single track")
        elif self.shuffle:
            LOG.debug("Shuffling")
            self.play_shuffle()
        elif not self.playlist.is_last_track:
            self.playlist.next_track()
            self.set_now_playing(self.playlist.current_track)
            LOG.info(f"Next track index: {self.playlist.position}")
        elif not self.media.search_playlist.is_last_track and \
                self.settings.get("merge_search", True):
            while self.media.search_playlist.current_track in self.playlist:
                # Don't play media already played from the playlist
                self.media.search_playlist.next_track()
            self.set_now_playing(self.media.search_playlist.current_track)
            LOG.info(f"Next search index: "
                     f"{self.media.search_playlist.position}")
        else:
            if self.loop_state == LoopState.REPEAT and len(self.playlist):
                LOG.info("end of playlist, repeat == True")
                self.playlist.set_position(0)
            else:
                LOG.info("requested next, but there aren't any more tracks")
                return
        self.play()

    def play_prev(self):
        """
        Play the previous track in the playlist.
        If there is no previous track, do nothing.
        """
        if self.active_backend in [PlaybackType.MPRIS]:
            if self.mpris:
                self.mpris.play_prev()
            return
        elif self.active_backend in [PlaybackType.SKILL,
                                     PlaybackType.UNDEFINED]:
            self.bus.emit(Message(
                f'ovos.common_play.{self.now_playing.skill_id}.prev'))
            return
        self.pause()  # make more responsive

        if self.shuffle:
            # TODO: Should skipping back get a random track instead of previous?
            self.play_shuffle()
        elif not self.playlist.is_first_track:
            self.playlist.prev_track()
            self.set_now_playing(self.playlist.current_track)
            LOG.debug(f"Previous track index: {self.playlist.position}")
            self.play()
        else:
            LOG.debug("requested previous, but already in 1st track")

    def pause(self):
        """
        Ask the current playback to pause.
        """
        LOG.debug(f"Pausing playback: {self.active_backend}")
        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.UNDEFINED]:
            self.audio_service.pause()
        if self.active_backend in [PlaybackType.VIDEO,
                                   PlaybackType.UNDEFINED]:
            self.video_service.pause()
        if self.active_backend in [PlaybackType.SKILL,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(Message(f'ovos.common_play.{self.active_skill}.pause'))
        if self.active_backend in [PlaybackType.MPRIS] and self.mpris:
            self.mpris.pause()
        self.set_player_state(PlayerState.PAUSED)
        self._paused_on_duck = False

    def resume(self):
        """
        Ask any paused or stopped playback to resume.
        """
        LOG.debug(f"Resuming playback: {self.active_backend}")
        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.UNDEFINED]:
            self.audio_service.resume()

        if self.active_backend in [PlaybackType.SKILL,
                                   PlaybackType.UNDEFINED]:
            self.bus.emit(Message(f'ovos.common_play.{self.active_skill}.resume'))

        if self.active_backend in [PlaybackType.VIDEO]:
            self.video_service.resume()

        if self.active_backend in [PlaybackType.MPRIS] and self.mpris:
            self.mpris.resume()

        self.set_player_state(PlayerState.PLAYING)

    def seek(self, position: int):
        """
        Request playback to go to a specific position in the current media
        @param position: milliseconds position to seek to
        """
        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.UNDEFINED]:
            self.audio_service.set_track_position(position / 1000)

    def stop(self):
        """
        Request stopping current playback and searching
        """
        # stop any search still happening
        self.bus.emit(Message("ovos.common_play.search.stop"))

        LOG.debug("Stopping playback")
        if self.active_backend in [PlaybackType.AUDIO,
                                   PlaybackType.UNDEFINED]:
            self.stop_audio_service()
            self.set_player_state(PlayerState.STOPPED)
        if self.active_backend in [PlaybackType.SKILL,
                                   PlaybackType.UNDEFINED]:
            self.stop_audio_skill()
        if self.active_backend in [PlaybackType.VIDEO,
                                   PlaybackType.UNDEFINED]:
            self.stop_gui_player()
            self.set_player_state(PlayerState.STOPPED)
        # if self.active_backend in [PlaybackType.MPRIS] and self.mpris:
        #    self.mpris.stop()

    def stop_gui_player(self):
        """
        Emit a Message notifying the gui player to stop
        """
        self.video_service.stop()

    def stop_audio_skill(self):
        """
        Emit a Message notifying self.active_skill to stop
        """
        self.bus.emit(Message(f'ovos.common_play.{self.active_skill}.stop'))

    def stop_audio_service(self):
        """
        Call self.audio_service.stop()
        """
        self.audio_service.stop()

    def reset(self):
        """
        Reset this instance to clear any media or settings
        """
        self.stop()
        self.playlist.clear()
        self.media.clear()
        self.set_media_state(MediaState.NO_MEDIA)
        self.shuffle = False
        self.loop_state = LoopState.NONE

    def shutdown(self):
        """
        Shutdown this instance and its spawned objects. Remove events.
        """
        self.stop()
        if self.mpris:
            self.mpris.shutdown()
        self.now_playing.shutdown()
        self.media.shutdown()

    # player -> common play
    def handle_player_state_update(self, message):
        """
        Handles 'ovos.common_play.player.state' messages with player state updates
        @param message: Message providing new "state" data
        """
        state = message.data.get("state")
        if state is None:
            raise ValueError(f"Got state update message with no state: "
                             f"{message}")
        if isinstance(state, int):
            state = PlayerState(state)
        if not isinstance(state, PlayerState):
            raise ValueError(f"Expected int or PlayerState, but got: {state}")
        if state == self.state:
            return
        LOG.info(f"PlayerState changed: {repr(state)}")
        if state == PlayerState.PLAYING:
            self.state = PlayerState.PLAYING
        elif state == PlayerState.PAUSED:
            self.state = PlayerState.PAUSED
        elif state == PlayerState.STOPPED:
            self.state = PlayerState.STOPPED

        if self.mpris:
            state2str = {PlayerState.PLAYING: "Playing",
                         PlayerState.PAUSED: "Paused",
                         PlayerState.STOPPED: "Stopped"}
            self.mpris.update_props({"CanPause": state == PlayerState.PLAYING,
                                     "CanPlay": state == PlayerState.PAUSED,
                                     "PlaybackStatus": state2str[state]})

    def handle_player_media_update(self, message):
        """
        Handles 'ovos.common_play.media.state' messages with media state updates
        @param message: Message providing new "state" data
        """
        LOG.debug(f"backend={repr(self.active_backend)}|"
                  f"msg_type={message.msg_type}")
        state = message.data.get("state")
        if state is None:
            raise ValueError(f"Got state update message with no state: "
                             f"{message}")
        if isinstance(state, int):
            state = MediaState(state)
        if not isinstance(state, MediaState):
            raise ValueError(f"Expected int or MediaState, but got: {state}")
        if state == self.media_state:
            return
        LOG.debug(f"MediaState changed: {repr(state)}")
        self.media_state = state
        if state == MediaState.END_OF_MEDIA:
            self.handle_playback_ended(message)
        elif state == MediaState.INVALID_MEDIA:
            self.handle_invalid_media(message)
            if self.settings.get("autoplay", True):
                self.play_next()

    def handle_invalid_media(self, message):
        pass

    def handle_playback_ended(self, message):
        # TODO: When we get here, self.active_backend has been reset!
        if self.settings.get("autoplay", True) and \
                self.active_backend != PlaybackType.MPRIS:
            LOG.debug(f"Playing next (backend={repr(self.active_backend)}")
            self.play_next()
            return
        LOG.info("Playback ended")

    # ovos common play bus api requests
    def handle_play_request(self, message):
        LOG.debug("Received external OVOS playback request")
        repeat = message.data.get("repeat", False)
        if repeat:
            self.loop_state = LoopState.REPEAT

        if message.data.get("tracks"):
            # backwards compat / old style
            playlist = disambiguation = message.data["tracks"]
            media = playlist[0]
        else:
            media = message.data.get("media")
            playlist = message.data.get("playlist") or [media]
            disambiguation = message.data.get("disambiguation") or [media]
        self.play_media(media, disambiguation, playlist)

    def handle_pause_request(self, message):
        self.pause()

    def handle_stop_request(self, message):
        self.stop()

    def handle_resume_request(self, message):
        self.resume()

    def handle_seek_request(self, message):
        # from bus api
        miliseconds = message.data.get("seconds", 0) * 1000

        # from audio player GUI
        position = message.data.get("seekValue")
        if not position:
            position = self.now_playing.position or 0
            if self.active_backend in [PlaybackType.AUDIO,
                                       PlaybackType.UNDEFINED]:
                position = self.audio_service.get_track_position() or position
            position += miliseconds
        self.seek(position)

    def handle_next_request(self, message):
        self.play_next()

    def handle_prev_request(self, message):
        self.play_prev()

    def handle_set_shuffle(self, message):
        self.shuffle = True

    def handle_unset_shuffle(self, message):
        self.shuffle = False

    def handle_set_repeat(self, message):
        self.loop_state = LoopState.REPEAT

    def handle_unset_repeat(self, message):
        self.loop_state = LoopState.NONE

    # playlist control bus api
    def handle_repeat_toggle_request(self, message):
        if self.loop_state == LoopState.REPEAT_TRACK:
            self.loop_state = LoopState.NONE
        elif self.loop_state == LoopState.REPEAT:
            self.loop_state = LoopState.REPEAT_TRACK
        elif self.loop_state == LoopState.NONE:
            self.loop_state = LoopState.REPEAT
        LOG.info(f"Repeat: {self.loop_state}")

    def handle_shuffle_toggle_request(self, message):
        self.shuffle = not self.shuffle
        LOG.info(f"Shuffle: {self.shuffle}")

    def handle_playlist_set_request(self, message):
        self.playlist.clear()
        self.handle_playlist_queue_request(message)

    def handle_playlist_queue_request(self, message):
        for track in message.data["tracks"]:
            self.playlist.add_entry(track)

    def handle_playlist_clear_request(self, message):
        self.playlist.clear()
        self.set_media_state(MediaState.NO_MEDIA)

    # audio ducking - NB: we distinguish ducking vs corking  (lower volume vs pause)
    def handle_cork_request(self, message):
        """
        Pause audio on 'recognizer_loop:record_begin'
        @param message: Message associated with event
        """
        if self.state == PlayerState.PLAYING:
            self.pause()
            self._paused_on_duck = True

    def handle_uncork_request(self, message):
        """
        Resume paused audio on 'recognizer_loop:record_begin'
        @param message: Message associated with event
        """
        if self.state == PlayerState.PAUSED and self._paused_on_duck:
            self.resume()
            self._paused_on_duck = False

    def handle_duck_request(self, message):
        """
        Lower volume on 'recognizer_loop:record_begin'
        @param message: Message associated with event
        """
        if self.state == PlayerState.PLAYING:
            if self.active_backend in [PlaybackType.VIDEO]:
                self.video_service._lower_volume()
            elif self.active_backend in [PlaybackType.AUDIO]:
                self.audio_service._lower_volume()
            self._paused_on_duck = True

    def handle_unduck_request(self, message):
        """
        Restore volume on 'recognizer_loop:record_begin'
        @param message: Message associated with event
        """
        if self.state == PlayerState.PAUSED and self._paused_on_duck:
            if self.active_backend in [PlaybackType.VIDEO]:
                self.video_service.restore_volume()
            elif self.active_backend in [PlaybackType.AUDIO]:
                self.audio_service.restore_volume()
            self._paused_on_duck = False

    # track data
    def handle_track_length_request(self, message):
        l = self.now_playing.length
        if self.active_backend == PlaybackType.AUDIO:
            l = self.audio_service.get_track_length() or l
        data = {"length": l}
        self.bus.emit(message.response(data))

    def handle_track_position_request(self, message):
        pos = self.now_playing.position
        if self.active_backend == PlaybackType.AUDIO:
            pos = self.audio_service.get_track_position() or pos
        data = {"position": pos}
        self.bus.emit(message.response(data))

    def handle_set_track_position_request(self, message):
        miliseconds = message.data.get("position")
        self.seek(miliseconds)

    def handle_track_info_request(self, message):
        data = self.now_playing.as_dict
        if self.active_backend == PlaybackType.AUDIO:
            data = self.audio_service.track_info() or data
        self.bus.emit(message.response(data))

    # internal info
    def handle_list_backends_request(self, message):
        data = self.audio_service.available_backends()
        self.bus.emit(message.response(data))
