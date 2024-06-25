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
from base.utils import check_directory, check_file
from plugins.common.RVT_files import GetTimeline
from plugins.windows.windows_tz import win_tz

# TODO: Obtain last login from events instead of registry


class CharacterizeWindows(base.job.BaseModule):
    """ Extract summary info about Windows partitions OS general information and users.

    Timeline and Regripper output files must had been previously generated.

    Parameters:
        :ripplugins (str): path to json containing the list of essential plugins executed by 'autorip' job
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.users_sid = {}
        #self.aux_file = self.config.config['.'.join([__name__, self.__class__.__name__])]['aux_file']
        self.aux_file = self.myconfig('aux_file')

    def read_config(self):
        super().read_config()
        self.set_default_config('hivesdir', os.path.join(self.myconfig('outputdir'), 'windows', 'hives'))
        self.set_default_config('ripplugins', os.path.join(self.config.config['windows']['plugindir'], 'minimalrip.json'))
        self.set_default_config('aux_file', os.path.join(self.config.config['plugins.windows']['auxdir'], 'os_info.json'))

    def run(self, path=None):
        """ The output dictionaries with os information are expected to be sent to a mako template """

        # Check if there's another characterize job running
        base.job.wait_for_job(self.config, self)

        self.partitions = self.get_available_partitions()
        self.os_info = defaultdict(dict)

        # Get the autorip outputfile associated with each necessary plugin. Generate output if necessary
        self.get_ripplugins()
        if not self.ripplugins:
            return [dict(os_info=self.os_info, source=self.myconfig('source'))]

        used_plugins = ['winver2', 'shutdown', 'timezone', 'lastloggedon', 'processor_architecture', 'compname', 'samparse', 'profilelist', 'nic2']
        self.plugin_files = {plug: p['file'] for plug in used_plugins for p in self.ripplugins if plug in p['plugins']}
        # Define self.ntusers, that gets the creation date of NTUSER.DAT for every user and partition
        self.make_usrclass_timeline()

        # Get OS and users information
        for part in self.partitions:
            self.os_information(part)
            self.users_information(part)

        # Check there is a valid output
        if not self.os_info:
            self.logger().warning('No registry output has been generated. Make sure there are registry hives in the partition')
            return []

        self.logger().debug('Windows OS characterization finished')

        # Save information in auxiliar file to be used by other modules
        aux_json_file_raw = '.'.join(self.aux_file.split('.')[:-1]) + '_raw.json'
        check_directory(os.path.dirname(self.aux_file), create=True)
        with open(self.aux_file, 'w') as outfile:
            json.dump(self.os_info, outfile, indent=4)
        with open(aux_json_file_raw, 'w') as outfile:
            json.dump(self.os_info, outfile)

        return [
            dict(os_info=self.os_info, source=self.myconfig('source'))
        ]

    def get_available_partitions(self):
        # Get partition names of non empty partitions
        partitions = []
        for folder in sorted(os.listdir(self.myconfig('mountdir'))):
            if folder.startswith('p'):
                full_path = os.path.join(self.myconfig('mountdir'), folder)
                if not os.path.isfile(full_path) and os.listdir(full_path):
                    partitions.append(folder)
        return partitions

    def get_ripplugins(self):
        """ Get the autorip outputfile associated with each necessary plugin.
            If autorip results aren't found, generate a subsection of all plugins
        """
        self.hives_dir = self.myconfig('hivesdir')
        ripplugins_file = self.myconfig('ripplugins')
        with open(ripplugins_file) as rf:
            self.ripplugins = json.load(rf)

        # Check if registry is already parsed. Generate the minimum files needed otherwise
        if not check_directory(self.hives_dir):
            for partition_to_characterize in self.get_available_partitions():
                try:
                    list(base.job.run_job(self.config.copy(), 'windows.autorip_analyze',
                        path=os.path.join(self.myconfig('mountdir'), partition_to_characterize, '[Ww][Ii][Nn][Dd][Oo][Ww][Ss]/[Ss]ystem32/[Cc]onfig'),
                        extra_config=dict(volume_id=partition_to_characterize, ripplugins=ripplugins_file)))
                except base.job.RVTError as exc:
                    self.logger().warning(exc)
                    self.ripplugins = {}

    def os_information(self, part):
        """ Characterize Windows partitions from registry files. """

        os_plugins = ['winver2', 'shutdown', 'timezone', 'lastloggedon', 'processor_architecture', 'compname', 'nic2']

        plugin_fields = {'winver2': ['ProductName', 'InstallationType', 'EditionID', 'CurrentBuild', 'ProductId', 'RegisteredOwner', 'RegisteredOrganization', 'InstallDate'],
                         'shutdown': ['ShutdownTime'],
                         'processor_architecture': ['PROCESSOR_ARCHITECTURE'],
                         'compname': ['ComputerName']}

        field_names = {'ProductName': 'ProductName', 'InstallationType': 'InstallationType',
                       'EditionID': 'EditionID', 'CurrentBuild': 'CurrentBuild', 'ProductId': 'ProductId', 'RegisteredOwner': 'RegisteredOwner',
                       'RegisteredOrganization': 'RegisteredOrganization', 'InstallDate': 'InstallDate', 'ShutdownTime': 'ShutdownTime',
                       '  TimeZoneKeyName': 'TimeZone', 'PROCESSOR_ARCHITECTURE': 'ProcessorArchitecture', 'ComputerName': 'ComputerName'}

        # Main loop to populate os_info
        for plug in os_plugins:
            hivefile = os.path.join(self.hives_dir, '{}_{}.txt'.format(self.plugin_files[plug], part))
            if not check_file(hivefile):
                continue
            with open(hivefile, 'r') as f_in:
                if plug == 'lastloggedon':
                    for line in f_in:
                        if line.startswith('LastLoggedOn'):
                            f_in.readline()
                            last_write = f_in.readline()[11:].rstrip('\n')
                            f_in.readline()
                            last_user = f_in.readline()[22:].rstrip('\n')
                            self.os_info[part]['LastLoggedOn'] = '{} ({})'.format(last_write, last_user)
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
                            self.os_info[part]['TimeZone'] = '{} {}'.format(tz_name, bias)
                            break
                    continue
                elif plug == 'nic2':
                    ips = set()
                    for line in f_in:
                        if line.startswith('  IPAddress'):
                            ips.add(line[31:].rstrip())
                    self.os_info[part]['IpAddress'] = [i for i in ips if i]
                    continue

                for field in plugin_fields[plug]:
                    f_in.seek(0)
                    for line in f_in:
                        if line.startswith(field):
                            if plug == 'compname':
                                self.os_info[part][field_names[field]] = line.split('= ')[1].rstrip('\n').strip()
                            else:
                                self.os_info[part][field_names[field]] = line[len(field) + 3:].rstrip('\n').strip()
                            break

    def users_information(self, part):
        """ Get Users general information in Windows partitions from registry files and timeline. """

        # Skip displaying partition info if it does not contain an OS
        if not self.os_info.get(part, None):
            self.logger().debug('No OS information for partition {}'.format(part))
            return

        # users = {'username': '', 'creation_time': '', 'last_log': ''}
        users = {}
        # user_profiles = {'username': '', 'creation_time': '', 'last_log': '', 'sid': ''}
        user_profiles = {}
        samparse_hivefile = os.path.join(self.hives_dir, '{}_{}.txt'.format(self.plugin_files['samparse'], part))
        profilelist_hivefile = os.path.join(self.hives_dir, '{}_{}.txt'.format(self.plugin_files['profilelist'], part))

        # Usually samparse and profilelist should be on the same outputfile, but treat it separately just in case
        if not check_file(samparse_hivefile) or not profilelist_hivefile:
            return

        self._samparse(users, samparse_hivefile)
        self._profilelist(user_profiles, profilelist_hivefile)

        # Get creation date from usrclass.DAT if not found in profilelist
        for user, data in user_profiles.items():
            for ntusers_info in self.ntusers[part]:
                if user == ntusers_info[0] and data['creation_time'] == "":
                    data['creation_time'] = ntusers_info[1]
        self.os_info[part]["users"] = users
        self.os_info[part]["user_profiles"] = user_profiles

    def _samparse(self, users, file):
        # Parse samparse
        line = '  '
        with open(file) as f_in:
            while not line.startswith('samparse'):  # anything before samparse uotput is ignored
                line = f_in.readline()
                if not line:  # end of file
                    return

            while not line.startswith('.' * 20):   # a large line of points marks the end of the plugin output
                line = f_in.readline()
                aux = re.search(r"Username\s*:\s*(.*)\n", line)
                if aux:
                    username = aux.group(1)
                    users[username] = {'creation_time': '', 'last_write': ''}
                    while line != "\n":
                        line = f_in.readline()
                        aux = re.search(r"Account Created\s*:\s*(.*)\n", line)
                        if aux:
                            date = self._parse_dates(aux.group(1))
                            users[username]['creation_time'] = date.strftime('%Y-%m-%d %H:%M:%S')
                            continue
                        aux = re.search(r"Last Login Date\s*:\s*(.*)\n", line)  # TODO: check this field is reliable
                        if aux:
                            if aux.group(1).find("Never") == -1:
                                date = self._parse_dates(aux.group(1))
                                users[username]['last_write'] = date.strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                users[username]['last_write'] = "Never"
                            break
                if not line:  # end of file
                    return

    def _profilelist(self, user_profiles, file):
        # Parse profilelist
        line = '  '
        with open(file) as f_in:
            while not line.startswith('profilelist'):  # anything before profilelist uotput is ignored
                line = f_in.readline()
                if not line:  # end of file
                    return

            while not line.startswith('.' * 20):   # a large line of points marks the end of the plugin output
                line = f_in.readline()

                aux = re.match(r"Path\s*:\s*.:.Users.(.*)", line.strip())
                if aux:
                    username = aux.group(1)
                    user_profiles[username] = {'creation_time': '', 'last_write': '', 'sid': ''}
                    while line != "\n":
                        line = f_in.readline()
                        sid_search = re.search(r"SID\s*:\s*(.*)", line.strip())
                        last_write_search = re.search(r"LastWrite\s*:\s*(.*)", line.strip())
                        if sid_search:
                            user_profiles[username]['sid'] = sid_search.group(1)
                        elif last_write_search:
                            date = self._parse_dates(last_write_search.group(1))
                            user_profiles[username]['last_write'] = date.strftime("%Y-%m-%d %H:%M:%S")
                if not line:  # end of file
                    return

    def make_usrclass_timeline(self):
        """ Get user creation date from the birth time of UsrClass.dat"""

        # Get macb times of all UsrClass. Used to determine user account creation time
        try:
            usrclass_files = GetTimeline(config=self.config).get_macb([r"/(?:Documents and settings|Users)/.*(?:UsrClass)\.dat[\"\|]"], regex=True, progress_disable=True)
            # ntuser_files = GetTimeline(config=self.config).get_macb([r"/(?:Documents and settings|Users)/.*(?:NTUSER|UsrClass)\.dat[\"\|]"], regex=True, progress_disable=True)
        except IOError:
            self.ntusers = defaultdict(list)
            return []

        ntusers = defaultdict(list)
        # Determine birth time
        for filename, dates in usrclass_files.items():
            # Expected file format: sourcename/mnt/p0X/full_path'
            fn_parts = re.search(r"mnt/(p\d+)/(?:Documents and settings|Users)/([^/]*)(.*)/(?:NTUSER|UsrClass)\.dat", filename, re.IGNORECASE)
            if fn_parts is None:
                continue
            part, user, middle_path = fn_parts.groups()
            # Additional UsrClass.dat outside common locations will be ommited
            if middle_path.lower() not in ('', '/appdata/local/microsoft/windows'):
                self.logger().warning('Found extra user hive at {}. Consider analyzing this file separately'.format(filename))
                continue

            ntusers[part].append([user, datetime.datetime.strptime(dates['b'], "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S")])

        self.ntusers = ntusers

    def _parse_dates(self, date_string):
        """ Try different expected formats to get datetime object """
        date_string = date_string.rstrip('Z').rstrip('(UTC)').strip()
        possible_date_formats = ['%Y-%m-%d %H:%M:%S', '%a %b %d %H:%M:%S %Y']
        for date_format in possible_date_formats:
            try:
                return datetime.datetime.strptime(date_string, date_format)
            except ValueError:
                pass
        # Default answer
        self.logger().debug('No correct date format found for {}'.format(date_string))
        return datetime.datetime.min

    def get_information(self, item, partition='p01'):
        """ Get selected OS or user information by reading a previously defined json file where information is stored """

        self.logger().debug('Getting {} information about partition {}'.format(item, partition))
        os_info_keys = ["productname", "installationtype", "editionid", "currentbuild", "productid", "registeredowner", "registeredorganization",
                        "installdate", "shutdowntime", "timezone", "lastloggedon", "processorarchitecture", "computername"]
        users_info_keys = ["users", "user_profiles"]
        if item.lower() in os_info_keys:
            default_output = ''
        elif item.lower() in users_info_keys:
            default_output = defaultdict(dict)
        else:
            raise base.job.RVTError('Selected item <{}> is not a recognized OS attribute'.format(item))

        # Parse the minimal information from hives if not done before
        if not os.path.exists(self.aux_file):
            self.run()
        info = self.load_saved_os_info()
        if info:
            return info.get(partition, defaultdict(dict)).get(item, default_output)

        return default_output

    def load_saved_os_info(self):
        """ Load all OS info data from a previously saved json file """
        if os.path.exists(self.aux_file) and os.path.getsize(self.aux_file) > 0:
            with open(self.aux_file, 'r') as infile:
                return json.load(infile)
        return {}

    def get_users_names(self, partition=None):
        """ Check registry files to obtain the relation between user SID and name. """
        if self.users_sid:
            return self.users_sid

        # Parse the minimal information from hives if not done before
        if not os.path.exists(self.aux_file):
            self.run()

        # Assume first valid Windows partition is the right one. This may be problematic if multiple partitions exist
        if not partition:
            parsed_partitions = list(self.load_saved_os_info().keys())
            if parsed_partitions:
                partition = parsed_partitions[0]

        # Return if no registry information about users is available
        if not partition:
                return {}

        try:
            users = self.get_information("user_profiles", partition=partition)
            # Reverse the data for easier lookup
            self.users_sid = {}
            for user_name, data in users.items():
                if "sid" in data:
                    self.users_sid[data['sid']] = user_name
            return self.users_sid
        except Exception as exc:
            self.logger().warn(exc)
            return {}

    def get_user_name_from_sid(self, sid, partition=None, sid_default=True):
        # Return the name of a local user profile given a SID. IF not found, return the SID itself.
        users_sid = self.get_users_names(partition=partition)
        return users_sid.get(sid, sid if sid_default else '')

    def get_windows_version(self, partition='p01'):
        """ Get general version information about partition OS.
        It may be used in other modules to parse results according to OS version.

        Returns:
            versions (dict): Basic characterization of Windows version. Example: {'Name': 'Windows 10', 'SubVersion': '1809', 'Version': '10.0', 'BuildNumber': '17763', 'PublicRelease': '2018-11-13', 'RTMRelease': ''}
        """
        product = self.get_information("ProductName", partition)
        server = True if product.find('Server') != -1 else False
        build = self.get_information("CurrentBuild", partition)
        architecture = self.get_information("ProcessorArchitecture", partition)

        versions_file = os.path.join(self.config.config['windows']['plugindir'], 'windows_versions.json')
        with open(versions_file, 'r') as infile:
            info = json.load(infile)
        for version in info:
            if build == version['BuildNumber']:
                is_server = True if version['Name'].find('Server') != -1 else False
                if server == is_server:
                    version.update({'ProcessorArchitecture': architecture})
                    return version

        # Default answer if version not in predefined list
        self.logger().warning('OS Version not recognized. Run windows.characterize or update list of Windows versions')
        return {'Name': product, 'SubVersion': '', 'Version': version,
                'BuildNumber': build, 'PublicRelease': '', 'RTMRelease': '',
                'ProcessorArchitecture': architecture}

    def get_timezone(self, partition='p01'):
        """ Return tuple (tzinfo name, offset) reading computer timezone in registry"""

        raw_tz = self.get_information("TimeZone", partition)
        try:
            # Get the tzdata/Olsen timezone names
            name = re.search(r"(.*) \(", raw_tz)
            tzdata_name = win_tz.get(name.groups()[0].strip(), 'UTC')
            # Get the current bias as an integer (this number is season depending)
            bias = re.search(r"\((-?\d+) hours\)", raw_tz)
            bias = int(bias.groups()[0])
        except Exception:
            self.logger().debug('Unable to parse timezone from registry. Setting UTC.')
            tzdata_name = 'UTC'
            bias = 0

        return (tzdata_name, bias)


class GetUserFromSID(base.job.BaseModule):
    """ Substitute or add a 'user_field' given a 'sid_field' containing a user SID by consulting the user_profiles registry.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: Data dict.
        - **yields**: The updated dict data.

    Configuration:
        - **sid_field**: Names of the fiels containing the SID string. If not provided, this module is transparent.
        - **user_field**: Name for the new field containing user name. If not provided, overwrite 'sid_field'.
        - **keep_sid*: If True and 'user_field' is set, keep also the original 'sid_field'.
        - **sid_default**: If True, the value assigned to the user name if the SID is not found will be the SID itself. If False, it will be ''.
        - **partiton**: partition number to seek for user profiles. Exemple: 'p01'.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('sid_field', None)
        self.set_default_config('user_field', None)
        self.set_default_config('keep_sid', '')
        self.set_default_config('sid_default', True)
        self.set_default_config('partition', None)

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        sid_field = self.myconfig('sid_field')
        user_field = self.myconfig('user_field')
        if not sid_field:
            yield from self.from_module.run(path)
            return []

        keep_sid = self.myflag('keep_sid')
        sid_default = self.myflag('sid_default')
        partition = self.myconfig('partition')
        if not user_field:
            user_field = sid_field

        os_info = CharacterizeWindows(config=self.config)
        for data in self.from_module.run(path):
            if sid_field not in data:
                # Create user_field anyway
                data[user_field] = data.get(user_field, '') or ''
                yield data
                continue
            try:
                new_value = os_info.get_user_name_from_sid(data[sid_field], partition=partition, sid_default=sid_default)
                if sid_default and not new_value:
                    data[user_field] = data[sid_field]
                else:
                    data[user_field] = new_value
            except Exception as exc:
                self.logger().warn(exc)
                data[user_field] = data.get(user_field, '') or ''
            finally:
                if not keep_sid and sid_field != user_field:
                    data.pop(sid_field)
                yield data
