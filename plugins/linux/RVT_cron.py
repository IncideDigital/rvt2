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


import re
import base.job
import os
from base.utils import save_csv, save_dummy


class Cron(base.job.BaseModule):
    
    """ Extract the cron tasks and scripts

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('outdir', None)
        self.set_default_config('mountdir', None)
    

    def run(self, path=None):
        base_path = self.myconfig('outdir')
        mount_dir = self.myconfig('mountdir')
        pattern_cron = r'^\s*([\d*,\-/]+)\s+([\d*,\-/]+)\s+([\d*,\-/]+)\s+([\d*,\-/]+)\s+([\d*,\-/]+)\s+([\S]+)\s+(.+)$'
        prog = re.compile(pattern_cron)

        script_data = []
        file_path = path[len(mount_dir):]
        
        script_data.append("#########################################################################")
        script_data.append("#" + file_path)
        script_data.append("#########################################################################")

        is_cron = False
        for line in self.from_module.run(path):
            match = prog.match(line)
            if match:
                is_cron = True
                keys = ["Minute", "Hour", "Day of Month", "Month", "Day of Week", "user.name", "process.command_line","file.path"]
                values = list(match.groups())
                values.append(str(file_path))
                crontab_dict = {key: value for key, value in zip(keys, values)}
                yield crontab_dict
            else:
                script_data.append(line)
                    

        if not is_cron:
            txt_out = os.path.join(base_path, 'cronScripts.txt')
            save_dummy(script_data, outfile=txt_out)
        else:
            extra_data = []
            for line in script_data:
                if line and not line.startswith('#'):
                    extra_data.append({'line':line,'file.path':file_path})
            csv_out = os.path.join(base_path, 'cronReferences.csv')
            save_csv(extra_data, outfile=csv_out, file_exists='APPEND') 


class AnacronTab(base.job.BaseModule):
    
    """ Extract the anacrontab tasks and scripts

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()
    

    def run(self, path=None):
        base_path = self.myconfig('outdir')
        mount_dir = self.myconfig('mountdir')
        pattern_cron = r'^(\S*)\s+(\S*)\s+(\S*)\s+(.*)$'
        prog = re.compile(pattern_cron)

        script_data = []
        file_path = path[len(mount_dir):]

        for line in self.from_module.run(path):
            match = prog.match(line)
            if line and not line.startswith('#'):
                if match:
                    keys = ["Period(days)", "Delay(minutes)", "job-identifier", "command", "file.path"]
                    values = list(match.groups())
                    values.append(str(file_path))
                    crontab_dict = {key: value for key, value in zip(keys, values)}
                    yield crontab_dict
                else:
                    script_data.append(line)
                    
        extra_data = []
        for line in script_data:
            if line and not line.startswith('#'):
                extra_data.append({'line':line,'file.path':file_path})
        csv_out = os.path.join(base_path, 'cronReferences.csv')
        save_csv(extra_data, outfile=csv_out, file_exists='APPEND') 


class CronLog(base.job.BaseModule):
    """ Extract the cron logs

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()    

    def run(self, path=None):        
        self.check_params(path, check_path=True, check_path_exists=True)
        filename = os.path.basename(path)
        pattern = r'(\w+\s+\d+\s\d+:\d+:\d+)\s([\w.-]+)\s(.*\[\d+\]):(\s.*)'
        prog = re.compile(pattern)
        
        for line in self.from_module.run(path):
            match = prog.match(line)
            if match:
                timestamp, host, process, command = match.groups()
                log_entry_dict = {
                    "@timestamp": timestamp,
                    "host.hostname": host,
                    "process.name": process,
                    "process.command_line": command,
                    "filename": filename
                }
                yield log_entry_dict
            else:
                self.logger().warning("Regex pattern failed with some logline input " + line)