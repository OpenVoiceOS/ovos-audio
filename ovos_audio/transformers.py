from typing import Optional

from ovos_config import Configuration
from ovos_plugin_manager.dialog_transformers import find_dialog_transformer_plugins
from ovos_plugin_manager.transformer_services import (
    DialogTransformersService as _DialogTransformersService,
    TTSTransformersService as _TTSTransformersService)
from ovos_plugin_manager.tts_transformers import find_tts_transformer_plugins


def _stage_config(config: Optional[dict], section: str) -> dict:
    """The configuration for one transformer stage.

    The plugin manager accepts either a whole core configuration or the
    stage's own section, and cannot tell them apart when the whole
    configuration does not carry the section: every top-level key then reads
    as an enabled plugin, and the loader warns once per key that the plugin
    is not installed. Neither of this module's sections ships in the default
    configuration, so reading the section here is what keeps an ordinary
    boot quiet.

    An explicit ``config`` is returned untouched, because a caller that
    supplies one has already named the mapping it wants used.
    """
    if config is not None:
        return config
    return Configuration().get(section) or {}


class DialogTransformersService(_DialogTransformersService):
    """Transforms dialogs before being sent to TTS, in OVOS-TRANSFORM §4
    ascending priority order: a plugin of priority 1 runs first."""

    def __init__(self, bus, config: Optional[dict] = None):
        super().__init__(bus=bus,
                         config=_stage_config(config, self.config_section))

    @classmethod
    def find_plugins(cls):
        return find_dialog_transformer_plugins().items()


class TTSTransformersService(_TTSTransformersService):
    """Transforms wav_files after TTS, in OVOS-TRANSFORM §4 ascending
    priority order: a plugin of priority 1 runs first."""

    def __init__(self, bus=None, config: Optional[dict] = None):
        super().__init__(bus=bus,
                         config=_stage_config(config, self.config_section))

    @classmethod
    def find_plugins(cls):
        return find_tts_transformer_plugins().items()
