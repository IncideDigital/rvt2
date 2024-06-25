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
import dateutil.parser
import shlex
import shutil
import codecs
from collections import OrderedDict
from Registry import Registry
from Registry.RegistryParse import parse_windows_timestamp as _parse_windows_timestamp
from tqdm import tqdm

from plugins.external import jobparser
import base.job
from base.utils import check_directory, check_file, save_csv, save_json, relative_path, windows_format_path
from base.commands import run_command, yield_command
from plugins.common.RVT_files import GetTimeline
from plugins.windows.RVT_os_info import CharacterizeWindows


# Types of Registry Data: https://www.chemtable.com/blog/en/types-of-registry-data.htm
REG_TYPES = {
    0: "REG_NONE",
    1: "REG_SZ",
    2: "REG_EXPAND_SZ",
    3: "REG_BINARY",
    4: "REG_DWORD",
    5: "REG_DWORD_BIG_ENDIAN",
    6: "REG_LINK",
    7: "REG_MULTI_SZ",
    8: "REG_RESOURCE_LIST",
    9: "REG_FULL_RESOURCE_DESCRIPTOR",
    10: "REG_RESOURCE_REQUIREMENTS_LIST",
    11: "REG_QWORD"
}


def parse_windows_timestamp(value):
    try:
        return _parse_windows_timestamp(value)
    except ValueError:
        return datetime.datetime.min


WINDOWS_TIMESTAMP_ZERO = parse_windows_timestamp(0).strftime("%Y-%m-%d %H:%M:%S")


def get_hives(path):
    """ Obtain the paths to all registry hives files present in a directory specified by `path`.

    Arguments:
        path (str): Hives location directory. Expected inputs:
            - Directory where registry hive files are stored, such as 'Windows/System32/config/' or 'Windows/AppCompat/Programs/'
            - Main volume directory --> Root directory, where 'Documents and Settings' or 'Users' folders are expected
            - Custom folder containing hives. Warning: 'ntuser.dat' are expected to be stored in a username folder.

    Returns:
        regfiles (dict): Dictionary where keys are hive related names and values are the absolute paths to those hives.
            In case of ntuser and usrclass hives, they are organized by username
    """
    regfiles = {}
    if not check_directory(path):
        return regfiles

    # Common Hives
    hive_names = {
        'system': 'system',
        'software': 'software',
        'sam': 'sam',
        'security': 'security',
        'amcache.hve': 'amcache',
        'syscache.hve': 'syscache',
        'bcd': 'bcd'}

    # Search only first level, not subfolders. File names MUST BE the expected Windows hives names. If names had been changed, they will be ommited
    for file in os.listdir(path):
        for hive_file, hive_name in hive_names.items():
            if file.lower() == hive_file:
                regfiles[hive_name] = os.path.join(path, file)

    # User hives
    usr = []
    regfiles["ntuser"] = {}
    regfiles["usrclass"] = {}

    # Recursive search in subdirectories. Username will be taken from the directory name where hive is found
    for root, dirs, files in os.walk(path):
        for file in files:
            for hve, hve_name in zip(['ntuser.dat', 'usrclass.dat'], ['ntuser', 'usrclass']):
                if file.lower() == hve:
                    user = relative_path(root, path).split('/')[0]
                    if user not in regfiles[hve_name]:
                        regfiles[hve_name][user] = os.path.join(root, file)
                        usr.append(user)

    if not regfiles['ntuser'] and not regfiles['usrclass']:
        del regfiles['ntuser']
        del regfiles['usrclass']

    return regfiles


def _parse_reg_key(volumekey, hive=''):
    """ Yelds registry values from a given key in ECS format """
    for value in volumekey.values():
        data = {
            '@timestamp': volumekey.timestamp().strftime("%Y-%m-%d %H:%M:%S"),   # Key LastWrite
            'registry.hive': hive,
            'registry.key': '/'.join(volumekey.path().split('\\')[1:]),
            'registry.value': value.name(),
            'registry.data.type': REG_TYPES.get(value.value_type(), value.value_type())
        }
        # String types (ECS requires the field to be a list)
        if value.value_type() in [Registry.RegSZ, Registry.RegExpandSZ,
                                  Registry.RegDWord, Registry.RegBigEndian,
                                  Registry.RegQWord, Registry.RegLink]:
            data['registry.data.strings'] = [value.value()]
        # Multi String Type (already a list)
        elif value.value_type() == Registry.RegMultiSZ:
            data['registry.data.strings'] = value.value()
        # Binary Types (may cause errors)
        else:
            try:
                data['registry.data.binary'] = value.value().hex()
            except Exception as exc:
                try:
                    data['registry.data.binary'] = str(value.value())
                except Exception as exc2:
                    data['registry.data.binary'] = "Error: Unknown Type Exception"
        yield data


def registry_key_to_json(volumekey, depth=1, hive='SOFTWARE'):
    """ Yields ecs format registry data from all subkeys of a registry key

        Parameters:
            - volumekey (Registry.Registry.RegistryKey): RegistryKey object pointing the key to parse
            - hive (str): Name of the hive. Ex: SOFTWARE, HKLM
            - depth (int): Maximum number of subkey iterations to perform. Default: 1 (only same level)
    """

    if depth > 0:
        # Get key values
        yield from _parse_reg_key(volumekey, hive=hive)
        # Recursively get subkey values
        for filekey in volumekey.subkeys():
            yield from registry_key_to_json(filekey, depth - 1, hive=hive)


def registry_simple_recursive_to_json(volumekey, depth=0, hive='SOFTWARE'):
    """ Yields ecs format registry data from all tree subkeys leafs

        Parameters:
            - registry (Registry.Registry): Registry object to the loaded hive
            - regkey (str): Key or subkey path inside the hive
            - hive (str): Name of the hive. Ex: SOFTWARE, HKLM
            - depth (int): Number of subkey iterations to perform. Default: 0
    """

    # TODO: take a common name for hive, relating to the path

    if len(volumekey.subkeys()) == 0:
        data = {
            '@timestamp': volumekey.timestamp().strftime("%Y-%m-%d %H:%M:%S"),   # Key LastWrite
            'registry.hive': hive,
            'registry.key': '/'.join(volumekey.path().split('\\')[1:]),
            'registry.value': volumekey.name()
        }
        yield data
    else:
        for filekey in volumekey.subkeys():
            yield from registry_simple_recursive_to_json(filekey, hive=hive)


