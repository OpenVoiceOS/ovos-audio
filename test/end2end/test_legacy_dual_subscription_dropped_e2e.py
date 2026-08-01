"""Regression test for the dropped legacy dual-subscriptions.

``init_messagebus`` used to subscribe both a spec topic AND its legacy
counterpart for six topics that are already in the ovos-spec-tools
MIGRATION_MAP: ``mycroft.stop``, ``mycroft.audio.speech.stop``,
``mycroft.audio.speak.status``, ``mycroft.audio.queue``,
``mycroft.audio.play_sound`` and ``speak:b64_audio``. Those legacy
subscriptions were redundant: ``FakeBus``/the real bus-client namespace
bridge (``ovos_bus_client.client.client.MessageBusClient.on_message``)
already mirrors a legacy emit onto its spec counterpart for LOCAL
listeners, so a handler registered only on the spec topic still fires
when a deployment emits the legacy one.

This test locks in that dependency: it emits each legacy topic on a
bridge-enabled ``FakeBus`` and asserts the spec-only handler fires,
so a future change that disables the bridge (or removes a MIGRATION_MAP
entry these handlers rely on) is caught here instead of silently
breaking legacy deployments.
"""
import time
import unittest

from ovos_bus_client.message import Message

import ovos_audio.service as service_mod
from ovoscope.audio import PlaybackServiceHarness


class TestLegacyTopicsStillReachSpecOnlyHandlers(unittest.TestCase):
    """Legacy emits reach the spec-only subscriptions via the bus bridge."""

    def _fired_topics_for(self, legacy_topic, handler_name):
        """Boot a PlaybackService on a bridge-enabled FakeBus (via the
        ovoscope harness, ``modernize``/``emit_legacy`` default True), spy on
        ``handler_name``, emit ``legacy_topic`` and return the msg_types the
        handler was invoked with."""
        seen = []
        orig = getattr(service_mod.PlaybackService, handler_name)

        def spy(self, message=None):
            seen.append(message.msg_type if message else None)
            return orig(self, message)

        setattr(service_mod.PlaybackService, handler_name, spy)
        try:
            with PlaybackServiceHarness() as h:
                h.bus.emit(Message(legacy_topic))
                time.sleep(0.3)
        finally:
            setattr(service_mod.PlaybackService, handler_name, orig)
        return seen

    def test_legacy_mycroft_stop_reaches_spec_only_handler(self):
        self.assertTrue(
            self._fired_topics_for("mycroft.stop", "handle_stop"),
            "legacy 'mycroft.stop' must still reach handle_stop via the bus "
            "bridge now that the manual legacy subscription is gone",
        )

    def test_legacy_audio_speech_stop_reaches_spec_only_handler(self):
        self.assertTrue(
            self._fired_topics_for("mycroft.audio.speech.stop", "handle_stop"),
            "legacy 'mycroft.audio.speech.stop' must still reach handle_stop "
            "via the bus bridge",
        )

    def test_legacy_speak_status_reaches_spec_only_handler(self):
        self.assertTrue(
            self._fired_topics_for("mycroft.audio.speak.status",
                                   "handle_speak_status"),
            "legacy 'mycroft.audio.speak.status' must still reach "
            "handle_speak_status via the bus bridge",
        )

    def test_legacy_audio_queue_reaches_spec_only_handler(self):
        self.assertTrue(
            self._fired_topics_for("mycroft.audio.queue", "handle_queue_audio"),
            "legacy 'mycroft.audio.queue' must still reach handle_queue_audio "
            "via the bus bridge",
        )

    def test_legacy_play_sound_reaches_spec_only_handler(self):
        self.assertTrue(
            self._fired_topics_for("mycroft.audio.play_sound",
                                   "handle_instant_play"),
            "legacy 'mycroft.audio.play_sound' must still reach "
            "handle_instant_play via the bus bridge",
        )

    def test_legacy_speak_b64_audio_reaches_spec_only_handler(self):
        self.assertTrue(
            self._fired_topics_for("speak:b64_audio", "handle_b64_audio"),
            "legacy 'speak:b64_audio' must still reach handle_b64_audio via "
            "the bus bridge",
        )


if __name__ == "__main__":
    unittest.main()
