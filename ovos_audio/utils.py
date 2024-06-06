# Copyright 2017 Mycroft AI Inc.
#
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
from functools import wraps

from ovos_bus_client.send_func import send
from ovos_config import Configuration
from ovos_utils.log import deprecated, LOG
from ovos_utils.signal import check_for_signal


def validate_message_context(message, native_sources=None):
    destination = message.context.get("destination")
    if destination:
        native_sources = native_sources or Configuration()["Audio"].get(
            "native_sources", ["debug_cli", "audio"]) or []
        if any(s in destination for s in native_sources):
            # request from device
            return True
        # external request, do not handle
        return False
    # broadcast for everyone
    return True


def require_native_source():
    def _decorator(func):
        @wraps(func)
        def func_wrapper(self, message=None):
            validated = message is None or \
                        not self.validate_source or \
                        validate_message_context(message, self.native_sources)
            if validated:
                return func(self, message)
            LOG.debug(f"ignoring '{message.msg_type}' message, not from a native audio source")
            return None

        return func_wrapper

    return _decorator


# NOTE: nothing imports these from here, utils accidentally dragged while isolating ovos-audio
@deprecated("file signals have been deprecated", "0.1.0")
def is_speaking():
    """Determine if Text to Speech is occurring

    Returns:
        bool: True while still speaking
    """
    return check_for_signal("isSpeaking", -1)


# NOTE: nothing imports these from here, utils accidentally dragged while isolating ovos-audio
@deprecated("file signals have been deprecated", "0.1.0")
def wait_while_speaking():
    """Pause as long as Text to Speech is still happening

    Pause while Text to Speech is still happening.  This always pauses
    briefly to ensure that any preceeding request to speak has time to
    begin.
    """
    time.sleep(0.3)  # Wait briefly in for any queued speech to begin
    while is_speaking():
        time.sleep(0.1)


# NOTE: nothing imports these from here, utils accidentally dragged while isolating ovos-audio
@deprecated("file signals have been deprecated", "0.1.0")
def stop_speaking():
    """Stop mycroft speech.

    TODO: Skills should only be able to stop speech they've initiated
    """
    if is_speaking():

        send('mycroft.audio.speech.stop')

        # Block until stopped
        while check_for_signal("isSpeaking", -1):
            time.sleep(0.25)


def report_timing(ident, stopwatch, data):
    """ TODO - implement metrics upload at some point """
