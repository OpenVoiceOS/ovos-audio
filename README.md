# ovos-audio

`ovos-audio` is the audio daemon for OpenVoiceOS. It handles text-to-speech (TTS) synthesis and sound playback, and it runs as a background service that connects to the OVOS MessageBus.

_________

## Install

```bash
pip install ovos-audio[extras]
```

The `extras` group installs this package with the default plugins. Without it, you must install and configure TTS modules yourself, as described below.

_________

## Configuration

`ovos-audio` reads its settings from `mycroft.conf`.

```javascript
{

  // Text to Speech parameters
  "tts": {
    "module": "ovos-tts-plugin-server",
    "fallback_module": "ovos-tts-plugin-mimic",
    "ovos-tts-plugin-mimic": {
        "voice": "ap"
    }
  },

  // File locations of sounds to play for system events
  "sounds": {
    "start_listening": "snd/start_listening.wav",
    "end_listening": "snd/end_listening.wav",
    "acknowledge": "snd/acknowledge.mp3",
    "error": "snd/error.mp3"
  },

  // Mechanism used to play WAV audio files
  "play_wav_cmdline": "paplay %1 --stream-name=mycroft-voice",

  // Mechanism used to play MP3 audio files
  "play_mp3_cmdline": "mpg123 %1",

  // Mechanism used to play OGG audio files
  "play_ogg_cmdline": "ogg123 -q %1"
}
```
_________

## Persona Support

`ovos-audio` supports dialog-transformer plugins that rewrite generated speech to match a tone or persona. See the [technical manual's dialog transformers page](https://tigregotico.github.io/ovos-technical-manual/dialog-transformers/) for the full transformer chain and priority rules.

For example, [ovos-solver-plugin-openai-persona](https://github.com/OpenVoiceOS/ovos-solver-plugin-openai-persona) rewrites text before synthesis, based on a persona string. Sample personas:

- `"rewrite the text as if you were explaining it to a 5-year-old"`
- `"rewrite the text as if it was an angry old man speaking"`
- `"Add more 'dude'ness to it"`

Example input and output with the "explain to a 5-year-old" persona:

- **Input:** `"Quantum mechanics is a branch of physics that describes the behavior of particles at the smallest scales."`
- **Output:** `"Quantum mechanics is like a special kind of science that helps us understand really tiny things."`

To enable the plugin, add this to `mycroft.conf`:

```json
"dialog_transformers": {
    "ovos-dialog-transformer-openai-plugin": {
        "rewrite_prompt": "rewrite the text as if you were explaining it to a 5-year-old"
    }
}
```

_____

## Using Legacy AudioService

The legacy audio service handles audio playback through the old Mycroft API. See the implementation in [mycroft-core](https://github.com/MycroftAI/mycroft-core/blob/dev/mycroft/skills/audioservice.py) and [ovos-bus-client](https://github.com/OpenVoiceOS/ovos-bus-client/blob/dev/ovos_bus_client/apis/ocp.py).

By default, OCP delegates to the legacy audio service when needed, so no action is required. If you disable OCP, this API becomes the sole media playback provider.

> **Note:** once `ovos-media` is released, OCP and this API will be disabled by default and deprecated.

See [docs/audio-service.md](docs/audio-service.md) for the module reference, and the [technical manual's OCP audio plugin page](https://tigregotico.github.io/ovos-technical-manual/ocp-audio-plugin/) for how OCP relates to this subsystem.

```javascript
{
    "enable_old_audioservice": true,
    "disable_ocp": true,
    "Audio": {
        "default-backend": "vlc",
        "backends": {
          "simple": {
            "type": "ovos_audio_simple",
            "active": true
          },
          "vlc": {
            "type": "ovos_vlc",
            "active": true
          }
        }
    }
  },
}
```

Legacy backend plugins:
- [ovos-vlc-plugin](https://github.com/OpenVoiceOS/ovos-vlc-plugin)
- [ovos-audio-plugin-simple](https://github.com/OpenVoiceOS/ovos-audio-plugin-simple) (no HTTPS support)
- [ovos-audio-plugin-mpv](https://github.com/OpenVoiceOS/ovos-audio-plugin-mpv) (recommended default)
- [ovos-media-plugin-chromecast](https://github.com/OpenVoiceOS/ovos-media-plugin-chromecast)
- [ovos-media-plugin-spotify](https://github.com/OpenVoiceOS/ovos-media-plugin-spotify)

**About OCP:**

- OCP was developed for `mycroft-core` under the legacy audio service system.
- OCP is always the default audio plugin, unless `"disable_ocp": true` is set in the config.
- OCP uses the legacy API internally to delegate playback when the GUI is unavailable, or when configured to do so.
- OCP does not support old Mycroft CommonPlay skills. The `"ocp_legacy"` pipeline in `ovos-core` handles that instead.
- [ovos-media](https://github.com/OpenVoiceOS/ovos-media) will fully replace OCP in `ovos-audio` 1.0.0.

_________

## Related Projects

- [ovos-media](https://github.com/OpenVoiceOS/ovos-media), the replacement for OCP and the legacy audio service
- [ovos-core](https://github.com/OpenVoiceOS/ovos-core), the assistant core that starts and manages `ovos-audio`
- [ovos-plugin-manager](https://github.com/OpenVoiceOS/ovos-plugin-manager), plugin discovery for TTS, G2P, and audio backends
- [ovos-bus-client](https://github.com/OpenVoiceOS/ovos-bus-client), the MessageBus client used to communicate with `ovos-audio`

See [docs/index.md](docs/index.md) for a full architecture overview.

_________

## License

`ovos-audio` is licensed under the [Apache License 2.0](LICENSE).
