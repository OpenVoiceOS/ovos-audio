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
#
import time
import unittest
from time import sleep

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_utils.ocp import MediaState, TrackState, PlayerState

from ovos_audio.service import AudioService


class TestLegacy(unittest.TestCase):
    def setUp(self):
        self.core = AudioService(FakeBus(), disable_ocp=True,
                                 autoload=False,
                                 validate_source=True)
        self.core.config['default-backend'] = "simple"
        self.core.config['backends'] = {"simple": {
            "type": "ovos_simple",
            "active": True
        }}
        self.core.load_services()
        # simple plugin
        self.core.bus.remove_all_listeners('ovos.common_play.simple.play')

    def test_http(self):

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        utt = Message('mycroft.audio.service.play',
                      {"tracks": ["http://fake.mp3"]},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.play',
            "ovos.common_play.media.state",  # LOADING_MEDIA
            "ovos.common_play.track.state",  # QUEUED_AUDIOSERVICE
            "ovos.common_play.simple.play",  # call simple plugin
            "ovos.common_play.player.state",  # PLAYING
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # PLAYING_AUDIOSERVICE
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        state = messages[1]
        self.assertEqual(state.data["state"], MediaState.LOADING_MEDIA)
        state = messages[2]
        self.assertEqual(state.data["state"], TrackState.QUEUED_AUDIOSERVICE)
        state = messages[4]
        self.assertEqual(state.data["state"], PlayerState.PLAYING)
        state = messages[5]
        self.assertEqual(state.data["state"], MediaState.LOADED_MEDIA)
        state = messages[6]
        self.assertEqual(state.data["state"], TrackState.PLAYING_AUDIOSERVICE)
        # confirm stream has been loaded into plugin
        self.assertEqual(self.core.current._now_playing, "http://fake.mp3")

    def test_youtube(self):

        url = "https://www.youtube.com/watch?v=zc-R6ahuB-8&pp=ygULT3BlblZvaWNlT1M%3D"

        def x_t(u):
            extracted = []
            for t in u:
                if "youtube.com" in t:
                    t = f"https://NOT-{t}"
                extracted.append(t)
            return extracted

        real_x_t = self.core._extract

        self.core._extract = x_t
        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        utt = Message('mycroft.audio.service.play',
                      {"tracks": [url]},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.play',
            "ovos.common_play.media.state",  # LOADING_MEDIA
            "ovos.common_play.track.state",  # QUEUED_AUDIOSERVICE
            "ovos.common_play.simple.play",  # call simple plugin
            "ovos.common_play.player.state",  # PLAYING
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # PLAYING_AUDIOSERVICE
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # confirm stream has been extracted
        self.assertNotEqual(self.core.current._now_playing, url)


        self.core._extract = real_x_t

    def test_uri_error(self):

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        utt = Message('mycroft.audio.service.play',
                      {"tracks": ["bad_uri://fake.mp3"]},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.play',
            "ovos.common_play.media.state"  # invalid media
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        state = messages[-1]
        self.assertEqual(state.data["state"], MediaState.INVALID_MEDIA)

    def test_PLAYLIST(self):

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        utt = Message('mycroft.audio.service.play',
                      {"tracks": ["http://fake.mp3",
                                  "http://fake2.mp3",
                                  "http://fake3.mp3"]},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.play',
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # QUEUED_AUDIOSERVICE
            "ovos.common_play.simple.play",  # call simple plugin
            "ovos.common_play.player.state",  # PLAYING
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # PLAYING_AUDIOSERVICE
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        self.assertEqual(self.core.default._tracks,
                         ['http://fake.mp3',
                          'http://fake2.mp3',
                          'http://fake3.mp3'])
        self.assertEqual(self.core.default._idx, 0)

        messages = []

        utt = Message('mycroft.audio.service.next',
                      {},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.next',
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # QUEUED_AUDIOSERVICE
            "ovos.common_play.simple.play",  # call simple plugin
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        self.assertEqual(self.core.default._tracks,
                         ['http://fake.mp3',
                          'http://fake2.mp3',
                          'http://fake3.mp3'])
        self.assertEqual(self.core.default._idx, 1)
        messages = []

        utt = Message('mycroft.audio.service.next',
                      {},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.next',
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # QUEUED_AUDIOSERVICE
            "ovos.common_play.simple.play",  # call simple plugin
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        self.assertEqual(self.core.default._tracks,
                         ['http://fake.mp3',
                          'http://fake2.mp3',
                          'http://fake3.mp3'])
        self.assertEqual(self.core.default._idx, 2)
        messages = []

        utt = Message('mycroft.audio.service.prev',
                      {},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.prev',
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # QUEUED_AUDIOSERVICE
            "ovos.common_play.simple.play",  # call simple plugin
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        self.assertEqual(self.core.default._tracks,
                         ['http://fake.mp3',
                          'http://fake2.mp3',
                          'http://fake3.mp3'])
        self.assertEqual(self.core.default._idx, 1)

        messages = []

        utt = Message('mycroft.audio.service.queue',
                      {"tracks": ['http://fake4.mp3', 'http://fake5.mp3']},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.queue'
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        self.assertEqual(self.core.default._tracks,
                         ['http://fake.mp3',
                          'http://fake2.mp3',
                          'http://fake3.mp3',
                          'http://fake4.mp3',
                          'http://fake5.mp3'])
        self.assertEqual(self.core.default._idx, 1)

    def test_play_pause_resume(self):

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        utt = Message('mycroft.audio.service.play',
                      {"tracks": ["http://fake.mp3"]},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.play',
            "ovos.common_play.media.state",  # LOADING_MEDIA
            "ovos.common_play.track.state",  # QUEUED_AUDIOSERVICE
            "ovos.common_play.simple.play",  # call simple plugin
            "ovos.common_play.player.state",  # PLAYING
            "ovos.common_play.media.state",  # LOADED_MEDIA
            "ovos.common_play.track.state",  # PLAYING_AUDIOSERVICE
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        state = messages[4]
        self.assertEqual(state.data["state"], PlayerState.PLAYING)
        state = messages[5]
        self.assertEqual(state.data["state"], MediaState.LOADED_MEDIA)
        state = messages[6]
        self.assertEqual(state.data["state"], TrackState.PLAYING_AUDIOSERVICE)

        messages = []
        utt = Message('mycroft.audio.service.pause',
                      {},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.pause',
            "ovos.common_play.player.state",  # PAUSED
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        state = messages[-1]
        self.assertEqual(state.data["state"], PlayerState.PAUSED)

        messages = []
        utt = Message('mycroft.audio.service.resume',
                      {},
                      {})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            'mycroft.audio.service.resume',
            "ovos.common_play.player.state",  # PAUSED
            "ovos.common_play.track.state",  # PLAYING_AUDIOSERVICE
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        state = messages[-2]
        self.assertEqual(state.data["state"], PlayerState.PLAYING)

        messages = []

        self.core.track_start(None)  # end of track

        # confirm all expected messages are sent
        expected_messages = [
            "mycroft.audio.queue_end",
            "ovos.common_play.player.state",  # PAUSED
            "ovos.common_play.media.state",  # PLAYING_AUDIOSERVICE
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        state = messages[-2]
        self.assertEqual(state.data["state"], PlayerState.STOPPED)
        state = messages[-1]
        self.assertEqual(state.data["state"], MediaState.END_OF_MEDIA)

    def test_sources(self):

        called = False

        def play(*args, **kwargs):
            nonlocal called
            called = True

        self.core.play = play

        utt = Message('mycroft.audio.service.play',
                      {"tracks": ["http://fake.mp3"]},
                      {"destination": "audio"})  # native source
        self.core._play(utt)

        self.assertTrue(called)

        called = False
        utt = Message('mycroft.audio.service.play',
                      {"tracks": ["http://fake.mp3"]},
                      {}) # missing destination
        self.core._play(utt)
        self.assertTrue(called)

        called = False
        utt = Message('mycroft.audio.service.play',
                      {"tracks": ["http://fake.mp3"]},
                      {"destination": "hive"})  # external source
        self.core._play(utt)
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
