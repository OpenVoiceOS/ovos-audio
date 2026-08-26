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

    def _assert_exactly_once_on_spec_topic(self, legacy_topic, handler_name,
                                            spec_topic):
        seen = self._fired_topics_for(legacy_topic, handler_name)
        self.assertEqual(
            len(seen), 1,
            f"legacy '{legacy_topic}' must reach {handler_name} exactly "
            f"once via the bus bridge (no duplicate delivery), got {seen}",
        )
        self.assertEqual(
            seen[0], spec_topic,
            f"legacy '{legacy_topic}' must be delivered on the spec topic "
            f"'{spec_topic}', got '{seen[0]}'",
        )

    def test_legacy_mycroft_stop_reaches_spec_only_handler(self):
        self._assert_exactly_once_on_spec_topic(
            "mycroft.stop", "handle_stop", "ovos.stop")

    def test_legacy_audio_speech_stop_reaches_spec_only_handler(self):
        self._assert_exactly_once_on_spec_topic(
            "mycroft.audio.speech.stop", "handle_stop", "ovos.audio.stop")

    def test_legacy_speak_status_reaches_spec_only_handler(self):
        # ovos.audio.is_speaking is a query==reply topic (AUDIO-OUT-1 §5.3):
        # handle_speak_status is subscribed to it AND emits its status reply
        # on it, so the handler legitimately re-fires on its own reply. That
        # self-trigger is spec behavior, not a duplicate of the bridged
        # legacy delivery — so assert the bridge delivered on the spec topic
        # (first invocation), not an exact count.
        seen = self._fired_topics_for(
            "mycroft.audio.speak.status", "handle_speak_status")
        self.assertGreaterEqual(
            len(seen), 1,
            "legacy 'mycroft.audio.speak.status' must reach "
            f"handle_speak_status via the bus bridge, got {seen}")
        self.assertEqual(
            seen[0], "ovos.audio.is_speaking",
            "the bridged legacy emit must arrive first on the spec topic, "
            f"got '{seen[0]}'")

    def test_legacy_audio_queue_reaches_spec_only_handler(self):
        self._assert_exactly_once_on_spec_topic(
            "mycroft.audio.queue", "handle_queue_audio", "ovos.audio.queue")

    def test_legacy_play_sound_reaches_spec_only_handler(self):
        self._assert_exactly_once_on_spec_topic(
            "mycroft.audio.play_sound", "handle_instant_play",
            "ovos.audio.play_sound")

    def test_legacy_speak_b64_audio_reaches_spec_only_handler(self):
        self._assert_exactly_once_on_spec_topic(
            "speak:b64_audio", "handle_b64_audio",
            "ovos.utterance.speak.b64")


if __name__ == "__main__":
    unittest.main()