def registry_key_tree_to_json(volumekey, depth=0, hive='SOFTWARE', data=None, event=None, start=True):
    """ Yields ecs format registry data joining all subkeys of a registry key
        in a single event

        Parameters:
            - registry (Registry.Registry): Registry object to the loaded hive
            - regkey (str): Key or subkey path inside the hive
            - hive (str): Name of the hive. Ex: SOFTWARE, HKLM
            - depth (int): Maximum number of subkey iterations to perform. Default: 0
    """

    # TODO: parse Registry.RegBin
    # TODO: take a common name for hive, relating to the path

    services_type = {1: "Kernel Driver",
                     2: "File System Driver",
                     4: "Adapter",
                     16: "Own Process",
                     32: "Share Process",
                     }

    services_start = {0: "Boot Start",
                      1: "Kernel Start",
                      2: "Auto Start",
                      3: "Manual",
                      4: "Disabled",
                      5: "Delayed Start"
                      }

    if start:
        data = list()
        for filekey in volumekey.subkeys():
            event = {
                '@timestamp': filekey.timestamp().strftime("%Y-%m-%d %H:%M:%S"),   # Key LastWrite
                'registry.hive': hive,
                'registry.key': '/'.join(filekey.path().split('\\')[1:])
            }
            data.append(event)
            registry_key_tree_to_json(filekey, depth - 1, hive=hive, data=data, event=event, start=False)

        return data

    # Recursive for loop when depth
    if depth > 0:
        for filekey in volumekey.subkeys():
            registry_key_tree_to_json(filekey, depth - 1, hive=hive, data=data, event=event, start=False)
    # Get registry data
    else:
        for value in volumekey.values():
            if value.value_type() in [Registry.RegSZ, Registry.RegExpandSZ,
                                      Registry.RegDWord, Registry.RegMultiSZ]:
                if value.name() == "Start":
                    event[f'registry.data.{value.name()}'] = services_start.get(value.value(), str(value.value()))
                elif value.name() == "Type":
                    event[f'registry.data.{value.name()}'] = services_type.get(value.value(), str(value.value()))
                else:
                    event[f'registry.data.{value.name()}'] = value.value()
            # Interesting data for Tasks subkeys, but may yield problems in other subkeys
            if value.name() == 'DynamicInfo':
                event[f'registry.data.DynamicInfo'] = value.value()


class AllKeys(base.job.BaseModule):
    """ Parses all keys and subkeys from a registry hive """

    def read_config(self):
        super().read_config()
        self.set_default_config('path', '')
        self.set_default_config('volume_id', '')

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)

        id = self.myconfig('volume_id', None)
        outfolder = self.myconfig('outdir')
        check_directory(outfolder, create=True)
        self.outfile = os.path.join(outfolder, 'all_registry{}.json'.format('_{}'.format(id) if id else ''))

        # When path is a file, parse only that hive
        if os.path.isfile(path):
            self._save_and_log(path)
            return []

        # Otherwise, get all hives inside path directory
        regfiles = get_hives(path)
        ntuser = None
        if 'ntuser' in regfiles:
            ntuser = regfiles.pop('ntuser')
        usrclass = None
        if 'usrclass' in regfiles:
            usrclass = regfiles.pop('usrclass')

        # Parse all hives
        for i, reg_hive in regfiles.items():
            self._save_and_log(reg_hive)
        for cls, cls_name in zip([ntuser, usrclass], ['NTUSER.DAT', 'UsrClass.dat']):
            if cls:
                for user, reg_hive in cls.items():
                    self._save_and_log(reg_hive, hive_name=f'{user}/{cls_name}')
        return []

    def _save_and_log(self, path, hive_name=None):
        self.logger().debug("Parsing all keys from hive {}".format(path))
        save_json(self._parse_all_keys(path, hive_name), outfile=self.outfile, file_exists='APPEND', quoting=0)
        self.logger().debug("Finished extraction from hive {}".format(path))

    def _parse_all_keys(self, path, hive_name=None):
        try:
            reg = Registry.Registry(path)
            volumekey = reg.root()
            if not hive_name:
                hive_name = reg.hive_name()
            yield from registry_key_to_json(volumekey, depth=100, hive=hive_name)
        except KeyError:
            self.logger().warning("Expected subkeys not found in hive file: {}".format(self.amcache_path))
        except Exception as exc:
            self.logger().warning("Problems parsing: {}. Error: {}".format(path, exc))


