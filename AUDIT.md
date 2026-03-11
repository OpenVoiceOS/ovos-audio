
# ovos-audio — Audit Report

## Documentation Status
- [ ] AGENTS.md Header Format
- [ ] QUICK_FACTS.md (Moved from docs/)
- [ ] FAQ.md (Moved from docs/)
- [ ] MAINTENANCE_REPORT.md
- [x] AUDIT.md
- [ ] SUGGESTIONS.md
- [x] docs/index.md

## E2E Coverage Status (2026-03-10)
- **Added**: `test/end2end/test_audio_service_e2e.py` — 11 tests covering `AudioService`
  (`ovos_audio/audio.py:63`): play, pause, resume, stop, queue, track_info, list_backends,
  audio ducking, session validation
- **Added**: `test/end2end/test_playback_service_e2e.py` — 7 tests covering `PlaybackService`
  (`ovos_audio/service.py:55`): speak, expect_response, stop, queue_sound, opm.tts.query,
  speak_status, multiple speaks
- Uses `ovoscope.audio.AudioServiceHarness` and `PlaybackServiceHarness` — no real hardware

## Technical Debt & Issues
- **Transitional Architecture**: Currently in a transitional state between the legacy OCP (OpenVoiceOS Common Play) system and the upcoming `ovos-media` stack.
- **Legacy Support**: Maintains significant code for legacy audio service support, which is deprecated but still default in some configurations.
- **Dependency Pining**: Dependencies in `pyproject.toml` use loose upper bounds (e.g., `<3.0.0`), which might lead to breaking changes if sub-dependencies don't follow semver strictly.
- **Dynamic Versioning**: Uses `ovos_audio.version` for dynamic versioning, which is standard but requires manual updates to `version.py`.

## Next Steps
- Migrate standard documentation files (`QUICK_FACTS.md`, `FAQ.md`) from `docs/` to the root directory.
- Prepare for the transition to `ovos-media` by identifying and isolating OCP-specific logic.
- Add `MAINTENANCE_REPORT.md` to track technical debt related to legacy audio backends.
