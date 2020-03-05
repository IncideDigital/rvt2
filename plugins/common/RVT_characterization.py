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
import datetime
import json
from collections import defaultdict
import base.job
from plugins.common.RVT_disk import getSourceImage
from base.utils import check_directory, check_file

# TODO: Get disk info from new cloning machine
# TODO: Obtain last login from events instead of registry


def human_readable_size(num):
    for unit in ['', 'K', 'M', 'G', 'T', 'P']:
        if abs(num) < 1024.0:
            return "%3.1f%s" % (num, unit)
        num /= 1024.0
    return "%.1f%s" % (num, 'Yi')


class CharacterizeDisk(base.job.BaseModule):
    """ Extract summary info about disk and Windows partitions.

    Regripper output files and the timeline, must had been previously generated.
    If the image has been obtained by a cloning machine, logs should be provided as well

    Parameters:
        :ripplugins (str): path to json containing the list of plugins executed by 'autorip' job
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('hivesdir', os.path.join(self.myconfig('outputdir'), 'windows', 'hives'))
        self.set_default_config('ripplugins', os.path.join(self.config.config['windows']['plugindir'], 'autorip.json'))

    def run(self, path=None):
        """ The output dictionaries with disk information are expected to be sent to a mako template """
        disk = getSourceImage(self.myconfig)

        disk_info = self.get_image_information(disk)
        os_info = self.characterize_Windows()
        self.logger().info('Disk characterization finished')

        return [
            dict(disk_info=disk_info, os_info=os_info, source=self.myconfig('source'))
        ]

    def get_image_information(self, disk):
        """ Get partition tables and number of vss. If cloning logs are provided, model ans serial number are obtained """
        disk_info = {}

        disk_info["Size"] = human_readable_size(os.stat(disk.imagefile).st_size)
        disk_info["npart"] = disk.getPartitionNumber()

        logfile = "{}.LOG".format(disk.imagefile[:-3])

        if os.path.isfile(logfile):
            with open(logfile, "r") as f1:
                for line in f1:
                    aux = re.search(r"\*\s*(Model\s*:\s*[^\|]*)\|\s*Model\s*:", line)
                    if aux:
                        disk_info["model"] = aux.group(1)
                    aux = re.search(r"\*\s*(Serial\s*:\s*[^\|]*)\|\s*Serial\s*:", line)
                    if aux:
                        disk_info["serial_number"] = aux.group(1)
        disk_info["partition"] = []

        for p in disk.partitions:
            if p.filesystem != "Unallocated" and not p.filesystem.startswith("Primary Table"):
                disk_info["partition"].append({"pnumber": p.partition, "size": human_readable_size(p.size), "type": p.filesystem, "vss": len(p.vss)})

        return disk_info

    def characterize_Windows(self):
        """ Characterize Windows partitions from registry files and timeline. """

        hives_dir = self.myconfig('hivesdir')

        # Check registry is parsed. Generate the minimum files needed otherwise
        ripplugins_file = self.myconfig('ripplugins')
        if not check_directory(hives_dir):
            module = base.job.load_module(self.config, 'plugins.windows.RVT_autorip.Autorip', extra_config=dict(ripplugins=ripplugins_file))
            list(module.run())

        # Get the autorip outputfile associated with each necessary plugin
        with open(ripplugins_file) as rf:
            ripplugins = json.load(rf)
        used_plugins = ['winnt_cv', 'shutdown', 'timezone', 'lastloggedon', 'processor_architecture', 'compname', 'samparse', 'profilelist']
        os_plugins = ['winnt_cv', 'shutdown', 'timezone', 'lastloggedon', 'processor_architecture', 'compname']
        plugin_files = {plug: p['file'] for plug in used_plugins for p in ripplugins if plug in p['plugins']}

        plugin_fields = {'winnt_cv': ['  ProductName', '  CurrentVersion', '  InstallationType', '  EditionID', '  CurrentBuild', '  ProductId', '  RegisteredOwner', '  RegisteredOrganization', '  InstallDate'],
                         'shutdown': ['  ShutdownTime'],
                         'processor_architecture': ['PROCESSOR_ARCHITECTURE'],
                         'compname': ['ComputerName']}

        field_names = {'  ProductName': 'ProductName', '  CurrentVersion': 'CurrentVersion', '  InstallationType': 'InstallationType',
                       '  EditionID': 'EditionID', '  CurrentBuild': 'CurrentBuild', '  ProductId': 'ProductId', '  RegisteredOwner': 'RegisteredOwner',
                       '  RegisteredOrganization': 'RegisteredOrganization', '  InstallDate': 'InstallDate', '  ShutdownTime': 'ShutdownTime',
                       '  TimeZoneKeyName': 'TimeZone', 'PROCESSOR_ARCHITECTURE': 'ProcessorArchitecture', 'ComputerName': 'ComputerName'}

        partitions = [folder for folder in sorted(os.listdir(self.myconfig('mountdir'))) if folder.startswith('p')]

        # Define self.ntusers, that gets the creation date of NTUSER.DAT for every user and partition
        self.make_ntuser_timeline()

        # Main loop to populate os_info
        os_info = defaultdict(dict)
        for part in partitions:
            for plug in os_plugins:
                hivefile = os.path.join(hives_dir, '{}_{}.txt'.format(plugin_files[plug], part))
                if not check_file(hivefile):
                    continue
                with open(hivefile) as f_in:
                    if plug == 'lastloggedon':
                        for line in f_in:
                            if line.startswith('LastLoggedOn'):
                                f_in.readline()
                                last_write = f_in.readline()[11:].rstrip('\n')
                                f_in.readline()
                                last_user = f_in.readline()[22:].rstrip('\n')
                                os_info[part]['LastLoggedOn'] = '{} ({})'.format(last_write, last_user)
                                break
                        continue
                    elif plug == 'timezone':
                        for line in f_in:
                            if line.startswith('TimeZoneInformation'):
                                bias, tz_name = '', ''
                                while not line.startswith('....................') and line != "":
                                    line = f_in.readline()
                                    if line.startswith('  Bias'):
                                        bias = line[line.find('('):].rstrip('\n')
                                    if line.startswith('  TimeZoneKeyName'):
                                        line = line[len('  TimeZoneKeyName') + 3:].rstrip('\n')
                                        tz_name = line[:line.find('Time') + 4]
                                os_info[part]['TimeZone'] = '{} {}'.format(tz_name, bias)
                                break
                        continue

                    for field in plugin_fields[plug]:
                        f_in.seek(0)
                        for line in f_in:
                            if line.startswith(field):
                                os_info[part][field_names[field]] = line[len(field) + 3:].rstrip('\n')
                                break

            # Skip displaying partition info if it does not contain an OS
            if not os_info.get(part, None):
                self.logger().debug('No OS information for partition {}'.format(part))
                continue

            # Users Info
            hivefile = os.path.join(hives_dir, '{}_{}.txt'.format(plugin_files['samparse'], part))
            line = '  '
            users = []
            user_profiles = []
            if check_file(hivefile):
                with open(hivefile) as f_in:
                    # Parse samparse
                    while not line.startswith('profilelist') and line != "":
                        line = f_in.readline()

                        aux = re.search(r"Username\s*:\s*(.*)\n", line)
                        if aux:
                            user = [aux.group(1), "", ""]
                            while line != "\n":
                                line = f_in.readline()
                                aux = re.search(r"Account Created\s*:\s*(.*)\n", line)
                                if aux:
                                    aux1 = aux.group(1).replace("  ", " ")
                                    date = datetime.datetime.strptime(aux1, '%a %b %d %H:%M:%S %Y Z')
                                    user[1] = date.strftime('%d-%m-%Y %H:%M:%S UTC')
                                    continue
                                aux = re.search(r"Last Login Date\s*:\s*(.*)\n", line)  # TODO: check this field is reliable
                                if aux:
                                    if aux.group(1).find("Never") == -1:
                                        aux1 = aux.group(1).replace("  ", " ")
                                        date = datetime.datetime.strptime(aux1, '%a %b %d %H:%M:%S %Y Z')
                                        user[2] = date.strftime('%d-%m-%Y %H:%M:%S UTC')
                                    else:
                                        user[2] = "Never"
                                    users.append(user)
                                    break

                    # Parse profilelist
                    line = '  '
                    while not line.startswith('....................') and line != "":
                        line = f_in.readline()
                        aux = re.match(r"Path\s*:\s*.:.Users.(.*)", line.strip())
                        if aux:
                            # import pudb; pudb.set_trace()
                            user = [aux.group(1), "", ""]
                            while line != "\n":
                                line = f_in.readline()
                                aux = re.search(r"LastWrite\s*:\s*(.*)", line.strip())
                                if aux:
                                    aux1 = aux.group(1).replace("  ", " ")
                                    date = datetime.datetime.strptime(aux1, '%a %b %d %H:%M:%S %Y (UTC)')
                                    user[2] = date.strftime("%d-%m-%Y %H:%M:%S UTC")
                                    user_profiles.append(user)

            # Get creation date from NTUSER.DAT if not found in profilelist
            for i in user_profiles:
                for j in self.ntusers[part]:
                    if i[0] == j[0] and i[1] == "":
                        i[1] = j[1].strftime('%d-%m-%Y %H:%M:%S UTC')
            os_info[part]["users"] = users
            os_info[part]["user_profiles"] = user_profiles
        return os_info

    def make_ntuser_timeline(self):
        """ Get user creation date from the birth time of NTUSER.dat """

        timeline_file = os.path.join(self.config.get('plugins.common', 'timelinesdir'), '{}_TL.csv'.format(self.myconfig('source')))
        if not check_file(timeline_file):
            self.logger().warning('Timeline file not found: {}'.format(timeline_file))
            self.ntusers = {}
            return
        ntusers = defaultdict(list)
        with open(timeline_file, "r", encoding="iso8859-15") as tl_f:
            for line in tl_f:
                mo = re.search(r"mnt/(p\d+)/(?:Documents and settings|Users)/([^/]*)/(?:NTUSER|UsrClass)\.dat\"", line, re.IGNORECASE)
                if mo is not None:
                    part, user = mo.group(1), mo.group(2)
                    line = line.split(',')
                    if line[2][3] != 'b':
                        continue
                    if line[0].endswith("Z"):
                        date = datetime.datetime.strptime(line[0], '%Y-%m-%dT%H:%M:%SZ')
                    else:
                        date = datetime.datetime.strptime(line[0], '%Y %m %d %a %H:%M:%S')
                    if user not in ntusers[part]:
                        ntusers[part].append((user, date))

        self.ntusers = ntusers