class AmCache(base.job.BaseModule):
    """ Parses Amcache.hve registry hive. """

    def read_config(self):
        super().read_config()
        self.set_default_config('path', '')
        self.set_default_config('volume_id', '')
        self.set_default_config('max_days', 90)

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)
        self.amcache_path = path
        self.hash_dict = {}

        # Determine output filename
        id = self.myconfig('volume_id', None)
        self.partition = id if id else 'p01'  # needed to get OS info
        outfolder = self.myconfig('outdir')
        check_directory(outfolder, create=True)
        self.outfile = os.path.join(outfolder, 'amcache{}.csv'.format('_{}'.format(id) if id else ''))

        self.days = int(self.myconfig('max_days'))

        self.logger().debug("Parsing {}".format(self.amcache_path))

        try:
            reg = Registry.Registry(self.amcache_path)
            entries = self.parse_amcache_entries(reg)
            save_csv(entries, outfile=self.outfile, file_exists='OVERWRITE', quoting=0)
        except KeyError:
            self.logger().warning("Expected subkeys not found in hive file: {}".format(self.amcache_path))
        except Exception as exc:
            self.logger().warning("Problems parsing: {}. Error: {}".format(self.amcache_path, exc))

        self.logger().debug("Amcache.hve parsing finished")
        return []

    def parse_amcache_entries(self, registry):
        """ Return a generator of dictionaries describing each entry in the hive.

        Fields:
            * KeyLastWrite: Possible application first executed time (must be tested)
            * AppPath: application path inside the volume
            * AppName: friendly name for application, if any
            * Sha1Hash: binary file SHA-1 hash value
            * Created: file creation time
            * LastModified: file modificatin time
            * GUID: Volume GUID the application was executed from
        """

        # Hive subkeys may have different relevant subkeys depending on OS version.
        # File amcache.hve appears on Windows 8. Previous versions used the RecentFileCache.bcf. Use job windows.execution for parsing this file
        #   * {GUID}\\Root\\File
        #   * {GUID}\\Root\\Programs
        #   * {GUID}\\Root\\InventoryApplication
        #   * {GUID}\\Root\\InventoryApplicationFile
        entries_by_version = {
            'Windows 10': {
                '1507': ['Programs', 'File'],
                '1511': ['Programs', 'File'],
                '1607': ['InventoryApplication', 'InventoryApplicationFile'],
                '1703': ['InventoryApplication', 'InventoryApplicationFile'],
                '1709': ['InventoryApplication', 'InventoryApplicationFile'],
                '1803': ['InventoryApplication', 'InventoryApplicationFile'],
                '1809': ['InventoryApplication', 'InventoryApplicationFile'],
                'default': ['InventoryApplication', 'InventoryApplicationFile'],
            },
            'Windows Server 2012': {
                '': ['File'],
                'R2': ['File']
            },
            'Windows Server 2016': {
                '1607': ['InventoryApplication', 'InventoryApplicationFile'],
                '1709': ['InventoryApplication', 'InventoryApplicationFile']
            },
            'Windows Server 2019': {'1809': ['InventoryApplication', 'InventoryApplicationFile']},
            'Windows 8': {'': ['File']},
            'Windows 8.1': {'': ['File']},
            'Windows 7': {'default': ['InventoryApplication', 'InventoryApplicationFile']}
        }
        structures = {
            'File': self._parse_File_entries,
            'Programs': self._parse_Programs_entries,
            'InventoryApplication': self._parse_IA_entries,
            'InventoryApplicationFile': self._parse_IAF_entries
        }

        os_version = CharacterizeWindows(config=self.config).get_windows_version(partition=self.partition)
        if os_version['Name']:
            self.logger().debug('Processing OS version {} {} {}'.format(os_version['Name'], os_version['SubVersion'], os_version['BuildNumber']))
        version_to_search = entries_by_version.get(os_version['Name'], {'default': ['InventoryApplication', 'InventoryApplicationFile', 'Programs', 'File']})
        if os_version['SubVersion'] in version_to_search:
            keys_to_search = version_to_search[os_version['SubVersion']]
        else:
            keys_to_search = version_to_search['default']
        if not keys_to_search:
            self.logger().info('Version {} has no known amcache keys'.format(os_version['Name']))
            raise KeyError

        # Parse every relevant key
        found_key = None
        for key in keys_to_search:
            try:
                volumes = registry.open("Root\\{}".format(key))
                found_key = key
                self.logger().debug('Parsing entries in key: Root\\{}'.format(key))
                for app in structures[key](volumes):
                    yield app
            except Registry.RegistryKeyNotFoundException:
                self.logger().debug('Key "Root\\{}" not found'.format(key))
            except Exception as exc:
                self.logger().warning(exc)

        if not found_key:
            raise KeyError('None of the subkeys found in Amcache')

    def _parse_File_entries(self, volumes):
        """ Parses File subkey entries for amcache hive """

        fields = {'LastModified': "17", 'Created': "12", 'AppPath': "15", 'AppName': "0", 'Sha1Hash': "101"}
        for volumekey in volumes.subkeys():
            for filekey in volumekey.subkeys():
                app = OrderedDict([('KeyLastWrite', WINDOWS_TIMESTAMP_ZERO), ('AppName', ''), ('AppPath', ''),
                                   ('ProgramId', ''), ('Sha1Hash', ''), ('Version', ''), ('Size', ''),
                                   ('Created', ''), ('LastModified', ''), ('Installed', ''), ('Uninstalled', ''), ('LinkDate', ''),
                                   ('GUID', ''), ('Subkey', 'File'), ('ismalware', '')])
                app['GUID'] = volumekey.path().split('}')[0][1:]
                app['KeyLastWrite'] = filekey.timestamp()
                for f in fields:
                    try:
                        val = filekey.value(fields[f]).value()
                        if f == 'Sha1Hash':
                            val = val[4:].rstrip()
                            if val in self.hash_dict.keys():
                                app.update({'ismalware': self.hash_dict[val]})
                        elif f in ['LastModified', 'Created']:
                            val = parse_windows_timestamp(val).strftime("%Y-%m-%d %H:%M:%S")
                        app.update({f: val})
                    except Registry.RegistryValueNotFoundException:
                        pass
                yield app

    def _parse_Programs_entries(self, volumes):
        """ Parses Programs subkey entries for amcache hive """

        fields = {'AppName': "0", 'AppPath': "d", 'Version': "1", 'Installed': "a", 'Uninstalled': "b"}
        for volumekey in volumes.subkeys():
            for filekey in volumekey.subkeys():
                app = OrderedDict([('KeyLastWrite', WINDOWS_TIMESTAMP_ZERO), ('AppName', ''), ('AppPath', ''),
                                   ('ProgramId', ''), ('Sha1Hash', ''), ('Version', ''), ('Size', ''),
                                   ('Created', ''), ('LastModified', ''), ('Installed', ''), ('Uninstalled', ''), ('LinkDate', ''),
                                   ('GUID', ''), ('Subkey', 'Programs'), ('ismalware', '')])
                app['GUID'] = volumekey.path().split('}')[0][1:]
                app['KeyLastWrite'] = filekey.timestamp()
                if app['Sha1Hash'].rstrip() in self.hash_dict.keys():
                    app.update({'ismalware': self.hash_dict[app['Sha1Hash'].rstrip()]})
                for f in fields:
                    try:
                        val = filekey.value(fields[f]).value()
                        if f in ['Installed', 'Uninstalled']:
                            val = datetime.datetime.fromtimestamp(int(val)).strftime("%Y-%m-%d %H:%M:%S")
                        app.update({f: val})
                    except Registry.RegistryValueNotFoundException:
                        pass
                yield app

    def _parse_IA_entries(self, volumes):
        """ Parses InventoryApplication subkey entries for amcache hive """

        names = {'RootDirPath': 'AppPath',
                 'InstallDate': 'Installed',
                 'ProgramId': 'ProgramId',
                 'ProgramInstanceId': 'Sha1Hash',
                 'Name': 'AppName',
                 'Version': 'Version'}

        for volumekey in volumes.subkeys():
            app = OrderedDict([('KeyLastWrite', WINDOWS_TIMESTAMP_ZERO), ('AppName', ''), ('AppPath', ''),
                               ('ProgramId', ''), ('Sha1Hash', ''), ('Version', ''), ('Size', ''),
                               ('Created', ''), ('LastModified', ''), ('Installed', ''), ('Uninstalled', ''), ('LinkDate', ''),
                               ('GUID', ''), ('Subkey', 'InventoryApplication'), ('ismalware', '')])
            app['GUID'] = volumekey.path().split('}')[0][1:]
            app['KeyLastWrite'] = volumekey.timestamp()
            for v in volumekey.values():
                if v.name() in ['RootDirPath', 'Name', 'Version']:
                    app.update({names.get(v.name(), v.name()): v.value()})
                elif v.name() in ['ProgramID', 'ProgramInstanceId']:
                    sha = v.value()[4:].rstrip()  # SHA-1 hash is registered 4 0's padded
                    app.update({names.get(v.name(), v.name()): sha})
                    if sha in self.hash_dict.keys():
                        app.update({'ismalware': self.hash_dict[sha]})
                elif v.name() == 'InstallDate':
                    install_date = ''
                    if v.value():
                        install_date = datetime.datetime.strptime(v.value(), "%m/%d/%Y %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%SZ")
                    app.update({names.get(v.name(), v.name()): install_date})
            yield app

    def _parse_IAF_entries(self, volumes):
        """ Parses InventoryApplicationFile subkey entries for amcache hive."""

        names = {'LowerCaseLongPath': 'AppPath',
                 'FileId': 'Sha1Hash',
                 'ProductName': 'AppName',
                 'Size': 'Size',
                 'ProgramId': 'ProgramId',
                 'LinkDate': 'LinkDate',
                 'Version': 'Version',
                 'ismalware': ''}

        for volumekey in volumes.subkeys():
            app = OrderedDict([('KeyLastWrite', WINDOWS_TIMESTAMP_ZERO), ('AppName', ''), ('AppPath', ''),
                               ('ProgramId', ''), ('Sha1Hash', ''), ('Version', ''), ('Size', ''),
                               ('Created', ''), ('LastModified', ''), ('Installed', ''), ('Uninstalled', ''), ('LinkDate', ''),
                               ('GUID', ''), ('Subkey', 'InventoryApplicationFile'), ('ismalware', '')])
            app['GUID'] = volumekey.path().split('}')[0][1:]
            app['KeyLastWrite'] = volumekey.timestamp()
            for v in volumekey.values():
                if v.name() in ['LowerCaseLongPath', 'ProductName', 'Size']:
                    app.update({names.get(v.name(), v.name()): v.value()})
                elif v.name() in ['FileId', 'ProgramId']:
                    sha = v.value()[4:]  # SHA-1 hash is registered 4 0's padded
                    app.update({names.get(v.name(), v.name()): sha})
                elif v.name == 'ismalware':
                    sha = app['Sha1Hash'].rstrip()
                    if sha in self.hash_dict.keys():
                        app.update({'ismalware': self.hash_dict[sha]})
                elif v.name() == 'LinkDate':
                    link_date = ''
                    if v.value():
                        link_date = datetime.datetime.strptime(v.value(), "%m/%d/%Y %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%SZ")
                    app.update({names.get(v.name(), v.name()): link_date})
            yield app


