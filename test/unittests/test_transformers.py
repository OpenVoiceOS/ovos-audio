"""Unit tests for DialogTransformersService and TTSTransformersService.

Covers:
- Construction with no configured plugins (default/empty config)
- load_plugins() with a disabled plugin entry
- load_plugins() with a plugin that raises during instantiation
- blacklisted_skills property default
- plugins property (sorted list)
- shutdown() happy path and with exception
- transform() with no plugins (identity)
- transform() with a single plugin
- set_bus() propagation in TTSTransformersService
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestDialogTransformersServiceInit(unittest.TestCase):
    """DialogTransformersService instantiation with no plugins configured."""

    def _make(self, config=None):
        from ovos_audio.transformers import DialogTransformersService
        return DialogTransformersService(bus=MagicMock(), config=config or {})

    def test_init_empty_config(self):
        svc = self._make()
        self.assertTrue(svc.has_loaded)
        self.assertEqual(svc.loaded_plugins, {})

    def test_blacklisted_skills_default_contains_jokes(self):
        svc = self._make()
        bl = svc.blacklisted_skills
        self.assertIsInstance(bl, list)
        self.assertTrue(any("joke" in s for s in bl))

    def test_blacklisted_skills_custom(self):
        svc = self._make(config={"blacklisted_skills": ["my-skill"]})
        self.assertEqual(svc.blacklisted_skills, ["my-skill"])

    def test_plugins_empty_when_no_plugins_loaded(self):
        svc = self._make()
        self.assertEqual(svc.plugins, [])

    def test_transform_identity_no_plugins(self):
        svc = self._make()
        dialog, ctx = svc.transform("hello world", context={"key": "val"})
        self.assertEqual(dialog, "hello world")
        self.assertEqual(ctx, {"key": "val"})

    def test_transform_returns_none_context_when_none_passed(self):
        svc = self._make()
        dialog, ctx = svc.transform("test")
        self.assertEqual(dialog, "test")
        self.assertIsNone(ctx)

    def test_shutdown_no_plugins(self):
        svc = self._make()
        # Should not raise
        svc.shutdown()


class TestDialogTransformersLoadPlugins(unittest.TestCase):
    """load_plugins() edge cases."""

    def test_disabled_plugin_not_loaded(self):
        """Plugin with active=False must be skipped."""
        from ovos_audio.transformers import DialogTransformersService
        config = {"my.plugin": {"active": False}}
        fake_plugin_class = MagicMock()
        with patch("ovos_audio.transformers.find_dialog_transformer_plugins",
                   return_value={"my.plugin": fake_plugin_class}):
            svc = DialogTransformersService(bus=MagicMock(), config=config)
        self.assertNotIn("my.plugin", svc.loaded_plugins)
        fake_plugin_class.assert_not_called()

    def test_plugin_load_exception_logged_not_raised(self):
        """A plugin that raises during __init__ must not propagate the error."""
        from ovos_audio.transformers import DialogTransformersService
        config = {"bad.plugin": {"active": True}}
        bad_plugin = MagicMock(side_effect=RuntimeError("boom"))
        with patch("ovos_audio.transformers.find_dialog_transformer_plugins",
                   return_value={"bad.plugin": bad_plugin}):
            svc = DialogTransformersService(bus=MagicMock(), config=config)
        self.assertNotIn("bad.plugin", svc.loaded_plugins)
        self.assertTrue(svc.has_loaded)

    def test_plugin_loaded_when_active(self):
        """A valid active plugin must appear in loaded_plugins."""
        from ovos_audio.transformers import DialogTransformersService
        config = {"good.plugin": {"active": True}}
        mock_instance = MagicMock()
        mock_instance.priority = 50
        good_plugin = MagicMock(return_value=mock_instance)
        with patch("ovos_audio.transformers.find_dialog_transformer_plugins",
                   return_value={"good.plugin": good_plugin}):
            svc = DialogTransformersService(bus=MagicMock(), config=config)
        self.assertIn("good.plugin", svc.loaded_plugins)


class TestDialogTransformersTransform(unittest.TestCase):
    """transform() with active plugins."""

    def _make_with_plugin(self, transform_fn):
        from ovos_audio.transformers import DialogTransformersService
        config = {"p": {"active": True}}
        mock_instance = MagicMock()
        mock_instance.priority = 50
        mock_instance.transform = transform_fn
        mock_class = MagicMock(return_value=mock_instance)
        with patch("ovos_audio.transformers.find_dialog_transformer_plugins",
                   return_value={"p": mock_class}):
            svc = DialogTransformersService(bus=MagicMock(), config=config)
        return svc

    def test_transform_calls_plugin(self):
        def fake_transform(dialog, context=None):
            return "modified " + dialog, context
        svc = self._make_with_plugin(fake_transform)
        result, ctx = svc.transform("hello", context={})
        self.assertEqual(result, "modified hello")

    def test_transform_plugin_exception_does_not_propagate(self):
        def bad_transform(dialog, context=None):
            raise ValueError("oops")
        svc = self._make_with_plugin(bad_transform)
        # Should not raise, returns original dialog
        result, ctx = svc.transform("hello", context={})
        # plugin raised, dialog unchanged
        self.assertEqual(result, "hello")


class TestDialogTransformersShutdown(unittest.TestCase):

    def test_shutdown_calls_plugin_shutdown(self):
        from ovos_audio.transformers import DialogTransformersService
        svc = DialogTransformersService(bus=MagicMock(), config={})
        mock_plugin = MagicMock()
        mock_plugin.priority = 50
        svc.loaded_plugins["p"] = mock_plugin
        svc.shutdown()
        mock_plugin.shutdown.assert_called_once()

    def test_shutdown_logs_exception_not_raised(self):
        from ovos_audio.transformers import DialogTransformersService
        svc = DialogTransformersService(bus=MagicMock(), config={})
        mock_plugin = MagicMock()
        mock_plugin.priority = 50
        mock_plugin.shutdown.side_effect = RuntimeError("fail")
        svc.loaded_plugins["p"] = mock_plugin
        # Should not raise
        svc.shutdown()


class TestTTSTransformersService(unittest.TestCase):
    """TTSTransformersService init, set_bus, transform, shutdown."""

    def _make(self, config=None):
        from ovos_audio.transformers import TTSTransformersService
        return TTSTransformersService(bus=MagicMock(), config=config or {})

    def test_init_empty_config(self):
        svc = self._make()
        self.assertTrue(svc.has_loaded)
        self.assertEqual(svc.loaded_plugins, {})

    def test_plugins_empty(self):
        svc = self._make()
        self.assertEqual(svc.plugins, [])

    def test_transform_identity(self):
        svc = self._make()
        result, ctx = svc.transform("/tmp/test.wav", context={"a": 1})
        self.assertEqual(result, "/tmp/test.wav")
        self.assertEqual(ctx, {"a": 1})

    def test_transform_none_context(self):
        svc = self._make()
        result, ctx = svc.transform("/tmp/test.wav")
        self.assertEqual(result, "/tmp/test.wav")
        self.assertIsNone(ctx)

    def test_set_bus_propagates_to_plugins(self):
        svc = self._make()
        mock_plugin = MagicMock()
        svc.loaded_plugins["p"] = mock_plugin
        new_bus = MagicMock()
        svc.set_bus(new_bus)
        self.assertEqual(svc.bus, new_bus)
        mock_plugin.bind.assert_called_with(new_bus)

    def test_shutdown_no_plugins(self):
        svc = self._make()
        svc.shutdown()  # no exception

    def test_shutdown_with_plugin(self):
        svc = self._make()
        mock_plugin = MagicMock()
        mock_plugin.priority = 50
        svc.loaded_plugins["p"] = mock_plugin
        svc.shutdown()
        mock_plugin.shutdown.assert_called_once()

    def test_shutdown_logs_exception(self):
        svc = self._make()
        mock_plugin = MagicMock()
        mock_plugin.priority = 50
        mock_plugin.shutdown.side_effect = RuntimeError("fail")
        svc.loaded_plugins["p"] = mock_plugin
        svc.shutdown()  # should not raise

    def test_disabled_plugin_not_loaded(self):
        from ovos_audio.transformers import TTSTransformersService
        config = {"my.plugin": {"active": False}}
        fake_plugin = MagicMock()
        with patch("ovos_audio.transformers.find_tts_transformer_plugins",
                   return_value={"my.plugin": fake_plugin}):
            svc = TTSTransformersService(bus=MagicMock(), config=config)
        self.assertNotIn("my.plugin", svc.loaded_plugins)

    def test_plugin_load_exception_not_raised(self):
        from ovos_audio.transformers import TTSTransformersService
        config = {"bad.plugin": {"active": True}}
        bad_plugin = MagicMock(side_effect=RuntimeError("boom"))
        with patch("ovos_audio.transformers.find_tts_transformer_plugins",
                   return_value={"bad.plugin": bad_plugin}):
            svc = TTSTransformersService(bus=MagicMock(), config=config)
        self.assertNotIn("bad.plugin", svc.loaded_plugins)

    def test_transform_calls_plugin(self):
        from ovos_audio.transformers import TTSTransformersService
        config = {"p": {"active": True}}
        mock_instance = MagicMock()
        mock_instance.priority = 50
        mock_instance.transform.return_value = ("/tmp/transformed.wav", {})
        mock_class = MagicMock(return_value=mock_instance)
        with patch("ovos_audio.transformers.find_tts_transformer_plugins",
                   return_value={"p": mock_class}):
            svc = TTSTransformersService(bus=MagicMock(), config=config)
        result, ctx = svc.transform("/tmp/test.wav", context={})
        self.assertEqual(result, "/tmp/transformed.wav")


if __name__ == "__main__":
    unittest.main()
