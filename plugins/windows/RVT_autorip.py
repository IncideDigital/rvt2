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
import logging
import json
from tqdm import tqdm

from base.utils import check_directory
from base.commands import run_command
from plugins.windows.RVT_hives import get_hives
import base.job


def write_registry_file(filename, pluginlist, hivedict, regfiles, rip='/opt/regripper/rip.pl', logger=logging, logfile=None, separator="." * 105):
    """ Generates a report file for a group of related regripper plugins.

    Parameters:
        filename (str): report filename
        pluginlist (list): list of plugins to execute
        hivedict (dict): relates plugin to hive files
        regfiles (list): list of hive files paths
        rip (str): path to rip.pl executable
        logger (logging): logging instance
        logfile (file): stream related to logfile
    """

    with open(filename, "a") as f:
        for plugin in pluginlist:
            if hivedict[plugin] == ["all"]:
                hivedict[plugin] = ["system", "software", "sam", "ntuser", "usrclass"]
            for hiv in hivedict[plugin]:
                try:
                    if hiv not in regfiles.keys():
                        continue
                    if hiv == "ntuser" or hiv == "usrclass":
                        for user in regfiles[hiv].keys():
                            if not regfiles[hiv][user]:
                                continue
                            f.write("\n************* Extracting from User {} *************\n\n".format(user))
                            output = run_command([rip, "-r", regfiles[hiv][user], "-p", plugin], stderr=logfile, logger=logger)
                            f.write("{}\n".format(output))
                    else:
                        output = run_command([rip, "-r", regfiles[hiv], "-p", plugin], stderr=logfile, logger=logger)
                        f.write(output)
                    f.write("\n\n{}\n\n".format(separator))
                except Exception as exc:
                    logger.error(exc)
                    continue


class Autorip(base.job.BaseModule):
    """ Uses multiple regripper plugins to parse the Windows registry and create a series of reports organized by theme.

    Configuration:
        - **path**: Hives location directory. Expected inputs:
            - Directory where registry hive files are stored, such as 'Windows/System32/config/' or 'Windows/AppCompat/Programs/'
            - Main volume directory --> Root directory, where 'Documents and Settings' or 'Users' folders are expected
            - Custom folder containing hives. Warning: 'ntuser.dat' are expected to be stored in a username folder.
        - **outdir**: output directory for generated files
        - **errorfile**: path to log file to register regripper errors
        - **ripplugins**: path to json file containing the organized list of regripper plugins to run
        - **pluginshives**: path to json file associating each regripper plugin with a list of hives
        - **volume_id**: volume identifier, such as partition number. Ex: 'p03'
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('rip', '/opt/regripper/rip.pl')
        self.set_default_config('pluginshives', os.path.join(self.config.config['windows']['plugindir'], 'regripper_plugins.json'))
        self.set_default_config('ripplugins', os.path.join(self.config.config['windows']['plugindir'], 'autorip.json'))
        self.set_default_config('errorfile', os.path.join(self.myconfig('sourcedir'), "{}_aux.log".format(self.myconfig('source'))))
        self.set_default_config('volume_id', 'p01')

    def run(self, path=""):
        """ Main function to generate report files """

        if not path:
            path = self.myconfig('path', '')
        regfiles = get_hives(path)
        id = self.myconfig('volume_id', None)
        self.generate_registry_output(regfiles, id)
        return []

    def generate_registry_output(self, regfiles, id=None):
        """ Generates registry output files for a partition

        Arguments:
            id (str): Volume identifier, such as partition number. Ex: 'p03'
        """

        if not regfiles:
            raise base.job.RVTError('No valid registry hives provided')

        output_path = self.myconfig('outdir')
        check_directory(output_path, create=True)

        # Get the hives associated with each plugin
        pluginshives = self.myconfig('pluginshives')
        with open(pluginshives, 'r') as f:
            hivedict = json.load(f)

        # Get the files destination for output
        ripplugins_file = self.myconfig('ripplugins')
        with open(ripplugins_file) as rf:
            ripplugins = json.load(rf)

        rip = self.myconfig('rip')
        errorlog = self.myconfig('errorfile')

        # Write output
        with open(errorlog, 'a') as logfile:
            for ar in tqdm(ripplugins, total=len(ripplugins), desc=self.section):
                output_filename = os.path.join(output_path, '{}{}.txt'.format(ar['file'], '_{}'.format(id) if id else ''))
                self.logger().debug('Writing {}'.format(output_filename))
                write_registry_file(output_filename, ar['plugins'], hivedict,
                                    regfiles, rip, logger=self.logger(), logfile=logfile)

        return []