class ShimCache(base.job.BaseModule):
    """ Extracts ShimCache information from registry hives. """

    # TODO: .sdb shim database files (ex: Windows/AppPatch/sysmain.sdb)

    def read_config(self):
        super().read_config()
        self.set_default_config('path', '')
        self.set_default_config('volume_id', '')

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)
        self.shimcache_path = path

        # Determine output filename
        id = self.myconfig('volume_id', None)
        outfolder = self.myconfig('outdir')
        check_directory(outfolder, create=True)
        self.outfile = os.path.join(outfolder, 'shimcache{}.csv'.format('_{}'.format(id) if id else ''))

        self.logger().debug("Parsing shimcache on {}".format(self.shimcache_path))
        save_csv(self.parse_ShimCache_hive(self.shimcache_path), outfile=self.outfile, file_exists='OVERWRITE', quoting=0)
        self.logger().debug("Finished extraction from ShimCache")

        return []

    def parse_ShimCache_hive(self, sysfile):
        """ Launch shimcache regripper plugin and parse results """
        ripcmd = self.config.get('plugins.common', 'rip', '/opt/regripper/rip.pl')
        date_regex = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')

        # shimcache regripper plugin output sample:
        r"""
        shimcache v.20200428
        (System) Parse file refs from System hive AppCompatCache data

        *** ControlSet001 ***
        ControlSet001\Control\Session Manager\AppCompatCache
        LastWrite Time: 2022-09-01 09:47:19Z
        Signature: 0x34
        C:\ProgramData\Dell\UpdateService\Downloads\Driver_VP20T.EXE  2021-11-05 16:27:20
        C:\Program Files\Intel\WiFi\bin\iwrap.exe  2019-05-14 13:58:23 Executed
        """

        line_number = 0
        start = 1000
        for line in yield_command([ripcmd, "-r", sysfile, "-p", "shimcache"], logger=self.logger()):
            line_number += 1
            if line_number < 5:
                continue
            if line.startswith('LastWrite Time'):
                start = line_number + 1
            if line_number > start:
                matches = re.search(date_regex, line)
                if matches:
                    path = line[:matches.span()[0] - 2]
                    date = str(datetime.datetime.strptime(matches.group(), '%Y-%m-%d %H:%M:%S'))
                    executed = "Yes" if len(line[matches.span()[1]:].strip()) else "NA"
                    yield OrderedDict([('LastModified', date), ('AppPath', path), ('Executed', executed)])


class SysCache(base.job.BaseModule):
    """ Parse SysCache registry hive """

    def read_config(self):
        super().read_config()
        self.set_default_config('path', '')
        self.set_default_config('volume_id', '')
        self.set_default_config('max_days', 90)

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)

        # Determine output filename
        # Partition is needed to get inode information
        self.partition = self.myconfig('volume_id', None)
        if not self.partition:
            self.partition = relative_path(path, self.myconfig('mountdir')).split('/')[0] or 'p01'
        outfolder = self.myconfig('outdir')
        check_directory(outfolder, create=True)
        self.outfile = os.path.join(outfolder, f'syscache_{self.partition}.csv')

        self.days = int(self.myconfig('max_days'))
        self.logger().debug("Parsing SysCache hive: {}".format(path))
        save_csv(self.parse_SysCache_hive(path), outfile=self.outfile, file_exists='OVERWRITE', quoting=0)
        self.logger().debug("Finished extraction from SysCache")

        return []

    def parse_SysCache_hive(self, path):
        """ Use syscache_csv plugin from regripper to parse SysCache hive """
        ripcmd = self.config.get('plugins.common', 'rip', '/opt/regripper/rip.pl')
        output_text = run_command([ripcmd, "-r", path, "-p", "syscache_csv"], logger=self.logger())

        try:
            timeline = GetTimeline(config=self.config)
        except IOError:
            timeline = None

        hash_dict = {}

        # Since get_path_from_inode traverses the timeline every time, get all the inodes first and pass it as a list
        results = list()
        for line in output_text.split('\n')[:-1]:
            # line expected format: date_string,inode,sha1  (the last fragment ",sha1" is optional)
            line = line.strip().split(",")
            keydate = line[0]
            fileID = line[1]
            inode = line[1].split('/')[0]

            if len(line) == 2:  # Hash not included
                results.append(OrderedDict([("Date", dateutil.parser.parse(keydate).strftime("%Y-%m-%dT%H:%M:%SZ")),
                    ("Name", ""), ("Sha1", ""), ("Malware", ""), ("FileID", fileID), ("Inode", inode), ("FilenameFromHash", "")]))
                continue

            ismalware = ''
            original_filename = ''
            sha1 = line[2].rstrip()
            if sha1 in hash_dict.keys():
                ismalware = hash_dict[sha1]
            else:
                ismalware = False
                hash_dict[sha1] = False
            results.append(OrderedDict([("Date", dateutil.parser.parse(keydate).strftime("%Y-%m-%dT%H:%M:%SZ")),
                ("Name", ""), ("Sha1", sha1), ("Malware", ismalware), ("FileID", fileID), ("Inode", inode), ("FilenameFromHash", original_filename)]))

        # Get filename from inode if timeline is present
        filenames = {}
        if timeline:
            try:
                filenames = timeline.get_path_from_inode([r["inode"] for r in results], partition=self.partition)
            except Exception as exc:
                self.logger().warn(exc)
        for result in results:
            # Get path starting from partition (timeline returns in format "SOURCE/mnt/pX/path")
            if filenames:
                filename = '/'.join(filenames.get(result["inode"], "").split('/')[2:])
                if filename:
                    result["Name"] = filename
            result.pop("inode")
            yield result


