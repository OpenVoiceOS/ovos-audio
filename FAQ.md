
# FAQ — `ovos-audio`

## How do I run E2E tests for ovos-audio?

End-to-end tests live in `test/end2end/` and use `ovoscope.audio` harnesses:

```bash
uv run --active pytest test/end2end/ -v --timeout=60
```

Four test modules:
- `test_audio_service_e2e.py` — 11 tests for `AudioService` (backend selection,
  ducking, stop guard, session validation)
- `test_playback_service_e2e.py` — 7 tests for `PlaybackService` (TTS synthesis,
  speak lifecycle events, opm.tts.query, speak status)
- `test_audio_service_extended_e2e.py` — 13 extended tests for `AudioService`
  (volume ducking, restore-on-handled, stop guard, position/length bus roundtrip,
  seek, track_start callback, `AudioCaptureSession`, shutdown isolation)
- `test_playback_service_extended_e2e.py` — 14 extended tests for `PlaybackService`
  (b64_audio, languages/tts, instant play WAV + binary, G2P query, session
  validation, speak+ident, `AudioCaptureSession` TTS lifecycle, speak after stop)

No real audio hardware or TTS engine required — `MockAudioBackend` and `MockTTS`
from `ovoscope[audio]` are used. See `ovoscope/docs/audio-testing.md` for
harness API reference.

## What is `ovos-audio`?
`ovos-audio` is ovos-core audio daemon client.

## How do I install it?
```bash
pip install ovos-audio
```
Or for development:
```bash
uv pip install -e ovos-audio/
```

## Where do I report bugs?
Open an issue on the GitHub repository. Ensure you are targeting the `dev` branch for fixes.

## How do I run tests?
```bash
uv run pytest ovos-audio/test/ --cov=ovos_audio
```

## How do I contribute?
1. Fork the repository and create a feature branch from `dev`.
2. Write tests for your changes.
3. Open a PR targeting the `dev` branch.
4. Ensure CI passes before requesting review.

## What Python versions are supported?
See `QUICK_FACTS.md` — currently `>=3.9`.
