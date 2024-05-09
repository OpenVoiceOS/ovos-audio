# ovos-audio

The "mouth" of the OVOS assistant!

Handles TTS generation and sounds playback

## Install

`pip install ovos-audio[extras]` to install this package and the default
plugins.

Without `extras`, you will also need to manually install,
and possibly configure TTS modules as described below.

# Configuration

under mycroft.conf

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

## Using Legacy AudioService

The legacy audio service supports audio playback via the old mycroft api ([@mycroft](https://github.com/MycroftAI/mycroft-core/blob/dev/mycroft/skills/audioservice.py#L43) [@ovos](https://github.com/OpenVoiceOS/ovos-bus-client/blob/dev/ovos_bus_client/apis/ocp.py#L51))

by default OCP acts as a translation layer for this api and no action is needed, but if you want to disable ocp this api remains available

> **NOTE:** once ovos-media is released OCP and this api will be disabled by default and deprecated!

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

legacy plugins:
- [ocp](https://github.com/OpenVoiceOS/ovos-ocp-audio-plugin)
- [vlc](https://github.com/OpenVoiceOS/ovos-vlc-plugin)
- [simple](https://github.com/OpenVoiceOS/ovos-audio-plugin-simple) (no https support)

**OCP technical details:**

- OCP was developed for mycroft-core under this legacy system
- OCP will pose as a legacy plugin and translate the received bus events to the [OCP api](https://github.com/OpenVoiceOS/ovos-bus-client/blob/dev/ovos_bus_client/apis/ocp.py#L228)
- OCP is **always** the default audio plugin, unless you set `"disable_ocp": true` in config
- OCP uses the legacy api internally, to delegate playback when GUI is not available (or configured to do so)
- this does **NOT** bring support for old Mycroft CommonPlay skills, that is related to skills service not ovos-audio
- this brings support for [OCP skills](https://openvoiceos.github.io/ovos-technical-manual/OCP_skills) to OVOS until [ovos-media](https://github.com/OpenVoiceOS/ovos-media) is finished
- [ovos-media](https://github.com/OpenVoiceOS/ovos-media) will fully replace OCP in **ovos-audio 0.2.0**