class AppCompat(base.job.BaseModule):
    """ Get application executed. The timestamp recorded by Windows is the $SI Modification Time, not the execution time
    
    Configuration section:
        - **cmd**: external command to parse shellbags. It is a Python string template accepting variables "windows_tool", "executable", "hives_dir" and "outdir". Variable "hives_dir" is deduced by the job from "path". The rest are the same ones specified in parameters
        - **executable**: path to executable app to parse appcompat. By default is using AppCompatCacheParser. See (https://ericzimmerman.github.io/#!index.md)
        - **windows_tool**: in a non Windows environment, path to the tool needed to run the executable, such as `wine` or `dotnet`
        - **convert_paths**: Convert paths to Windows format ("\\"). Necessary when using native Windows tools like `wine`  
     """
    # appcompatcache regripper plugin doesn't seems to show executed flag. AppCompatCacheParser.exe does

    def read_config(self):
        super().read_config()
        self.set_default_config('path', '')
        self.set_default_config('volume_id', '')
        self.set_default_config('cmd', '')
        #self.set_default_config('cmd', '{windows_tool} {executable} -f {path} --csv {outdir} --csvf {filename} --nl')
        self.set_default_config('executable', os.path.join(self.config.config['plugins.windows']['windows_tools_dir'], 'AppCompatCacheParser.exe'))
        self.set_default_config('windows_tool', os.path.join(self.config.config['plugins.windows']['dotnet_dir'], 'dotnet'))
        self.set_default_config('convert_paths', False)

    def run(self, path=""):
        # Take path from params if not provided as an argument
        if not path:
            path = self.myconfig('path')

        # Determine output filename
        id = self.myconfig('volume_id', None)
        outfolder = self.myconfig('outdir')
        check_directory(outfolder, create=True)
        self.outfile = os.path.join(outfolder, 'appcompatcache{}.csv'.format('_{}'.format(id) if id else ''))
        tmp_file = os.path.join(os.path.dirname(self.outfile), 'temp_' + os.path.basename(self.outfile))

        cmd = self.myconfig('cmd', None)
        self.logger().debug("Parsing appcompatcache on registry hive {}".format(path))
        if not cmd:
            # Use regripper appcompatcache plugin to parse
            save_csv(self.parse_appcompatcache(path), outfile=self.outfile, file_exists='OVERWRITE', quoting=0)
        else:
            # Use the specified command to parse
            convert_paths = self.myflag('convert_paths')
            cmd_vars = {'windows_tool': self.myconfig('windows_tool'),
                        'executable': windows_format_path(self.myconfig('executable'), enclosed=True) if convert_paths else self.myconfig('executable'),
                        'path': windows_format_path(path, enclosed=True) if convert_paths else path,
                        'outdir': windows_format_path(self.myconfig('outdir'), enclosed=True) if convert_paths else self.myconfig('outdir'),
                        'filename': windows_format_path(os.path.basename(self.outfile), enclosed=True) if convert_paths else tmp_file}
            cmd_args = shlex.split(cmd.format(**cmd_vars))

            run_command(cmd_args)

            # Assuming AppCompatCacheParser is used, rearrange the default output and skip entries with Duplicate=True
            run_command("rg -v ',True,' {} | awk -F, '{{ print $4\";\"$3\";\"$2\";\"$5 }}' > {}".format(tmp_file, self.outfile))
            #run_command('mv {} {}'.format(tmp_file, self.outfile))

        self.logger().debug("Finished extraction from AppCompatCache")

        return []

    def parse_appcompatcache(self, path):
        """ Use appcompatcache plugin from regripper to parse AppCompatCache key in SYSTEM hive """
        ripcmd = self.config.get('plugins.common', 'rip', '/opt/regripper/rip.pl')
        date_regex = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        line_number = 0
        start = 1000
        result = {}
        for line in yield_command([ripcmd, "-r", path, "-p", "appcompatcache"], logger=self.logger()):
            line_number += 1
            if line_number < 5:
                continue
            if line.startswith('LastWrite Time'):
                start = line_number + 1
            if line_number > start:
                matches = re.search(date_regex, line)
                if matches:
                    path = line[:matches.span()[0] - 2]
                    date = str(datetime.datetime.strptime(matches.group(), '%Y-%m-%d %H:%M:%S'))
                    executed = "Yes" if len(line[matches.span()[1]:].strip()) else "NA"
                    yield OrderedDict([('LastModifiedTimeUTC', date), ('Path', path), ('Executed', executed)])

        return []

    def _check_valid_time(self, time_str, format="%Y-%m-%d %H:%M:%S"):
        try:
            datetime.datetime.strptime(time_str, format)
            return True
        except Exception:
            return False


