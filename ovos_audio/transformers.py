from typing import Optional

from ovos_config import Configuration
from ovos_plugin_manager.dialog_transformers import find_dialog_transformer_plugins
from ovos_plugin_manager.transformer_services import (
    DialogTransformersService as _DialogTransformersService,
    TTSTransformersService as _TTSTransformersService)
from ovos_plugin_manager.tts_transformers import find_tts_transformer_plugins


class DialogTransformersService(_DialogTransformersService):
    """Transforms dialogs before being sent to TTS, in OVOS-TRANSFORM §4
    ascending priority order: a plugin of priority 1 runs first."""

    def __init__(self, bus, config: Optional[dict] = None):
        config = config or Configuration()
        super().__init__(bus=bus, config=config)

    @classmethod
    def find_plugins(cls):
        return find_dialog_transformer_plugins().items()


class TTSTransformersService(_TTSTransformersService):
    """Transforms wav_files after TTS, in OVOS-TRANSFORM §4 ascending
    priority order: a plugin of priority 1 runs first."""

    def __init__(self, bus=None, config: Optional[dict] = None):
        config = config or Configuration()
        super().__init__(bus=bus, config=config)

    @classmethod
    def find_plugins(cls):
        return find_tts_transformer_plugins().items()
