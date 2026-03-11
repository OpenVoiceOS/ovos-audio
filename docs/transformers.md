# Transformer Services

`ovos-audio` runs two transformer pipelines around TTS synthesis:

```
speak event
    │
    ▼
DialogTransformersService    ← rewrite text before sending to TTS
    │
    ▼
TTS plugin (synthesis)
    │
    ▼
TTSTransformersService       ← post-process wav file after synthesis
    │
    ▼
PlaybackThread (play audio)
```

---

## DialogTransformersService

**Module:** `ovos_audio.transformers.DialogTransformersService`

Rewrites dialog text before it is sent to the TTS engine. Examples of use: pronunciation corrections, language-specific rewrites, censoring.

```python
from ovos_audio.transformers import DialogTransformersService

svc = DialogTransformersService(bus)
transformed_text, context = svc.transform(dialog="Hello world", context=msg.context)
```

### Plugin Entry Point

Entry point group: `opm.dialog_transformer` (via `ovos-plugin-manager`).

Plugins are enabled by adding their entry point name to `mycroft.conf`:

```json
{
  "dialog_transformers": {
    "ovos-dialog-transformer-example": {
      "active": true,
      "priority": 50
    }
  }
}
```

Only plugins with a config entry are loaded. A plugin with `"active": false` is skipped.

### Priority Ordering

Plugins are called in descending priority order (highest number first). A plugin with higher priority runs first and its output is the input to the next plugin.

Priority `1` is the **last** to run and has the final say on the output.

### Blacklisted Skills

Dialog from certain skills is never transformed. The default blacklist:

```python
["skill-ovos-icanhazdadjokes.openvoiceos"]
```

Configurable via `dialog_transformers.blacklisted_skills`.

### `transform(dialog, context, sess)`

```python
dialog, context = svc.transform(dialog, context=context, sess=session)
# Returns (rewritten_text, updated_context)
```

---

## TTSTransformersService

**Module:** `ovos_audio.transformers.TTSTransformersService`

Post-processes the synthesized WAV file after TTS output and before playback. Examples of use: audio normalization, speed adjustment, noise reduction.

```python
from ovos_audio.transformers import TTSTransformersService

svc = TTSTransformersService(bus)
wav_path, context = svc.transform(wav_file="/tmp/speech.wav", context=msg.context)
```

### Plugin Entry Point

Entry point group: `opm.tts_transformer` (via `ovos-plugin-manager`).

Enabled the same way as dialog transformers:

```json
{
  "tts_transformers": {
    "ovos-tts-transformer-example": {
      "active": true,
      "priority": 50
    }
  }
}
```

### Priority Ordering

Same as `DialogTransformersService`: descending by priority, with `1` running last.

### `transform(wav_file, context, sess)`

```python
wav_path, context = svc.transform(wav_file, context=context, sess=session)
# Returns (path_to_transformed_wav, updated_context)
```

The returned path may differ from the input if the plugin produces a new file.

### `set_bus(bus)`

Used by `PlaybackThread` to attach the bus after the thread starts, since `TTSTransformersService` may be created before the bus is ready.

---

## Common Behaviour

Both services share the same pattern:

| Behaviour | Detail |
|---|---|
| Plugin discovery | `find_dialog_transformer_plugins()` / `find_tts_transformer_plugins()` from `ovos-plugin-manager` |
| Activation | Config key must exist; `"active": false` disables |
| Priority | Higher number → runs first |
| Error handling | Exceptions in individual plugins are logged and skipped |
| Shutdown | `shutdown()` calls `module.shutdown()` on each loaded plugin |