class UserAssist(base.job.BaseModule):
    """ Parses UserAssist registry key in NTUSER.DAT hive.

    Configuration section:
        - **cmd**: external command to parse userassist. It is a Python string template accepting variables "executable", "hive", "outdir", "filename" and "batch_file". Variables "hive" and "file
name" are automatically set by the job. The rest are the same ones specified in parameters
        - **executable**: path to executable app to parse UserAssist. By default is using RECmd.exe. See (https://ericzimmerman.github.io/#!index.md)
        - **batch_file**: configuration file that settles the registry keys to be parsed. Relative to `windows_tools_dir`
        - **windows_tool**: in a non Windows environment, path to the tool needed to run the executable, such as `wine` or `dotnet`
        - **convert_paths**: Convert paths to Windows format ("\\"). Necessary when using native Windows tools like `wine`         
    """

    def read_config(self):
        super().read_config()
        #self.set_default_config('cmd', 'env WINEDEBUG=fixme-all wine {executable} --bn {batch_file} -f {hive} --csv {outdir} --csvf {filename} --nl')
        self.set_default_config('cmd', '{windows_tool} {executable} --bn {batch_file} -f {hive} --csv {outdir} --csvf {filename} --nl')
        self.set_default_config('executable', os.path.join(self.config.config['plugins.windows']['windows_tools_dir'], 'RECmd/RECmd.exe'))
        self.set_default_config('batch_file', os.path.join(self.config.config['plugins.windows']['windows_tools_dir'], 'RECmd/BatchExamples/BatchExampleUserAssist.reb'))
        self.set_default_config('windows_tool', os.path.join(self.config.config['plugins.windows']['dotnet_dir'], 'dotnet'))
        self.set_default_config('convert_paths', False)

    def run(self, path=""):

        # Take path from params if not provided as an argument
        if not path:
            path = self.myconfig('path')

        regfiles = get_hives(path)
        if 'ntuser' not in regfiles:
            self.logger().warning('No valid NTUSER.DAT registry hives provided')
            return []

        id = self.myconfig('volume_id', None)  # Volume identifier
        check_directory(self.myconfig('outdir'), create=True)

        cmd = self.myconfig('cmd')

        for user in tqdm(regfiles['ntuser'], total=len(regfiles['ntuser']), desc=self.section):
            output_filename = 'userassist_{}_{}.csv'.format(id if id else '', user)
            hive = regfiles['ntuser'][user]

            convert_paths = self.myflag('convert_paths')
            cmd_vars = {'windows_tool': self.myconfig('windows_tool'),
                        'executable': windows_format_path(self.myconfig('executable'), enclosed=True) if convert_paths else self.myconfig('executable'),
                        'batch_file': windows_format_path(self.myconfig('batch_file'), enclosed=True) if convert_paths else self.myconfig('batch_file'),
                        'hive': windows_format_path(hive, enclosed=True) if convert_paths else hive,
                        'outdir': windows_format_path(self.myconfig('outdir'), enclosed=True) if convert_paths else self.myconfig('outdir'),
                        'filename': windows_format_path(output_filename, enclosed=True) if convert_paths else output_filename}
            cmd_args = shlex.split(cmd.format(**cmd_vars))

            output_folder_to_remove = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H")
            run_command(cmd_args)

            # RECmd.exe creates an additional folder containing details. Remove those contents
            for f in os.listdir(self.myconfig('outdir')):
                if f.startswith(output_folder_to_remove):
                    try:
                        shutil.rmtree(os.path.join(self.myconfig('outdir'), f))
                    except Exception as exc:
                        raise base.job.RVTError(exc)

        return []


class UserAssistAnalysis(base.job.BaseModule):

    def run(self, path=""):
        """ Creates a report based on the output of UserAssist.

            Arguments:
                - ** path **: Path to directory where output files from UserAssist are stored
        """
        check_directory(path, error_missing=True)
        outfile = self.myconfig('outfile')
        check_directory(os.path.dirname(os.path.abspath(outfile)), create=True)

        #save_csv(self.report_userassist(path), config=self.config, outfile=outfile, file_exists='OVERWRITE', quoting=0, encoding='utf-8')
        #save_csv(self.report_userassist_v1(path), config=self.config, outfile=outfile[:-4] + '1.csv', file_exists='OVERWRITE', quoting=0, encoding='utf-8')
        save_csv(self.report_userassist_v2(path), config=self.config, outfile=outfile, file_exists='OVERWRITE', quoting=0, encoding='utf-8')

        return []

    def report_userassist(self, path):
        """ Create a unique userassist csv for all users """

        fields = ["LastExecuted", "ProgramName", "RunCounter", "FocusCount", "FocusTime"]

        for file in sorted(os.listdir(path)):
            if file.startswith('userassist'):
                # Expected file format: `userassist_partition_user.csv`
                user = '.'.join('_'.join(file.split('_')[2:]).split('.')[:-1])
                partition = file[11:-(len(user) + 5)]
                for line in base.job.run_job(self.config,
                                             'base.input.CSVReader',
                                             path=os.path.join(path, file),
                                             extra_config={'delimiter': ',', 'encoding': 'utf-8-sig'}):
                    res = OrderedDict([(field, line.get(field, '')) for field in fields])
                    res.update({'User': user, 'Partition': partition})
                    yield res

    def report_userassist_v1(self, path):
        """ Create a unique userassist csv for all users. Based on raw output of RECmd v1.6.0.0"""

        # Files are ROT13 encoded
        rot13 = lambda s: codecs.getencoder("rot-13")(s)[0]
        fields = ["LastWriteTimestamp", "ValueName"]

        for file in sorted(os.listdir(path)):
            if file.startswith('userassist'):
                # Expected file format: `userassist_partition_user.csv`
                user = '.'.join('_'.join(file.split('_')[2:]).split('.')[:-1])
                partition = file[11:-(len(user) + 5)]
                for line in base.job.run_job(self.config,
                                             'base.input.CSVReader',
                                             path=os.path.join(path, file),
                                             extra_config={'delimiter': ',', 'encoding': 'utf-8-sig'}):
                    res = OrderedDict([(field, line.get(field, '')) for field in fields])
                    res["LastExecuted"] = res.pop("LastWriteTimestamp").split('.')[0]
                    res['ProgramName'] = rot13(res.pop("ValueName"))
                    if not res['ProgramName']:
                        continue
                    res.update({'User': user, 'Partition': partition})
                    yield res


    def report_userassist_v2(self, path):
        """ Create a unique userassist csv for all users. Based on raw output of RECmd v2.0.0.0 """

        fields = ["LastWriteTimestamp", "ValueData", "ValueData2", "ValueData3", "Deleted"]

        for file in sorted(os.listdir(path)):
            if file.startswith('userassist'):
                # Expected file format: `userassist_partition_user.csv`
                user = '.'.join('_'.join(file.split('_')[2:]).split('.')[:-1])
                partition = file[11:-(len(user) + 5)]
                for line in base.job.run_job(self.config,
                                             'base.input.CSVReader',
                                             path=os.path.join(path, file),
                                             extra_config={'delimiter': ',', 'encoding': 'utf-8-sig'}):
                    if line['ValueType'] == 'RegDword':
                        continue
                    res = OrderedDict([(field, line.get(field, '')) for field in fields])
                    res["LastWrite"] = res.pop("LastWriteTimestamp").split('.')[0]
                    res['LastExecuted'] = res.pop("ValueData2")[15:].split('.')[0]  # Value in the format "Last executed: 2022-08-19 08:24:43.4370000"
                    res['ProgramName'] = res.pop("ValueData")
                    if not res['ProgramName']:
                        continue                    
                    res['RunCount'] = res.pop("ValueData3")[11:]  # Value in the format "Run count: 32"
                    res["Deleted"] = res.pop("Deleted")
                    res.update({'User': user, 'Partition': partition})
                    yield res


