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
from functools import wraps
from ovos_utils.log import LOG
from ovos_bus_client.session import SessionManager


def require_default_session():
    def _decorator(func):
        @wraps(func)
        def func_wrapper(self, message=None):
            validated = message is None or \
                        not self.validate_source or \
                        SessionManager.get(message).session_id == "default"
            if validated:
                return func(self, message)
            LOG.debug(f"ignoring '{message.msg_type}' message, not from a native audio source")
            return None

        return func_wrapper

    return _decorator


def report_timing(ident, stopwatch, data):
    """ TODO - implement metrics upload at some point """
