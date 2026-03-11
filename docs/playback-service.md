# PlaybackService

**Module:** `ovos_audio.service.PlaybackService`

`PlaybackService` is the top-level daemon for `ovos-audio`. It is a `Thread` subclass that:

1. Initialises the TTS plugin and optionally the fallback TTS
2. Starts the `PlaybackThread` for queued audio output
3. Initialises `DialogTransformersService` for pre-TTS text rewriting
4. Optionally starts the legacy `AudioService` for media playback backends
5. Registers all bus event handlers

---

## Constructor

```python
PlaybackService(
    ready_hook=on_ready,
    error_hook=on_error,
    stopping_hook=on_stopping,
    alive_hook=on_alive,
    started_hook=on_started,
    watchdog=lambda: None,
    bus=None,
    disable_ocp=None,
    validate_source=True,
    tts=None,
    disable_fallback=False
)
```

| Parameter | Description |
|---|---|
| `bus` | `MessageBusClient` instance; created automatically if `None` |
| `disable_ocp` | Disable OCP inside `AudioService`; reads `disable_ocp` from config if `None` |
| `validate_source` | If `True`, only handle audio from sessions with `session_id == "default"` (local mic only) |
| `tts` | Pre-created `TTS` instance; if provided, auto-reload on config change is disabled |
| `disable_fallback` | If `True`, never load or use the fallback TTS plugin |

`ProcessStatus` lifecycle hook parameters (`ready_hook`, etc.) follow the standard OVOS process status pattern.

---

## TTS Loading and Reload

On startup, `_maybe_reload_tts()` is called to load the configured TTS plugin. It is also registered as a config watcher so it fires whenever `mycroft.conf` changes.

```python
# In mycroft.conf
{
  "tts": {
    "module": "ovos-tts-plugin-mimic3",
    "ovos-tts-plugin-mimic3": { ... },
    "fallback_module": "ovos-tts-plugin-server",
    "preload_fallback": true
  }
}
```

Reload happens only when the config hash for the plugin's section changes. The old TTS instance is shut down before the new one is created.

---

## Fallback TTS

If the primary TTS plugin raises an exception during `execute_tts()`, `execute_fallback_tts()` is called.

The fallback TTS is:
- Loaded at startup if `preload_fallback: true` (default) and `fallback_module` is set
- Lazy-loaded on first failure otherwise
- Skipped if `disable_fallback=True` or if `fallback_module` equals `module`

---

## Key Methods

### `handle_speak(message)`

Handles the `speak` bus event. Flow:

1. Acquire `playback_lock`
2. Extract `utterance` and `session` from the message
3. Run `DialogTransformersService.transform()` to optionally rewrite the text
4. Call `execute_tts(utterance, session_id, listen, message)`
5. Report timing metrics

### `execute_tts(utterance, ident, listen, message)`

Calls `tts.execute()` with the utterance. On failure, falls back to `execute_fallback_tts()`.

### `handle_queue_audio(message)`

Queues a sound file or binary audio blob for playback in the TTS thread (serialised with speech). Accepts:
- `uri` — file path or resource URI
- `binary_data` — hex-encoded byte string with optional `audio_ext`

### `handle_instant_play(message)`

Plays a sound immediately, bypassing the TTS queue. Supports optional volume-restore logic via `force_unmute`.

### `handle_b64_audio(message)`

Synthesizes an utterance and returns the audio base64-encoded on the bus instead of playing it. Useful for remote TTS integrations.

### `handle_stop(message)`

Clears the `PlaybackThread` queue on `mycroft.stop`.

---

## `@require_default_session()`

A decorator defined in `ovos_audio.utils` that guards bus handlers: if `validate_source=True`, only messages from `session_id == "default"` (the local mic) are processed. Messages from remote satellites or HiveMind nodes are silently ignored.

---

## ProcessStatus

`PlaybackService` uses `ProcessStatus('audio', ...)` to track and broadcast its lifecycle state. Transitions:

| State | When |
|---|---|
| `started` | Constructor finished |
| `alive` | `run()` called |
| `ready` | TTS is loaded |
| `error` | TTS failed to load |
| `stopping` | `shutdown()` called |

---

## Bus Events Handled

| Event | Handler | Description |
|---|---|---|
| `speak` | `handle_speak` | Synthesize and play TTS |
| `speak:b64_audio` | `handle_b64_audio` | Synthesize and return as base64 |
| `mycroft.stop` | `handle_stop` | Stop current TTS playback |
| `mycroft.audio.speech.stop` | `handle_stop` | Stop current TTS playback |
| `mycroft.audio.speak.status` | `handle_speak_status` | Reply with `{"speaking": bool}` |
| `mycroft.audio.queue` | `handle_queue_audio` | Queue sound file in TTS thread |
| `mycroft.audio.play_sound` | `handle_instant_play` | Play sound immediately |
| `ovos.languages.tts` | `handle_get_languages_tts` | Reply with supported TTS languages |
| `opm.tts.query` | `handle_opm_tts_query` | Reply with TTS plugin metadata |
| `opm.g2p.query` | `handle_opm_g2p_query` | Reply with G2P plugin metadata |
| `opm.audio.query` | `handle_opm_audio_query` | Deprecated; returns empty response |

## Bus Events Emitted

| Event | When |
|---|---|
| `mycroft.stop.handled` | After TTS queue is cleared on stop |
| `mycroft.audio.is_speaking` | In reply to `mycroft.audio.speak.status` |
