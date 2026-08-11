"""Tests for ovos_audio.__main__.main() entry point."""
import unittest
from unittest.mock import MagicMock, patch, call


class TestMain(unittest.TestCase):
    """main() wires up PlaybackService and blocks until exit signal."""

    def test_main_starts_service_and_waits(self):
        mock_service = MagicMock()
        with patch("ovos_audio.__main__.reset_sigint_handler") as mock_reset, \
             patch("ovos_audio.__main__.init_service_logger") as mock_logger, \
             patch("ovos_audio.__main__.setup_locale") as mock_locale, \
             patch("ovos_audio.__main__.PlaybackService", return_value=mock_service) as mock_cls, \
             patch("ovos_audio.__main__.wait_for_exit_signal") as mock_wait:
            from ovos_audio.__main__ import main
            main()

        mock_reset.assert_called_once()
        mock_logger.assert_called_once_with("audio")
        mock_locale.assert_called_once()
        mock_cls.assert_called_once()
        self.assertTrue(mock_service.daemon)
        mock_service.start.assert_called_once()
        mock_wait.assert_called_once()
        mock_service.shutdown.assert_called_once()

    def test_main_passes_hooks(self):
        mock_service = MagicMock()
        ready = MagicMock()
        error = MagicMock()
        stopping = MagicMock()
        watchdog = MagicMock()
        with patch("ovos_audio.__main__.reset_sigint_handler"), \
             patch("ovos_audio.__main__.init_service_logger"), \
             patch("ovos_audio.__main__.setup_locale"), \
             patch("ovos_audio.__main__.PlaybackService", return_value=mock_service) as mock_cls, \
             patch("ovos_audio.__main__.wait_for_exit_signal"):
            from ovos_audio.__main__ import main
            main(ready_hook=ready, error_hook=error, stopping_hook=stopping, watchdog=watchdog)

        _, kwargs = mock_cls.call_args
        self.assertEqual(kwargs["ready_hook"], ready)
        self.assertEqual(kwargs["error_hook"], error)
        self.assertEqual(kwargs["stopping_hook"], stopping)
        self.assertEqual(kwargs["watchdog"], watchdog)


if __name__ == "__main__":
    unittest.main()
