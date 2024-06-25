# Copyright (C) INCIDE Digital Data S.L.
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import os
import re
import subprocess
import pandas as pd
import base.job
from datetime import datetime
from base.utils import check_folder


class LinuxStandardLog(base.job.BaseModule):
    
    """ Extract the Logfile

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.

    Configuration:
        - **logtemplate**:  (String): String-based Template of the configuration logfile, usually: rsyslog.conf. Default RSYSLOG_TraditionalFileFormat
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('logtemplate', 'RSYSLOG_TraditionalFileFormat')

    def run(self, path=None):
        if self.myconfig('logtemplate') == "RSYSLOG_TraditionalFileFormat" :
            pattern = r'(\w+\s+\d+\s\d+:\d+:\d+)\s([\w.-]+)\s(.*)?'
            prog = re.compile(pattern)
            filename = os.path.basename(path)
            count_lines = 0
            prev_line_dict = {}
            
            for line in self.from_module.run(path):
                match = prog.match(line)
                if match:
                    count_lines += 1
                    timestamp, host, process_command = match.groups()
                    process, command = process_command.split(":", maxsplit=1)

                    log_entry_dict = {
                        "@timestamp": timestamp,
                        "process.name": process,
                        "message": command,
                        "filename": filename
                    }

                    if count_lines == 1:
                        prev_line_dict = log_entry_dict
                    else:
                        if ((self.count_leading_spaces(command) > 1) or (process.startswith("python3"))) and log_entry_dict["@timestamp"] == prev_line_dict["@timestamp"] and log_entry_dict["process.name"] == prev_line_dict["process.name"] :
                            prev_line_dict["message"] = prev_line_dict["message"] + log_entry_dict["message"]
                        else:
                            yield prev_line_dict
                            prev_line_dict = log_entry_dict
                else:
                    self.logger().warning("Regex pattern failed with some logline input " + line)
            if len(prev_line_dict) != 0:
                yield prev_line_dict
        else:
            self.logger().warning("Logtemplete " + self.myconfig('logtemplate') + " Not supported yet")

    def count_leading_spaces(self, line):
        count = 0
        for char in line:
            if char == ' ':
                count += 1
            else:
                break  # Stop counting when a non-space character is encountered
        return count

class JournalLogs(base.job.BaseModule):
    """ Extract from the Binarys Journal Logfile 

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """
    def read_config(self):
        super().read_config()
    
    def run(self, path=None):
        out_dir = self.myconfig('outdir')
        check_folder(out_dir)

        command = f"journalctl --directory {path} -o short-iso"
        env = {'TZ':"UTC"}
        process = subprocess.Popen(command, env=env,shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        command_output = process.stdout.readline()

        self.logger().warning("Extracting Journal logs, this might last some time")

        while command_output:
            output_splitted = command_output.split(" ", maxsplit=3)
            data = {
                '@timestamp' : output_splitted[0],
                'host.hostname' :  output_splitted[1],
                'process.name' : output_splitted[2],
                'message' :  output_splitted[3]
            }
            yield data
            command_output = process.stdout.readline()


class AnalysisLinuxSshLog(base.job.BaseModule):
    """ Analysis the Ssh log

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """
    def read_config(self):
        super().read_config()
    
    def run(self, path=None):
        df_sshlogin_aux = pd.DataFrame()
        aux_list_pids = []
        pid_pattern = r'.*\[(\d+)\]'
        pid_prog = re.compile(pid_pattern)

        p_pattern_accepted = r'.*Accepted\s(\w+)\sfor\s(\S+)\sfrom\s([\d\.]+)\sport\s(\d+).*'
        p_prog_accepted = re.compile(p_pattern_accepted)

        p_pattern_closed = r'.*pam_unix\(sshd:session\):\ssession\sclosed\sfor\suser\s(\S+).*'
        p_prog_closed = re.compile(p_pattern_closed)

        
        for line in self.from_module.run(path):
            line_pid = pid_prog.match(line["process.name"]).group(1)
            match_p_accepted = p_prog_accepted.match(line["message"].strip())

            if match_p_accepted:
                method, user_name, ut_host, port = match_p_accepted.groups()
                data = {'pid': line_pid,
                        'user.name': user_name, 
                        'method': method, 
                        'ut_host': ut_host,
                        'port': port,
                        '@timestamp': line['@timestamp'],
                        'ut_time_to': '',
                        'ut_time_total': ''
                        }
                new_row_df = pd.DataFrame([data])
                df_sshlogin_aux = pd.concat([df_sshlogin_aux, new_row_df], ignore_index=True)
            else:
                match_p_closed = p_prog_closed.match(line["message"].strip())
                if match_p_closed:
                    if df_sshlogin_aux.get("pid", "None").equals("None"):
                        data = {'pid': line_pid,
                                'user.name':  str(match_p_closed.groups()[0]), 
                                'method': 'Uknown', 
                                'ut_host': 'Uknown',
                                'port': 'Uknown',
                                '@timestamp': line['@timestamp'],
                                'ut_time_to': '',
                                'ut_time_total': 'Uknown - Session Closed '
                                }
                        yield data
                    else:
                        pid_in_df_sshlogin = df_sshlogin_aux.loc[df_sshlogin_aux['pid'] == line_pid]
                        if not pid_in_df_sshlogin.empty:
                            # it can be two or more sessions with the same pid
                            index_lists = [index_value for index_value in pid_in_df_sshlogin.index.values if index_value not in aux_list_pids]
                            index = index_lists[0]
                            aux_list_pids.append(index)

                            df_sshlogin_aux.at[index, "ut_time_to"] = line['@timestamp']

                            # time conversion
                            time_format = "%b %d %H:%M:%S"
                            time_from = df_sshlogin_aux.at[index, "@timestamp"]
                            time_to = line['@timestamp']

                            datetime_from = datetime.strptime(time_from, time_format)
                            datetime_to = datetime.strptime(time_to, time_format)

                            negative = ""
                            time_difference = datetime_to - datetime_from
                            if str(time_difference).startswith("-"):
                                time_difference = datetime_from - datetime_to
                                negative="-"
                            total_seconds = int(time_difference.total_seconds())
                            hours, remainder = divmod(abs(total_seconds), 3600)
                            minutes, seconds = divmod(remainder, 60)
                            formatted_result = f"{negative}{hours:02}:{minutes:02}:{seconds:02}"

                            df_sshlogin_aux.at[index, "ut_time_total"] = formatted_result
                            yield df_sshlogin_aux.loc[index, ['@timestamp','user.name', 'method', 'ut_host', 'port', 'ut_time_to', 'ut_time_total']].to_dict()
                        else:
                            data = {'pid': line_pid,
                                    'user.name':  str(match_p_closed.groups()[0]), 
                                    'method': 'Uknown', 
                                    'ut_host': 'Uknown',
                                    'port': 'Uknown',
                                    '@timestamp': line['@timestamp'],
                                    'ut_time_to': '',
                                    'ut_time_total': 'Uknown - Session Closed '
                                    }
                            yield data