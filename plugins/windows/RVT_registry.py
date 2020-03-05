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
from collections import defaultdict
from regipy.registry import RegistryHive
from tqdm import tqdm

from plugins.common.RVT_files import GetFiles
from base.utils import check_directory
import base.job


class RegistryDump(base.job.BaseModule):

    def run(self, path=""):
        """ Dumps all registry in json format """

        regfiles = self.get_hive_files(path)

        # Parse a single registry hive if path is supllied
        if isinstance(regfiles, str):
            self.logger().debug('Parsing {}'.format(path))
            for i in self.parse_hive(path, path.split('/')[-1].split('.')[0].lower()):
                yield i
            return []

        # Parse all registry hives
        for hive in tqdm(regfiles, total=len(regfiles), desc=self.section):
            if hive == "ntuser" or hive == "usrclass":
                for usr, h in regfiles[hive].items():
                    self.logger().debug('Parsing {}'.format(h))
                    for i in self.parse_hive(h, hive, usr):
                        yield i
            else:
                self.logger().debug('Parsing {}'.format(regfiles[hive]))
                for i in self.parse_hive(regfiles[hive], hive):
                    yield i

        self.logger().info('Registry parsed')
        return []

    def parse_hive(self, hive_file, hive_name, user=''):
        reg = RegistryHive(hive_file)
        for d in reg.recurse_subkeys(as_json=True):
            data = {}
            data.update({
                'timestamp': d.timestamp,
                'hive_name': hive_name,
                'path': d.path,
                'subkey': d.subkey_name,
            })

            if user:
                data['user'] = user

            if not d.values:
                yield data
                continue

            data['values_count'] = d.values_count

            # Store a list of dictionaries as values
            data['values'] = []
            for v in d.values:
                name = v['name'].lstrip('(').rstrip(')')
                value_type = 'bytes' if v['value_type'] == 'REG_BINARY' else 'strings'
                data['values'].append({'value': name, 'data.{}'.format(value_type): v['value']})

            yield data

    def get_hive_files(self, path):
        """ Retrieves all hives found in source if path is not specified.

            Attrs:
                path: path to registry hive
        """
        if path:
            if os.path.exists(path):
                return path
            else:
                raise base.job.RVTError('path {} does not exist'.format(path))

        check_directory(self.myconfig('mountdir'), error_missing=True)

        regfiles = {}

        Find = GetFiles(self.config, vss=self.myflag("vss"))

        for main_hive in ['SYSTEM', 'SOFTWARE', 'SAM', 'SECURITY']:
            for item in Find.search("/Windows/System32/config/{}$".format(main_hive)):
                hive = item.split('/')[-1].lower()
                if hive not in regfiles:  # Get only the first hit
                    regfiles[hive] = os.path.join(self.myconfig('casedir'), item)

        if "software" not in regfiles.keys():
            self.logger().warning('No SOFTWARE hive found in source')
            return {}

        NTUSER = Find.search(r"/(Documents and settings|users)/.*/(NTUSER|UsrClass)\.dat$")

        usr = defaultdict(list)
        regfiles["ntuser"] = {}
        regfiles["usrclass"] = {}

        for item in NTUSER:
            aux = re.search("(Documents and settings|Users)/([^/]*)/", item, re.I)
            user = aux.group(2)
            hive_name = 'ntuser' if item.lower().endswith("ntuser.dat") else 'usrclass'
            if user not in usr[hive_name]:
                usr[hive_name].append(user)
            else:  # Get only the first hit
                continue
            if hive_name == "ntuser":
                regfiles["ntuser"][user] = os.path.join(self.myconfig('casedir'), item)
            else:
                regfiles["usrclass"][user] = os.path.join(self.myconfig('casedir'), item)

        amcache = list(Find.search("/Windows/AppCompat/Programs/Amcache.hve"))
        if len(amcache) != 0:
            regfiles["amcache"] = os.path.join(self.myconfig('casedir'), amcache[0])
        syscache = list(Find.search(r"/syscache.hve$"))
        if len(syscache) != 0:
            regfiles["syscache"] = os.path.join(self.myconfig('casedir'), syscache[0])

        return regfiles
