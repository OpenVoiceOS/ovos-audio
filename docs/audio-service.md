# AudioService (Legacy)

**Module:** `ovos_audio.audio.AudioService`

> **Deprecation notice:** `AudioService` and its backend plugin system are being superseded by `ovos-media`. New deployments should migrate to `ovos-media`. The legacy audio service can be disabled with `"enable_old_audioservice": false` in `mycroft.conf`.

`AudioService` manages a set of audio playback backend plugins (e.g. VLC, MPV) and exposes media playback control over the MessageBus via the `mycroft.audio.service.*` event namespace.

---

## Constructor

```python
AudioService(bus, autoload=True, disable_ocp=False, validate_source=True)
```

| Parameter | Description |
|---|---|
| `bus` | `MessageBusClient` instance |
| `autoload` | If `True`, call `load_services()` immediately |
| `disable_ocp` | Skip loading the `OCPAudioBackend` (classic OCP) |
| `validate_source` | Only handle events from `session_id == "default"` |

Config is read from `mycroft.conf` at `["Audio"]`.

---

## Backend Loading

`load_services()` uses `ovos-plugin-manager` to discover installed audio backend plugins:

```python
from ovos_plugin_manager.audio import find_audio_service_plugins, setup_audio_service
```

1. All discovered plugins except `ovos_common_play` are instantiated
2. Local backends are listed before remote backends
3. OCP (`OCPAudioBackend` from `ovos-plugin-common-play`) is loaded separately if not disabled
4. The default backend is selected by matching `Audio.default-backend` config key against service names

Backend plugins must implement `ovos_plugin_manager.templates.audio.AudioBackend` or `RemoteAudioBackend`.

### Stream Extraction

Before playback, tracks are passed through `load_stream_extractors()` (from `ovos-plugin-manager`) which converts URLs (e.g. YouTube) into direct playable stream URIs.

---

## Playback Control

### `play(tracks, prefered_service, repeat)`

Selects a backend based on URI scheme priority and starts playback:

1. Stop any current playback
2. Run tracks through stream extractors
3. Select backend: preferred → default → first match by URI scheme
4. If no backend supports the URI, emit `ovos.common_play.media.state` with `INVALID_MEDIA`

Track format:
- `str` URI: `"https://example.com/song.mp3"`
- `(uri, mime_type)` tuple: `("https://example.com/song.mp3", "audio/mpeg")`

---

## Audio Ducking

`AudioService` automatically lowers playback volume during speech and microphone recording, then restores it afterward.

| Bus Event | Action |
|---|---|
| `ovos.audio.output.started` | Lower volume (TTS speaking) |
| `ovos.audio.output.ended` | Restore volume |
| `recognizer_loop:record_begin` | Lower volume (mic active) |
| `recognizer_loop:record_end` | Restore volume (with 8 s speech-detection grace period) |
| `ovos.utterance.handled` | Restore volume if not currently speaking |

---

## Bus Events Handled

| Event | Description |
|---|---|
| `mycroft.audio.service.play` | Start playback of a track list |
| `mycroft.audio.service.queue` | Add tracks to current playlist (or start if nothing playing) |
| `mycroft.audio.service.pause` | Pause current backend |
| `mycroft.audio.service.resume` | Resume paused backend |
| `mycroft.audio.service.stop` | Stop playback |
| `ovos.stop` | Stop playback on the universal stop broadcast (OVOS-STOP-1 §5.3) |
| `mycroft.audio.service.next` | Skip to next track |
| `mycroft.audio.service.prev` | Skip to previous track |
| `mycroft.audio.service.track_info` | Reply with current track metadata |
| `mycroft.audio.service.list_backends` | Reply with dict of loaded backends |
| `mycroft.audio.service.get_track_position` | Reply with `{"position": ms}` |
| `mycroft.audio.service.set_track_position` | Seek to position in ms |
| `mycroft.audio.service.get_track_length` | Reply with `{"length": ms}` |
| `mycroft.audio.service.seek_forward` | Seek forward by `seconds` |
| `mycroft.audio.service.seek_backward` | Seek backward by `seconds` |

## Bus Events Emitted

| Event | When |
|---|---|
| `mycroft.audio.playing_track` | A new track begins playing |
| `mycroft.audio.queue_end` | Last track in queue finishes |
| `mycroft.stop.handled` | After a stop request completes |
| `ovos.common_play.media.state` | When no backend can play a URI (`INVALID_MEDIA` state) |

---

## Configuration

```json
{
  "enable_old_audioservice": true,
  "disable_ocp": false,
  "Audio": {
    "default-backend": "vlc",
    "backends": {
      "OCP": {},
      "vlc": {"active": true}
    }
  }
}
```

| Key | Default | Description |
|---|---|---|
| `enable_old_audioservice` | `true` | Enable legacy AudioService (will default to `false` in future) |
| `disable_ocp` | `false` | Disable the OCP backend within AudioService |
| `Audio.default-backend` | `""` | Preferred backend name |
| `Audio.backends` | `{}` | Per-backend configuration dicts |

---

## `wait_for_load(timeout)`

```python
ready = audio_service.wait_for_load(timeout=180)
```

Blocks until all backend plugins have been loaded. Returns `True` if loading completed within the timeout.

---
[← tts.md](tts.md) · [Home](index.md) · [transformers.md →](transformers.md)
