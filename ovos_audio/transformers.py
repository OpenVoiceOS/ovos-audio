from ovos_plugin_manager.dialog_transformers import find_dialog_transformer_plugins
from ovos_utils.json_helper import merge_dict
from ovos_utils.log import LOG
from ovos_bus_client.session import Session, SessionManager


class DialogTransformersService:
    """ transform dialogs before being sent to TTS """
    def __init__(self, bus, config=None):
        self.loaded_plugins = {}
        self.has_loaded = False
        self.bus = bus
        # to activate a plugin, just add an entry to mycroft.conf for it
        self.config = config or Configuration().get("dialog_transformers", {})
        self.load_plugins()

    def load_plugins(self):
        for plug_name, plug in find_dialog_transformer_plugins().items():
            if plug_name in self.config:
                # if disabled skip it
                if not self.config[plug_name].get("active", True):
                    continue
                try:
                    self.loaded_plugins[plug_name] = plug()
                    self.loaded_plugins[plug_name].bind(self.bus)
                    LOG.info(f"loaded audio transformer plugin: {plug_name}")
                except Exception as e:
                    LOG.exception(f"Failed to load audio transformer plugin: "
                                  f"{plug_name}")
        self.has_loaded = True

    @property
    def plugins(self) -> list:
        """
        Return loaded transformers in priority order, such that modules with a
        higher `priority` rank are called first and changes from lower ranked
        transformers are applied last.

        A plugin of `priority` 1 will override any existing context keys and
        will be the last to modify `audio_data`
        """
        return sorted(self.loaded_plugins.values(),
                      key=lambda k: k.priority, reverse=True)

    def shutdown(self):
        """
        Shutdown all loaded plugins
        """
        for module in self.plugins:
            try:
                module.shutdown()
            except Exception as e:
                LOG.warning(e)

    def transform(self, dialog: str, session: Session= None) -> str:
        """
        Get transformed audio and context for the preceding audio
        @param dialog: str to be spoken
        @return: transformed dialog to be sent to TTS
        """
        session = session or SessionManager.get()

        # TODO property not yet introduced in Session
        # this will be set per Session/Persona
        # active_transformers = session.dialog_transformers or self.plugins
        active_transformers = self.plugins

        for module in active_transformers:
            try:
                LOG.debug(f"checking dialog transformer: {module}")
                dialog = module.transform(dialog)
                LOG.debug(f"{module.name}: {dialog}")
            except Exception as e:
                LOG.exception(e)
        return dialog