class Shellbags(base.job.BaseModule):
    """ Parses Shellbags registry key in NTUSER.DAT and/or usrclass.dat hive.

    Configuration section:
        - **cmd**: external command to parse shellbags. It is a Python string template accepting variables "windows_tool", "executable", "hives_dir" and "outdir". Variable "hives_dir" is deduced by the job from "path". The rest are the same ones specified in parameters
        - **executable**: path to executable app to parse shellbags. By default is using SBECmd.exe. See (https://ericzimmerman.github.io/#!index.md)
        - **windows_tool**: in a non Windows environment, path to the tool needed to run the executable, such as `wine` or `dotnet`
        - **convert_paths**: Convert paths to Windows format ("\\"). Necessary when using native Windows tools like `wine`  
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('cmd', '{windows_tool} {executable} -d {hives_dir} --csv {outdir} --nl --dedupe')
        self.set_default_config('executable', os.path.join(self.config.config['plugins.windows']['windows_tools_dir'], 'SBECmd/SBECmd.exe'))
        self.set_default_config('windows_tool', os.path.join(self.config.config['plugins.windows']['dotnet_dir'], 'dotnet'))
        self.set_default_config('convert_paths', False)

    def run(self, path=""):

        # Take path from params if not provided as an argument
        if not path:
            path = self.myconfig('path')

        # Get NTUSER.DAT and UsrClass.dat hives path for every user
        regfiles = get_hives(path)
        if 'ntuser' not in regfiles:
            self.logger().warning('No valid NTUSER.DAT or usrclass.dat registry hives provided')
            return []
        usr_folders = {}
        for user_hive in ['ntuser', 'usrclass']:
            for user, hive in regfiles.get(user_hive, {}).items():
                usr_folders[os.path.dirname(hive)] = user

        id = self.myconfig('volume_id', None)  # Volume identifier
        check_directory(self.myconfig('outdir'), create=True)

        cmd = self.myconfig('cmd')

        for hives_dir in tqdm(usr_folders, total=len(usr_folders), desc=self.section):
            user = usr_folders[hives_dir]
            # Only one user should own a folder with NTUSER.dat or UsrClasss.dat hives. Will overwrite if not.
            output_filename = 'shellbags_{}_{}.csv'.format(id if id else '', user)

            convert_paths = self.myflag('convert_paths')
            cmd_vars = {'windows_tool': self.myconfig('windows_tool'),
                        'executable': windows_format_path(self.myconfig('executable'), enclosed=True)  if convert_paths else self.myconfig('executable'),
                        'outdir': windows_format_path(self.myconfig('outdir'), enclosed=True)  if convert_paths else self.myconfig('outdir'),
                        'hives_dir': windows_format_path(hives_dir, enclosed=True) if convert_paths else hives_dir}
            cmd_args = shlex.split(cmd.format(**cmd_vars))

            run_command(cmd_args)

            # SBECmd.exe saves the output in a file called Deduplicated.csv. Change the name:
            if os.path.exists(os.path.join(self.myconfig('outdir'), 'Deduplicated.csv')):
                shutil.move(os.path.join(self.myconfig('outdir'), 'Deduplicated.csv'),
                            os.path.join(self.myconfig('outdir'), output_filename))

        # Remove summary file created by app
        os.remove(os.path.join(self.myconfig('outdir'), '!SBECmd_Messages.txt'))

        return []


class ShellbagsAnalysis(base.job.BaseModule):

    def run(self, path=""):
        """ Creates a report based on the output of Shellbags.

            Arguments:
                - ** path **: Path to directory where output files from Shellbags are stored
        """
        check_directory(path, error_missing=True)
        outfile = self.myconfig('outfile')
        check_directory(os.path.dirname(os.path.abspath(outfile)), create=True)

        save_csv(self.report_shellbags(path), config=self.config, outfile=outfile, file_exists='OVERWRITE', quoting=0, encoding='utf-8')

        return []

    def report_shellbags(self, path):
        """ Create a unique shellbags csv getting all users together """

        fields = ["LastWriteTime", "AbsolutePath", "FirstInteracted", "LastInteracted", "CreatedOn", "ModifiedOn", "AccessedOn", "HasExplored", "MFTEntry", "MFTSequenceNumber"]

        for file in sorted(os.listdir(path)):
            if file.startswith('shellbags'):
                # Expected file format: `shellbags_partition_user.csv`
                user = '.'.join('_'.join(file.split('_')[2:]).split('.')[:-1])
                partition = file[10:-(len(user) + 5)]
                for line in base.job.run_job(self.config,
                                             'base.input.CSVReader',
                                             path=os.path.join(path, file),
                                             extra_config={'delimiter': ',', 'encoding': 'utf-8-sig'}):
                    res = OrderedDict([(field, line.get(field, '')) for field in fields])
                    res.update({'User': user, 'Partition': partition})
                    yield res


class BaseRegistry(base.job.BaseModule):
    """ Base class to parse registry keys with Registry library """

    def read_config(self):
        super().read_config()
        self.set_default_config('path', '')
        self.set_default_config('volume_id', '')

    def get_outfile(self, prefix_name, extension='csv'):
        # Determine output filename
        id = self.myconfig('volume_id', None)
        self.partition = id if id else 'p01'  # needed to get OS info
        outfolder = self.myconfig('outdir')
        check_directory(outfolder, create=True)
        self.outfile = os.path.join(outfolder, '{}{}.{}'.format(
            prefix_name, '_{}'.format(id) if id else '', extension))

    def run(self, path=""):
        raise NotImplementedError


class RunKeys(BaseRegistry):
    """ Get autostart key contents from registry hives.
    Run Keys exist for all users in SOFTWARE hive and for individual users in NTUSER.DAT.
    """

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)
        self.get_outfile('run_keys', extension='csv')
        self.logger().debug("Parsing {}".format(path))

        regfiles = get_hives(path)
        if 'ntuser' not in regfiles and 'software' not in regfiles:
            self.logger().warning('No valid NTUSER.DAT or SOFTWARE registry hives provided')
            return []

        # Parse SOFTWARE Run Keys
        if 'software' in regfiles:
            # Since in the configuration files (job windows.registry_hives), SOFTWARE is parsed before NTUSER.DAT,
            # delete the output of any other possible executions of RunKeys jobs
            check_file(self.outfile, delete_exists=True)
            entries = self.parse_run_keys(regfiles['software'])
            save_csv(entries, outfile=self.outfile, file_exists='APPEND', quoting=0)
            return []

        # Parse NTUSER.DAT Run Keys
        for user in tqdm(regfiles['ntuser'], total=len(regfiles['ntuser']), desc=self.section):
            hive = regfiles['ntuser'][user]
            self.logger().debug("Parsing {}".format(hive))
            entries = self.parse_run_keys(hive, user=user)
            save_csv(entries, outfile=self.outfile, file_exists='APPEND', quoting=0)

    def parse_run_keys(self, path, user=None):

        run_keys = [
            'Microsoft\\Windows\\CurrentVersion\\Run',
            'Microsoft\\Windows\\CurrentVersion\\RunOnce',
            'Microsoft\\Windows\\CurrentVersion\\RunServices',
            'Wow6432Node\\Miyycrosoft\\Windows\\CurrentVersion\\Run',
            'Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\RunOnce',
            'Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer\\Run',
            'Microsoft\\Windows NT\\CurrentVersion\\Terminal Server\\Install\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',
            'Microsoft\\Windows NT\\CurrentVersion\\Terminal Server\\Install\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce',
            'Microsoft\\Windows\\CurrentVersion\\StartupApproved\\Run',
            'Microsoft\\Windows\\CurrentVersion\\StartupApproved\\Run32',
            'Microsoft\\Windows\\CurrentVersion\\StartupApproved\\StartupFolder'
        ]

        try:
            registry = Registry.Registry(path)
        except Exception as exc:
            self.logger().warning("Problems parsing: {}. Error: {}".format(path, exc))
        for regkey in run_keys:
            if user:
                # Desired keys in NTUSER.DAT start with SOFTWARE
                regkey = 'SOFTWARE\\' + regkey
            try:
                volumekey = registry.open(regkey)
                for result in registry_key_to_json(volumekey, depth=1, hive='SOFTWARE'):
                    result['user.name'] = user
                    result.pop('registry.hive')
                    result.pop('registry.data.type')
                    yield result
            except Registry.RegistryKeyNotFoundException:
                self.logger().debug(f'Key {regkey} not found')
            except KeyError:
                self.logger().warning("Expected subkeys not found in hive file: {}".format(self.amcache_path))

        self.logger().debug("RunKeys parsing finished")
        return []


class Services(BaseRegistry):
    """ Get services key contents from System hive. """

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)
        self.get_outfile('services', extension='json')
        self.logger().debug("Parsing {}".format(path))

        entries = self.parse_services_keys(path)
        # save_csv(entries, outfile=self.outfile, file_exists='OVERWRITE', quoting=0)
        save_json(entries, outfile=self.outfile, file_exists='OVERWRITE', quoting=0)

    def parse_services_keys(self, path):

        try:
            registry = Registry.Registry(path)
        except Exception as exc:
            self.logger().warning("Problems parsing: {}. Error: {}".format(path, exc))

        # Get current control set number
        select = registry.open("Select")
        current = select.value("Current").value()

        regkey = f"ControlSet{current:03d}\\Services"

        try:
            volumekey = registry.open(regkey)
            yield from registry_key_tree_to_json(volumekey, depth=1, hive='SYSTEM')
        except Registry.RegistryKeyNotFoundException:
            self.logger().debug(f'Key {regkey} not found')
        except KeyError:
            self.logger().warning("Expected subkeys not found in hive file: {}".format(self.amcache_path))

        self.logger().debug("Services Keys parsing finished")
        return []


class Tasks(BaseRegistry):
    """ Get TaskCache key contents from Software hive. """

    def run(self, path=""):
        self.check_params(path, check_path=True, check_path_exists=True)
        self.get_outfile('tasks', extension='csv')
        self.logger().debug("Parsing {}".format(path))

        entries = self.parse_tasks_keys(path)
        save_csv(entries, outfile=self.outfile, file_exists='OVERWRITE', quoting=0)
        #save_json(entries, outfile=self.outfile, file_exists='OVERWRITE', quoting=0)

    def parse_tasks_keys(self, path):

        try:
            registry = Registry.Registry(path)
        except Exception as exc:
            self.logger().warning("Problems parsing: {}. Error: {}".format(path, exc))

        regkey = 'Microsoft\\Windows NT\\CurrentVersion\\Schedule\\TaskCache\\Tasks'
        # Key 'Microsoft\\Windows NT\\CurrentVersion\\Schedule\\TaskCache\\Tree' won't be parsed since the information is not relevant

        try:
            volumekey = registry.open(regkey)
            for subkey in registry_key_tree_to_json(volumekey, depth=1, hive='SOFTWARE'):
                task_created, last_executed = ("", "")
                if subkey.get('registry.data.DynamicInfo', ""):
                    task_created, last_executed = self.convert_hex_dates(subkey['registry.data.DynamicInfo'])
                yield OrderedDict([("@timestamp", subkey['@timestamp']),
                                  ('Task', subkey.get('registry.data.Path', "")),
                                  ('Created', subkey.get('registry.data.Date', task_created)),
                                  ('LastExecuted', last_executed),
                                  ('Author', subkey.get('registry.data.Author', "")),
                                  ('Description', subkey.get('registry.data.Description', ""))])
        except Registry.RegistryKeyNotFoundException:
            self.logger().debug(f'Key {regkey} not found')
        except KeyError:
            self.logger().warning("Expected subkeys not found in hive file: {}".format(regkey))

        self.logger().debug("TaskCache Keys parsing finished")
        return []

    def convert_hex_dates(self, binary_stirng):
        task_created = parse_windows_timestamp(int.from_bytes(binary_stirng[4:12], byteorder='little'))
        last_executed = parse_windows_timestamp(int.from_bytes(binary_stirng[12:20], byteorder='little'))
        return task_created, last_executed


class TaskFolder(base.job.BaseModule):

    def run(self, path=""):
        """ Prints prefetch info from folder

        """
        print("Product Info|File Version|UUID|Maximum Run Time|Exit Code|Status|Flags|Date Run|Running Instances|Application|Working Directory|User|Comment|Scheduled Date")

        for fichero in os.listdir(path):
            if fichero.endswith(".job"):
                data = ""
                with open(os.path.join(path, fichero), "rb") as f:
                    data = f.read()
                job = jobparser.Job(data)
                print("{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}".format(jobparser.products.get(job.ProductInfo), job.FileVersion, job.UUID, job.MaxRunTime, job.ExitCode, jobparser.task_status.get(job.Status, "Unknown Status"),
                                                                         job.Flags_verbose, job.RunDate, job.RunningInstanceCount, "{} {}".format(job.Name, job.Parameter), job.WorkingDirectory, job.User, job.Comment, job.ScheduledDate))
