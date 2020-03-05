#!/usr/bin/env python3

"""
Copyright (c) 2012, CCL Forensics
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the CCL Forensics nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL CCL FORENSICS BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import sys
import os
import os.path as path
import re
try:
    from . import ccl_asldb
except:
    import ccl_asldb

__version__ = "0.1.1"
__description__ = "Reads the a folder of ASL files and harvests login, power and auth events"
__contact__ = "Alex Caithness"
__outputtype__ = 0
__outputext__ = "tsv"

TIMESTAMP_FORMAT="%Y-%m-%dT%H:%M:%SZ"
TSV_LINE_FORMAT="{0:" + TIMESTAMP_FORMAT + "}|{1}|{2}|{3}\n"

# Event Type Strings
EVENT_BOOT = "Boot"
EVENT_SHUTDOWN = "Shutdown"
EVENT_REBOOT = "Reboot"
EVENT_HIBERNATE = "Hibernate"
EVENT_WAKE = "Wake"
EVENT_LOGIN_LOGIN = "Login Process (Login)"
EVENT_LOGIN_LOGOUT = "Login Process (Logout)"
EVENT_LOGIN_UNKNOWN = "Login Process (Unknown Status)"
EVENT_LOGINWINDOW_LOGIN = "Login Window (Login)"
EVENT_LOGINWINDOW_LOGOUT = "Login Window (Logout)"
EVENT_LOGINWINDOW_UNKNOWN = "Login Window (Unknown Status)"
EVENT_FAILED_AUTHORISATION = "Authorisation Failed"
EVENT_SUDO = "Sudo"

# Wake reasons
WAKE_REASONS = {"OHC":"Open Host Controller (Often External USB Mouse/Keyboard etc.)",
                "EHC":"Enhanced Host Controller (Often External Bluetooth or Wireless device)",
                "USB":"USB Device",
                "LID":"Device lid lifted",
                "EC LID":"Device lid lifted",
                "PWRB":"Power button pressed",
                "RTC":"Real Time Clock - Scheduled wake"}

class AslEvent:
    def __init__(self, timestamp, event_type, user, details):
        self.timestamp = timestamp
        self.event_type = event_type
        self.user = user or ""
        self.details = details or ""

    def to_tsv_line(self):
        return TSV_LINE_FORMAT.format(self.timestamp, self.event_type, self.user, self.details)

"""
work_input - tuple containing the path to the asl folder
work_output - tuple containing the path for the output csv file
"""
def __dowork__(work_input, work_output):
    # Unpack input
    if not isinstance(work_input, tuple) or len(work_input) < 1:
        raise ValueError("work_input must be a tuple containing the path for the input database")

    if not isinstance(work_output, tuple) or len(work_output) < 1:
        raise ValueError("work_output must be a tuple containing the path for the output html report")

    input_dir = work_input[0]
    output_file_path = work_output[0]

    # Events will be a list AslEvent objects
    # For some events "user" and "other details" can be an empty string (boot times for example)
    events = []

    for file_path in os.listdir(input_dir):
        file_path = path.join(input_dir, file_path)
        # print("Reading: \"{0}\"".format(file_path))
        try:
            f = open(file_path, "rb")
        except IOError as e:
            # print("Couldn't open file {0} ({1}). Skipping this file".format(file_path, e))
            continue

        try:
            db = ccl_asldb.AslDb(f)
        except ccl_asldb.AslDbError as e:
            # print("Couldn't open file {0} ({1}). Skipping this file".format(file_path, e))
            f.close()
            continue

        for record in db:
            # *** boots ***
            if record.sender == "bootlog":
                events.append(AslEvent(record.timestamp, EVENT_BOOT, "", ""))
            # *** shutdowns ***
            elif record.sender == "shutdown":
                events.append(AslEvent(record.timestamp, EVENT_SHUTDOWN, "", ""))
            # *** reboots ***
            elif record.sender == "reboot":
                events.append(AslEvent(record.timestamp, EVENT_REBOOT, "", ""))
            # *** sleep/hibernation ***
            elif record.sender == "kernel" and record.message == "sleep":
                events.append(AslEvent(record.timestamp, EVENT_HIBERNATE, "", ""))
            # *** wakes ***
            elif record.sender == "kernel" and record.message.startswith("Wake reason"): # wakes
                reason_match = re.search(r"(?<=Wake reason: )[A-z ]+", record.message)
                if reason_match:
                    reason = "{0} {1}".format(record.message, "({0})".format(WAKE_REASONS[reason_match.group(0).strip()]) if reason_match.group(0).strip() in WAKE_REASONS else "")
                else:
                    reason = record.message
                events.append(AslEvent(record.timestamp, EVENT_WAKE, "", reason))
            # *** logins ***
            elif record.sender in ("login", "loginwindow", "sessionlogoutd") and record.facility in ("com.apple.system.lastlog", "com.apple.system.utmpx"):
                login_user = record.key_value_dict["ut_user"] if "ut_user" in record.key_value_dict else ""
                login_requested_by = record.key_value_dict["ut_line"] if "ut_line" in record.key_value_dict else ""
                if "ut_type" in record.key_value_dict:
                    if record.key_value_dict["ut_type"] == "7":
                        login_status = "process starting"
                        login_event_type = EVENT_LOGINWINDOW_LOGIN if record.sender == "loginwindow" else EVENT_LOGIN_LOGIN
                    elif record.key_value_dict["ut_type"] == "8":
                        login_status = "process exiting"
                        login_event_type = EVENT_LOGINWINDOW_LOGOUT if record.sender == "loginwindow" else EVENT_LOGIN_LOGOUT
                    else:
                        login_status = "ut_type={0}".format(record.key_value_dict["ut_type"])
                        login_event_type = EVENT_LOGINWINDOW_UNKNOWN if record.sender == "loginwindow" else EVENT_LOGIN_UNKNOWN
                else:
                    login_status = "unknown"

                # a little but of user friendliness
                if login_requested_by.startswith("tty"):
                    login_requested_by += " (terminal window)"
                if record.sender == "loginwindow":
                    login_requested_by += " (login from login window GUI)"

                events.append(AslEvent(record.timestamp, login_event_type, login_user, "Login for: \"{0}\"; Status: \"{1}\"".format(login_requested_by, login_status)))
            # *** failed auth ***
            elif record.sender == "authorizationhost" and record.facility == "authpriv" and record.level == 3:
                auth_user_match = re.search("(?<=<).+(?=>)", record.message)
                auth_user = auth_user_match.group(0) if auth_user_match else "---unknown---"
                events.append(AslEvent(record.timestamp, EVENT_FAILED_AUTHORISATION, auth_user, record.message))
            # *** sudo ***
            elif record.sender == "sudo" and record.level == 5:
                sudo_message = record.message.strip()
                sudo_message_split = sudo_message.split(" : ", 1)
                if len(sudo_message_split) == 2:
                    sudo_user, sudo_details = sudo_message_split
                else:
                    sudo_user, sudo_details = "---unknown---", ""
                events.append(AslEvent(record.timestamp, EVENT_SUDO, sudo_user, sudo_details))

        f.close()

    # Open and write output
    output = open(output_file_path, "w")
    output.write("Timestamp|Event Type|User|Other Details\n--|--|--|--\n")
    for event in sorted(events, key=lambda x: x.timestamp):
        output.write(event.to_tsv_line())
    output.close()


def __main__():
    if len(sys.argv) < 2:
        print()
        print("Usage: {0} <asl folder> <output.csv>".format(os.path.basename(sys.argv[0])))
        print()
        sys.exit(1)
    else:
        work_input = (sys.argv[1],)
        work_output = (sys.argv[2],)
        __dowork__(work_input, work_output)

if __name__ == "__main__":
    __main__()
