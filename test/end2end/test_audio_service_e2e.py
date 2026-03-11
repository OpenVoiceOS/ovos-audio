# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""End-to-end tests for AudioService (ovos_audio.audio).

Uses AudioServiceHarness from ovoscope to run AudioService on a FakeBus with
MockAudioBackend — no real audio plugins or internet required.

NOTE: AudioService._stop() has a 1-second stop guard.  Tests that invoke stop
must sleep at least 1.1 seconds after play() before calling stop().
"""

import time
import unittest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from ovoscope.audio import AudioCaptureSession, AudioServiceHarness


class TestPlayHttpTrack(unittest.TestCase):
    """play() wires tracks through add_list and calls play on the backend."""

    def test_play_http_track(self) -> None:
        """Backend add_list and play are invoked after mycroft.audio.service.play."""
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            self.assertIn("http://example.com/track.mp3", h.backend.played_tracks)
            h.assert_playing()


class TestPlayPauseResume(unittest.TestCase):
    """Full play → pause → resume lifecycle changes backend state correctly."""

    def test_play_pause_resume(self) -> None:
        """Backend state transitions through play, pause, and resume."""
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.assert_playing()

            h.pause()
            h.assert_paused()

            h.resume()
            self.assertFalse(h.backend.is_paused)
            # Still playing after resume
            self.assertTrue(h.backend.is_playing)


class TestStop(unittest.TestCase):
    """stop() after 1-second guard clears state and emits mycroft.stop.handled."""

    def test_stop(self) -> None:
        """stop() clears playing state and emits mycroft.stop.handled."""
        received = []
        with AudioServiceHarness() as h:
            h.bus.on("mycroft.stop.handled", lambda m: received.append(m))
            h.play(["http://example.com/track.mp3"])
            h.assert_playing()
            # Must sleep > 1 second to bypass AudioService stop guard
            time.sleep(1.1)
            h.stop()
            h.assert_stopped()
            time.sleep(0.1)
        self.assertTrue(len(received) > 0, "mycroft.stop.handled was not emitted")


class TestPlaylistNextPrev(unittest.TestCase):
    """next/prev control methods emit the correct bus messages."""

    def test_playlist_next_prev(self) -> None:
        """next and prev messages reach the service without errors."""
        with AudioServiceHarness() as h:
            h.play(["http://example.com/a.mp3", "http://example.com/b.mp3"])
            h.assert_playing()
            # next/prev are no-ops in the mock but must not raise
            h.bus.emit(Message("mycroft.audio.service.next"))
            time.sleep(0.05)
            h.bus.emit(Message("mycroft.audio.service.prev"))
            time.sleep(0.05)
            # Backend still considered playing
            self.assertTrue(h.backend.is_playing)


class TestQueueTracks(unittest.TestCase):
    """queue() appends additional tracks to the backend."""

    def test_queue_tracks(self) -> None:
        """Queued track URI must appear in backend.played_tracks."""
        with AudioServiceHarness() as h:
            h.play(["http://example.com/first.mp3"])
            h.queue(["http://example.com/second.mp3"])
            self.assertIn("http://example.com/second.mp3", h.backend.played_tracks)


class TestTrackInfo(unittest.TestCase):
    """track_info message returns dict with 'track' key."""

    def test_track_info(self) -> None:
        """mycroft.audio.service.track_info_reply must contain 'track'."""
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            info = h.get_track_info()
        self.assertIsNotNone(info)
        self.assertIn("track", info)
        self.assertEqual(info["track"], "http://example.com/track.mp3")


class TestListBackends(unittest.TestCase):
    """list_backends returns the mock backend info by name."""

    def test_list_backends(self) -> None:
        """mycroft.audio.service.list_backends response contains mock backend."""
        with AudioServiceHarness(backend_name="testbackend") as h:
            data = h.list_backends()
        self.assertIsNotNone(data)
        self.assertIn("testbackend", data)
        self.assertIn("supported_uris", data["testbackend"])


class TestAudioDuckingLowersVolume(unittest.TestCase):
    """Speech start event triggers volume ducking on active backend."""

    def test_audio_ducking_lowers_volume(self) -> None:
        """recognizer_loop:audio_output_start must call lower_volume."""
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.emit(Message("recognizer_loop:audio_output_start"))
            time.sleep(0.05)
            h.assert_volume_lowered()
            self.assertTrue(h.service.volume_is_speaking)


class TestAudioDuckingRestoresVolume(unittest.TestCase):
    """Speech end event restores volume after ducking."""

    def test_audio_ducking_restores_volume(self) -> None:
        """recognizer_loop:audio_output_end must call restore_volume."""
        with AudioServiceHarness() as h:
            h.play(["http://example.com/track.mp3"])
            h.bus.emit(Message("recognizer_loop:audio_output_start"))
            time.sleep(0.05)
            h.bus.emit(Message("recognizer_loop:audio_output_end"))
            time.sleep(0.05)
            h.assert_volume_restored()
            self.assertFalse(h.service.volume_is_speaking)


class TestSessionValidation(unittest.TestCase):
    """validate_source=True rejects play messages from non-default sessions."""

    def test_session_validation_rejects_non_default(self) -> None:
        """Non-default session must be ignored when validate_source=True."""
        with AudioServiceHarness(validate_source=True) as h:
            custom = Session("non-default-session-abc")
            msg = Message(
                "mycroft.audio.service.play",
                {"tracks": ["http://example.com/song.mp3"]},
                {"session": custom.serialize()},
            )
            h.bus.emit(msg)
            time.sleep(0.1)
            self.assertFalse(h.backend.is_playing)


class TestOcpFlagIntegration(unittest.TestCase):
    """volume_is_speaking transitions correctly without OCP installed."""

    def test_ocp_flag_integration(self) -> None:
        """volume_is_speaking goes True on speak start and False on speak end."""
        with AudioServiceHarness(disable_ocp=True) as h:
            h.play(["http://example.com/track.mp3"])
            self.assertFalse(h.service.volume_is_speaking)
            h.bus.emit(Message("recognizer_loop:audio_output_start"))
            time.sleep(0.05)
            self.assertTrue(h.service.volume_is_speaking)
            h.bus.emit(Message("recognizer_loop:audio_output_end"))
            time.sleep(0.05)
            self.assertFalse(h.service.volume_is_speaking)


if __name__ == "__main__":
    unittest.main()
