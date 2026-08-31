# TTS and PlaybackThread

---

## TTSFactory

**Module:** `ovos_audio.tts.TTSFactory`

Thin wrapper around `OVOSTTSFactory` from `ovos-plugin-manager`.

```python
from ovos_audio.tts import TTSFactory

tts = TTSFactory.create()          # reads config from mycroft.conf
tts = TTSFactory.create(config)    # use a specific config dict
```

`TTSFactory.create()` resolves `config["tts"]["module"]` to an installed TTS plugin entry point and instantiates it. The returned object is a `TTS` instance from `ovos_plugin_manager.templates.tts`.

After creation, the TTS must be initialised with the bus and playback thread:

```python
tts.init(bus, playback_thread)
```

---

## PlaybackThread

**Module:** `ovos_audio.playback.PlaybackThread`

A daemon `Thread` that consumes entries from `TTS.queue` (a `Queue`) and plays them sequentially. All TTS output and queued sounds pass through this thread to ensure they never overlap.

### Queue Entry Format

```python
(audio_path: str, visemes: list, listen: bool, tts_id: str, message: Message)
```

- `audio_path`: path to the synthesized WAV/MP3 file
- `visemes`: list of `(phoneme, timestamp)` pairs for mouth animation. `None` if unavailable
- `listen`: `True` if the microphone should be activated after playback
- `tts_id`: identifier of the TTS plugin that produced the audio. `"sounds"` for queued sound files
- `message`: originating `speak` message for context forwarding

### Lifecycle

```
PlaybackThread.run()
  └── loop:
        dequeue entry → _play()
            ├── on_start()         → begin_audio()  → emit recognizer_loop:audio_output_start
            ├── TTSTransformersService.transform()   (post-process wav)
            ├── emit recognizer_loop:utterance_start
            ├── play_audio(path)   (subprocess via ovos_utils.sound)
            ├── show_visemes()     (if enclosure set)
            └── on_end(listen)     → end_audio()    → emit recognizer_loop:audio_output_end
                                                     → emit mycroft.mic.listen  (if listen=True)
```

### OCP Integration

When `tts.ocp_cork` or `tts.ocp_duck` is set in config, `begin_audio()` and `end_audio()` emit the corresponding OCP control events:

| Config key | `begin_audio` emits | `end_audio` emits |
|---|---|---|
| `ocp_cork: true` | `ovos.common_play.cork` | `ovos.common_play.uncork` |
| `ocp_duck: true` | `ovos.common_play.duck` | `ovos.common_play.unduck` |

If `pulse_duck: true`, no bus events are emitted. Ducking is handled at the OS PulseAudio level.

### G2P Integration

If a G2P (Grapheme-to-Phoneme) plugin is configured (`g2p.module` in `mycroft.conf`), `PlaybackThread` loads it at startup. When viseme data is not provided by the TTS plugin, the G2P plugin generates visemes from the utterance text for mouth animations.

```json
{
  "g2p": {
    "module": "ovos-g2p-plugin-mimic"
  }
}
```

### Key Methods

| Method | Description |
|---|---|
| `set_bus(bus)` | Attach a bus instance (also propagated to `TTSTransformersService`) |
| `clear_queue()` | Drain the queue and terminate any playing subprocess |
| `clear()` | Alias for `clear_queue()` |
| `pause()` | Stop current playback and block the queue |

| Method | Description |
|---|---|
| `resume()` | Resume a paused playback |
| `stop()` | Terminate thread and clear queue |
| `shutdown()` | Alias for `stop()` |
| `show_visemes(pairs)` | Send viseme data to enclosure (if enclosure is set) |

### Properties

| Property | Type | Description |
|---|---|---|
| `is_running` | `bool` | True if started and not terminated |
| `_now_playing` | `tuple \| None` | The currently dequeued entry |

---

## Bus Events Emitted by PlaybackThread

| Event | When |
|---|---|
| `recognizer_loop:audio_output_start` | Playback of a batch of queued audio begins |
| `recognizer_loop:audio_output_end` | Playback of a batch of queued audio ends |
| `recognizer_loop:utterance_start` | Each individual utterance starts playing |
| `mycroft.mic.listen` | After speech ends when `listen=True` |

| Event | When |
|---|---|
| `ovos.common_play.cork` | Before speech if `ocp_cork=True` |
| `ovos.common_play.uncork` | After speech if `ocp_cork=True` |
| `ovos.common_play.duck` | Before speech if `ocp_duck=True` |
| `ovos.common_play.unduck` | After speech if `ocp_duck=True` |

---
[← playback-service.md](playback-service.md) · [Home](index.md) · [audio-service.md →](audio-service.md)
