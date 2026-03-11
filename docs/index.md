
# ovos-audio

`ovos-audio` is the audio daemon for OVOS. It handles all speech output (TTS) and legacy media playback, running as a background service that connects to the OVOS MessageBus.

---

## Responsibilities

- **TTS synthesis**: receives `speak` bus events, runs them through `DialogTransformersService`, synthesizes audio via the configured TTS plugin, and queues it for playback
- **TTS playback**: `PlaybackThread` dequeues synthesized audio, runs it through `TTSTransformersService`, plays it, and fires lifecycle bus events (start/end of speech, listen trigger)
- **Fallback TTS**: if the primary TTS plugin fails, falls back to a separately configured plugin
- **Legacy audio service**: optionally loads `AudioService` backends (VLC, MPV, etc.) for media playback via `mycroft.audio.service.*` bus events
- **Plugin introspection**: responds to `opm.tts.query` and `opm.g2p.query` with installed plugin metadata for external UIs

---

## Architecture

```
MessageBus
    │
    ▼
PlaybackService (Thread)
    ├── DialogTransformersService   ← rewrites dialog text before TTS
    ├── TTSFactory → TTS plugin     ← synthesizes audio
    ├── PlaybackThread (Thread)
    │       └── TTSTransformersService  ← post-processes wav files
    └── AudioService (optional, legacy)
            └── AudioBackend plugins (VLC, MPV, ...)
```

---

## Navigation

| Document | Contents |
|---|---|
| [playback-service.md](playback-service.md) | `PlaybackService` — main daemon, TTS lifecycle, fallback, bus events |
| [tts.md](tts.md) | `TTSFactory`, `PlaybackThread` — synthesis queue and playback lifecycle |
| [audio-service.md](audio-service.md) | `AudioService` — legacy audio backends, playback control, audio ducking |
| [transformers.md](transformers.md) | `DialogTransformersService`, `TTSTransformersService` — plugin pipeline |

---

## Quick Start

The service is normally started by `ovos-core` or run standalone:

```bash
ovos-audio
```

Or in Python:

```python
from ovos_audio.service import PlaybackService

service = PlaybackService()
service.start()
service.join()
```

---

## Package Layout

```
ovos_audio/
├── service.py       # PlaybackService — main daemon class
├── tts.py           # TTSFactory wrapper
├── playback.py      # PlaybackThread — dequeue and play TTS audio
├── audio.py         # AudioService — legacy audio backend manager
├── transformers.py  # DialogTransformersService, TTSTransformersService
├── utils.py         # require_default_session decorator, report_timing
└── __main__.py      # Entry point: ovos-audio CLI
```

---

## Configuration

All configuration is read from `mycroft.conf` via `ovos-config`.

| Key | Default | Description |
|---|---|---|
| `tts.module` | — | TTS plugin entry point name |
| `tts.fallback_module` | — | Fallback TTS plugin if primary fails |
| `tts.preload_fallback` | `true` | Load fallback TTS eagerly at startup |
| `tts.pulse_duck` | `false` | Use PulseAudio modules for audio ducking instead of bus events |
| `tts.ocp_cork` | `false` | Cork (pause) OCP media during speech |
| `tts.ocp_duck` | `false` | Duck (lower volume) OCP media during speech |
| `enable_old_audioservice` | `true` | Enable legacy `AudioService` backends |
| `disable_ocp` | `false` | Disable built-in OCP backend inside `AudioService` |
| `g2p.module` | — | Grapheme-to-Phoneme plugin for mouth/viseme animations |
| `dialog_transformers` | `{}` | Dialog transformer plugin configs |
| `tts_transformers` | `{}` | TTS (wav) transformer plugin configs |
| `Audio.default-backend` | — | Preferred legacy audio backend name |
| `Audio.backends` | `{}` | Legacy audio backend configs |
