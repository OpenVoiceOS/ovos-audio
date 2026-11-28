# Dropping the in-process OCP audio backend

The legacy `AudioService` no longer loads OCP itself. The classic OCP audio backend
(`ovos_plugin_common_play.OCPAudioBackend`) and everything that wired it in are removed:

- `AudioService.find_ocp()`, the `self.ocp` attribute, and the `disable_ocp` flag /
  constructor argument are gone.
- The legacy `MediaState` import fallback is dropped — `ovos_utils.ocp.MediaState` is now
  required directly.
- `ovos_plugin_common_play` is removed from the requirements.

`AudioService` is now strictly the legacy media-backend host (VLC, MPV, …) driven by the
`mycroft.audio.service.*` bus API. It no longer owns OCP playback.

## Spec conformance

Aligns with **OVOS-OCP-1**. OCP search and playback move out of `ovos-audio`'s in-process
audio service: discovery is handled by `MediaProvider` plugins
(`opm.media.provider`, queried in-process by the OCP pipeline, replacing the old OCP search
skills) rather than the bundled `OCPAudioBackend`. `ovos-audio` retains only TTS output and
the legacy `mycroft.audio.service.*` backends.
