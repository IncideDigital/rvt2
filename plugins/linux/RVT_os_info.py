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

import json
import os
import re
import shlex
import subprocess
import base.job
import pytz
from collections import defaultdict
from datetime import datetime, timezone
from base.utils import check_directory, date_to_iso
from plugins.linux import get_timezone

class CharacterizeLinux(base.job.BaseModule):
    
    """ Extract the essential information about user accounts in passwd file.

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()

    def run(self, path=None):
        """ The output dictionaries with os information are expected to be sent to a mako template """

        # Check if there's another characterize job running
        base.job.wait_for_job(self.config, self)

        self.partitions = [folder for folder in sorted(os.listdir(self.myconfig('mountdir'))) if folder.startswith('p')]
        self.os_info = defaultdict(dict)

        # With GRR dump the structure of folders in diferents partitions. But all partitions are one OS
        oneOS = True

        # Get OS information
        for part in self.partitions:
            self.os_information(part, oneOS)
        
         # Save information in auxiliar file to be used by other modules
        aux_json_file = self.myconfig('aux_file')
        aux_json_file_raw = '.'.join(aux_json_file.split('.')[:-1]) + '_raw.json'
        check_directory(os.path.dirname(aux_json_file), create=True)
        
        with open(aux_json_file, 'w') as outfile:
            json.dump(self.os_info, outfile, indent=4)
        with open(aux_json_file_raw, 'w') as outfile:
            json.dump(self.os_info, outfile)

        return [dict(os_info=self.os_info, source=self.myconfig('source'))]


    def os_information(self, part, oneOS):
            if oneOS:
                part_to_save = "01"
            else:
                part_to_save = part

            # Linux OS Information
            part_path = os.path.join(self.myconfig('mountdir'), "%s" % part)
            dist_name = dist_version = dist_version_id = dist_id = dist_id_like = dist_pretty_name = dist_version_codename = ""
            
            if os.path.isdir(os.path.join(part_path, "etc")):
                releas_f = ""
                if os.path.isfile(os.path.join(part_path, "etc/os-release")) or os.path.islink(os.path.join(part_path, "etc/os-release")):
                    releas_f = os.path.join(part_path, "etc/os-release")
                    if os.path.islink(releas_f):
                        releas_f = os.path.join(part_path, os.path.realpath(releas_f))
                    with open(releas_f, 'r') as file:
                        for line in file:
                            values = line.strip().split("=")
                            if values[0] == "NAME":
                                dist_name = values[1].strip('"')
                            elif values[0] == "VERSION":
                                dist_version = values[1].strip('"')
                            elif values[0] == "VERSION_ID":
                                dist_version_id = values[1].strip('"')
                            elif values[0] == "ID":
                                dist_id = values[1].strip('"')
                            elif values[0] == "ID_LIKE":
                                dist_id_like = values[1].strip('"')
                            elif values[0] == "PRETTY_NAME":
                                dist_pretty_name = values[1].strip('"')
                            elif values[0] == "VERSION_CODENAME":
                                dist_version_codename = values[1].strip('"')
                if os.path.isfile(os.path.join(part_path, "etc/lsb-release")) or os.path.islink(os.path.join(part_path, "etc/lsb-release")):
                    releas_f = os.path.join(part_path, "etc/lsb-release")
                    if os.path.islink(releas_f):
                        releas_f = os.path.join(part_path, os.path.realpath(releas_f))
                else:
                    for f in os.listdir(os.path.join(part_path, "etc")):
                        if f.endswith("-release"):
                            releas_f = os.path.join(part_path, "etc", f)
                if releas_f != "":
                    with open(releas_f, 'r') as file:
                        for line in file:
                            values = line.strip().split("=")
                            if values[0] == "DISTRIB_ID":
                                dist_id = values[1].strip('"')
                            elif values[0] == "DISTRIB_RELEASE":
                                dist_version_id = values[1].strip('"')
                            elif values[0] == "DISTRIB_CODENAME":
                                dist_version_codename = values[1].strip('"')
                            elif values[0] == "DISTRIB_DESCRIPTION":
                                dist_pretty_name = values[1].strip('"')
                
                self.os_info[part_to_save]["ProductName"] = dist_pretty_name
                if dist_version:
                    self.os_info[part_to_save]["CurrentVersion"] = dist_version
                elif dist_version_id:
                    self.os_info[part_to_save]["CurrentVersion"] = dist_version_id
                if dist_version_codename:
                    self.os_info[part_to_save]["DistribCodename"] = dist_version_codename
                
                if os.path.isfile(os.path.join(part_path, "etc/hostname")):
                    f_hostname = open(os.path.join(part_path, "etc/hostname"), "r")
                    hostname = f_hostname.read().rstrip()
                    f_hostname.close()
                    self.os_info[part_to_save]["ComputerName"] = hostname

                # Timezone data
                if os.path.isfile(os.path.join(part_path, "etc/timezone")):

                    tz_str = get_timezone(self.myconfig('mountdir'))
                    tz = pytz.timezone(tz_str)
                    current_time_in_timezone = datetime.now(tz)
                    utc_offset = current_time_in_timezone.utcoffset()
                    utc_offset_hours = utc_offset.total_seconds() / 3600
                    
                    self.os_info[part_to_save]["TimeZone"] = ' {} ({} hours)'.format(tz, int(utc_offset_hours))



            # Linux Kernel Version
            if os.path.isdir(os.path.join(part_path, "proc")) and not self.os_info[part_to_save].get("LinuxKernelVersion"):
                path_version = os.path.join(part_path, "proc/version")
                if os.path.isfile(path_version):
                    f_version = open(path_version, "r")
                    for linea in f_version:
                        aux = re.search(r"(Linux version [^\s]*)", linea)
                        if aux:
                            kernel_v = aux.group(1)
                            break
                    f_version.close()
                    self.os_info[part_to_save]["LinuxKernelVersion"] = kernel_v

            # Linux Kernel 
            if os.path.isdir(os.path.join(part_path, "var")):
                if os.path.isfile(os.path.join(part_path, "var/log/dmesg")) and not self.os_info[part_to_save].get("LinuxKernelVersion"):
                    f_dmesg = open(os.path.join(part_path, "var/log/dmesg"), "r")
                    for linea in f_dmesg:
                        aux = re.search(r"(Linux version [^\s]*)", linea)
                        if aux:
                            kernel_v = aux.group(1)
                            break
                    f_dmesg.close()
                    self.os_info[part_to_save]["LinuxKernelVersion"] = kernel_v

                if os.path.isfile(os.path.join(part_path, "var/log/installer/syslog")):
                    creation_time = os.path.getctime(os.path.join(part_path, "var/log/installer/syslog"))
                    creation_time_UTC = datetime.fromtimestamp(creation_time, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    self.os_info[part_to_save]["InstallDate"] = creation_time_UTC

                if os.path.isfile(os.path.join(part_path, "var/log/wtmp")):
                    tz = get_timezone(self.myconfig('mountdir'))

                    command = f"last -x shutdown -f {os.path.join(part_path, 'var/log/wtmp')} --time-format iso"
                    env = {'TZ':tz}

                    args = shlex.split(command)
                    process = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    output_string = process.stdout.read().split('\n')
                    
                    last_shutdown_line = output_string[0]
                    if last_shutdown_line.startswith("shutdown system down"):
                        from_time = datetime.fromisoformat(" ".join(last_shutdown_line.split()[4:5]))
                        to_time = datetime.fromisoformat(" ".join(last_shutdown_line.split()[6:7]))
                        if from_time > to_time:
                            last_shutdown_time = from_time
                        else:
                            last_shutdown_time = to_time
                        last_shutdown_utc = date_to_iso(last_shutdown_time, input_timezone=tz).replace("+00:00", "Z")
                        self.os_info[part_to_save]["ShutdownTime"] = last_shutdown_utc


class Fstab(base.job.BaseModule):
    """ Extract the essential information about fstab file.

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()

    def run(self, path=None):
        partitions_dict = {}
        for line in self.from_module.run(path):
            if not line.startswith('#'):
                data = line.split()
                group_entry_dict = {
                    "device": data[0],
                    "mount_point": data[1],
                    "type": data[2],
                    "options" : data[3],
                    "backup" : data[4],
                    "pass" : data[5]
                }
                partitions_dict[group_entry_dict["device"]] = group_entry_dict
        
        # Save information in auxiliar file to be used by other modules
        aux_json_file = self.myconfig('aux_file')
        aux_json_file_raw = '.'.join(aux_json_file.split('.')[:-1]) + '_raw.json'
        check_directory(os.path.dirname(aux_json_file), create=True)
        
        with open(aux_json_file, 'w') as outfile:
            json.dump(partitions_dict, outfile, indent=4)
        with open(aux_json_file_raw, 'w') as outfile:
            json.dump(partitions_dict, outfile)
                
        return [dict(partitions=partitions_dict, source=self.myconfig('source'))]