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
import unittest
import unittest.mock as mock
import time
from shutil import rmtree
from threading import Thread
from time import sleep

from os.path import exists
from ovos_utils.fakebus import FakeBus
from ovos_audio.service import AudioService
from ovos_bus_client.message import Message
from ovos_utils.ocp import MediaState


class TestLegacy(unittest.TestCase):
    def setUp(self):
        self.core = AudioService(FakeBus(), disable_ocp=True, autoload=False)
        self.core.config['default-backend'] = "simple"
        self.core.load_services()

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


if __name__ == "__main__":
    unittest.main()
