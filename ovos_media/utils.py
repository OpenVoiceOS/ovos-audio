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

from ovos_config import Configuration


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


def report_timing(ident, stopwatch, data):
    """ TODO - implement metrics upload at some point """
