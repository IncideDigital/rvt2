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

import ast
import os
import re
import shlex
import subprocess
import base
import glob
from datetime import datetime
from base.utils import check_directory, date_to_iso, save_csv, save_dummy
from plugins.linux import get_timezone


class LinuxDpkgLog(base.job.BaseModule):
    
    """ Extract the Dpkg

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()

    def run(self, path=None):
        pattern = r'(\d+-\d+-\d+\s\d+:\d+:\d+)\s(.*)'
        tz = get_timezone(self.myconfig('mountdir'))
        prog = re.compile(pattern)
        filename = os.path.basename(path)
        
        for line in self.from_module.run(path):
            match = prog.match(line)
            if match:
                timestamp, action = match.groups()
                log_entry_dict = {
                    "@timestamp": timestamp,
                    "action": action,
                    "filename": filename
                }
                actual_date = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                 # Parse the timestamp and convert it to ISO format
                output_string_utc = date_to_iso(actual_date, input_timezone=tz, output_timezone="UTC")
                log_entry_dict['@timestamp'] = output_string_utc

                yield log_entry_dict

            else:
                self.logger().warning("Regex pattern failed with some logline input " + line)


class LinuxAptHistoryLog(base.job.BaseModule):
    
    """ Extract the Dpkg

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()

    def run(self, path=None):
        aux_dict = {}
        for line in self.from_module.run(path):
            if line:
                linesplited = line.split(":", 1)
                if linesplited[0] == "Start-Date":
                    aux_dict = {}
                    timestamp = linesplited[1].strip()
                    localdate = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                    isodate = date_to_iso(localdate, input_timezone = get_timezone(self.myconfig('mountdir')))
                    aux_dict["@timestamp"] = isodate
                elif linesplited[0] == "End-Date":
                        timestamp = linesplited[1].strip()
                        localdate = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                        isodate = date_to_iso(localdate, input_timezone = get_timezone(self.myconfig('mountdir')))
                        aux_dict[linesplited[0]] = isodate
                        yield aux_dict
                elif linesplited[0] == "Commandline":
                    aux_dict[linesplited[0]] = linesplited[1]
                else:
                    if "action" in aux_dict:
                        aux_list =  list(aux_dict["action"])
                        aux_list.append({linesplited[0]:linesplited[1]})
                        aux_dict["action"] = aux_list
                    else:
                        aux_dict["action"] = [{linesplited[0]:linesplited[1]}]


class LinuxDpkgStatus(base.job.BaseModule):
    
    """ Extract the Dpkg Status

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """

    def read_config(self):
        super().read_config()

    def run(self, path=None):
        pattern = r'^(?!.*::)([\w-]*):\s?(.*)$'
        prog = re.compile(pattern)
        package_dict = {}
        
        for line in self.from_module.run(path):
            if line == "":
                data_dict = {
                    'package.name' : package_dict.get("Package", "Unknown!"),
                    'status' :  package_dict.get("Status", "Unknown!"),
                    'priority' : package_dict.get("Priority", ""),
                    'package.size' : package_dict.get("Installed-Size", ""),
                    'package.architecture' : package_dict.get("Architecture", ""),
                    'package.version' : package_dict.get("Version", ""),
                    'package.description' : package_dict.get("Description", "").replace('\n',''),
                    'maintainer' : package_dict.get("Maintainer", "")
                }
                package_dict.clear()
                yield data_dict
            else:
                rowValue = prog.match(line)
                if rowValue:
                    key, value = rowValue.groups()
                    package_dict[key] = value
                else:
                    prevValue = package_dict[key]
                    package_dict[key] = prevValue + "\n" + line


