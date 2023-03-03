from ovos_config.config import Configuration
from ovos_plugin_manager.tts import OVOSTTSFactory


class TTSFactory(OVOSTTSFactory):
    @staticmethod
    def create(config=None):
        config = config or Configuration()
        return OVOSTTSFactory.create(config)
