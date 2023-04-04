# ovos-audio

The "mouth" of the OVOS assistant!

Handles TTS generation and audio playback

# Configuration

under mycroft.conf

```javascript
{
  // File locations of sounds to play for system events
  "sounds": {
    "start_listening": "snd/start_listening.wav",
    "end_listening": "snd/end_listening.wav",
    "acknowledge": "snd/acknowledge.mp3",
    "error": "snd/error.mp3"
  },

  // Mechanism used to play WAV audio files
  // Override: SYSTEM
  "play_wav_cmdline": "paplay %1 --stream-name=mycroft-voice",

  // Mechanism used to play MP3 audio files
  // Override: SYSTEM
  "play_mp3_cmdline": "mpg123 %1",

  // Mechanism used to play OGG audio files
  // Override: SYSTEM
  "play_ogg_cmdline": "ogg123 -q %1",
  
  "Audio": {
    // message.context may contains a source and destination
    // native audio (playback / TTS) will only be played if a
    // message destination is a native_source or if missing (considered a broadcast)
    "native_sources": ["debug_cli", "audio"],

    "backends": {
      "OCP": {
        "type": "ovos_common_play",
        "active": true
      },
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
```