class SpecificFolders(base.job.BaseModule):
    
    """ Extract the software stored in /opt and /usr/local

    """

    def read_config(self):
        super().read_config()

    def run(self, path=None):
        check_directory(self.myconfig('analysisdir'), create=True)
        output_file = os.path.join(self.myconfig('analysisdir'), "other_programs.txt")
        
        path_to_opt = os.path.join(self.myconfig('mountdir'), "**", "opt")
        path_to_local = os.path.join(self.myconfig('mountdir'), "**", "usr", "local" )

        list_of_paths = [path_to_opt, path_to_local]

        for path in list_of_paths:
            list_files = glob.glob(path)
            if len(list_files) == 1:
                command = "tree -L 2 " + list_files[0]
                args = shlex.split(command)
                process = subprocess.Popen(args,  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                output = process.stdout.read().split("\n")
                if output:
                    save_dummy(output, outfile=output_file)
        '''
        path_to_sbin = os.path.join(self.myconfig('mountdir'), "**", "sbin")
        list_files_sbin = glob.glob(path_to_sbin)
        if len(list_files_sbin) == 1:
            command = f"find {list_files_sbin[0]}/ -exec dpkg -S {{}} \\; | grep 'no path found'"
            process = subprocess.run(command, shell=True,  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output = process.stdout.split("\n")
            if output:
                save_dummy(output, outfile=output_file)
            
            command_red = f"find {list_files_sbin[0]}/ -exec rpm -qf {{}} \\; | grep 'is not'"
            process_red = subprocess.run(command_red, shell=True,  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output_red = process_red.stdout.split("\n")
            if output_red:
                save_dummy(output_red, outfile=output_file)
        '''    

class AnalysisLinuxAptHistoryLog(base.job.BaseModule):
    """ Analysis the Apt History log

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """
    def read_config(self):
        super().read_config()
    
    def run(self, path=None):
        pkg_pattern = r'([\w\.-]+):(.+)\s\(([\d\~\w\.-]*).*\)'
        pkg_prog = re.compile(pkg_pattern)
        all_list = []

        for line in self.from_module.run(path):
            user_responsible = '' 
            action_list = ast.literal_eval(line["action"])
            if any("Requested-By" in x for x in action_list):
                user_responsible = [x["Requested-By"] for x in action_list if "Requested-By" in x]
            else:
                user_responsible = "Unknown"

            for action in action_list:
                package_action, package = list(action.items())[0]
                if not package_action == "Requested-By":
                    for package_name in package.split("),"):
                        if not str(package_name).endswith(")"):
                            package_name += ")"
                        match_pkg = pkg_prog.match(package_name.strip())
                        if match_pkg:
                            package_name, package_architecture, package_version = match_pkg.groups()
                            data_dict = {
                                '@timestamp': line['@timestamp'],
                                'package.name' : package_name,
                                'package.architecture' : package_architecture,
                                'package.version' : package_version,
                                'username' : user_responsible,
                                'action' : package_action
                            }

                            if package_action == "Install":
                                yield data_dict
                            all_list.append(data_dict)
                        else:
                            self.logger().warning("Regex pattern failed with some package name: " + package_name)

        analysisdir = self.myconfig('analysisdir')
        check_directory(analysisdir, create=True)

        if all_list:
            csv_all_out = os.path.join(analysisdir, 'apt_packages.csv')
            save_csv(all_list, outfile=csv_all_out)


class AnalysisLinuxDpkgLog(base.job.BaseModule):
    """ Analysis the Dpkg log

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """
    def read_config(self):
        super().read_config()
    
    def run(self, path=None):
        pkg_installed = r'status\sinstalled\s(.*):(\w+)+\s(.*)'
        pkg_prog = re.compile(pkg_installed)

        for line in self.from_module.run(path):
            match_pkg_installed = pkg_prog.match(line["action"])
            if match_pkg_installed:
                package_name, package_architecture, package_version = match_pkg_installed.groups()
                data_dict = {
                    '@timestamp': line['@timestamp'],
                    'package.name' : package_name,
                    'package.architecture' : package_architecture,
                    'package.version' : package_version
                }
                yield data_dict


class AnalysisLinuxDpkgStatus(base.job.BaseModule):
    """ Analysis the Dpkg log

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.
    """
    def read_config(self):
        super().read_config()
    
    def run(self, path=None):
        for line in self.from_module.run(path):
            if line["status"] == 'install ok installed':
                data_dict = {
                    'package.name' : line["package.name"],
                    'package.architecture' : line["package.architecture"],
                    'package.version' : line["package.version"]
                }
                yield data_dict
