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
import logging
import json
from tqdm import tqdm

from plugins.common.RVT_files import GetFiles
from base.utils import check_folder, check_directory
from base.commands import run_command
import base.job


def write_registry_file(filename, pluginlist, hivedict, title, regfiles, rip='/opt/regripper/rip.pl', logger=logging, logfile=None):
    """ Generates a report file for a group of related regripper plugins.

    Parameters:
        filename (str): report filename
        pluginlist (list): list of plugins to execute
        hivedict (dict): relates plugin to hive files
        title (str): title of report file
        regfiles (list): list of hive files paths
        rip (str): path to rip.pl executable
        logger (logging): logging instance
        logfile (file): stream related to logfile
    """

    separator = "=" * 105

    with open(filename, "w") as f:
        f.write("{}\n{}\n{}\n\n".format(separator, title, separator))
        for plugin in pluginlist:
            if hivedict[plugin] == ["all"]:
                hivedict[plugin] = ["system", "software", "sam", "ntuser", "usrclass"]
            for hiv in hivedict[plugin]:
                try:
                    if hiv == "ntuser" or hiv == "usrclass":
                        for user in regfiles[hiv].keys():
                            if not regfiles[hiv][user]:
                                continue
                            f.write("\n************* Extracting from User {} *************\n\n".format(user))
                            output = run_command([rip, "-r", regfiles[hiv][user], "-p", plugin], stderr=logfile, logger=logger)
                            f.write("{}\n".format(output))
                    else:
                        if hiv not in regfiles.keys():
                            continue
                        output = run_command([rip, "-r", regfiles[hiv], "-p", plugin], stderr=logfile, logger=logger)
                        f.write(output)
                    f.write("\n\n{}\n\n".format('.' * 107))
                except Exception as exc:
                    logger.error(exc)
                    continue


class Autorip(base.job.BaseModule):
    """ Uses multiple regripper plugins to parse the Windows registry and create a series of reports organized by theme.

    Configuration:
        - **outdir**: output directory for generated files
        - **voutdir**: output directory for generated files in case of Volume Snapshots (vss)
        - **errorfile**: path to log file to register regripper errors
        - **ripplugins**: path to json file containing the organixed list of regripper plugins to run
        - **pluginshives**: path to json file associating each regripper plugin with a list of hives
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('rip', '/opt/regripper/rip.pl')
        self.set_default_config('pluginshives', os.path.join(self.config.config['windows']['plugindir'], 'regripper_plugins.json'))
        self.set_default_config('ripplugins', os.path.join(self.config.config['windows']['plugindir'], 'autorip.json'))
        self.set_default_config('errorfile', os.path.join(self.myconfig('sourcedir'), "{}_aux.log".format(self.myconfig('source'))))

    def run(self, path=""):
        """ Main function to generate report files """
        vss = self.myflag('vss')
        check_directory(self.myconfig('mountdir'), error_missing=True)

        for p in os.listdir(self.myconfig('mountdir')):
            # parse only partition directories
            if (p.startswith('p') and not vss) or (p.startswith('v') and vss):
                regfiles = self.get_hives(p)
                self.generate_registry_output(p, regfiles)
        return []

    def get_hives(self, p):
        """ Obtain the paths to registry hives

        Arguments:
            p (str): partition number. Ex: 'p03'
        """
        regfiles = {}

        Find = GetFiles(self.config, vss=self.myflag("vss"))

        for item in Find.search("{}/Windows/System32/config/(SYSTEM|SOFTWARE|SAM|SECURITY)$".format(p)):
            hive = item.split('/')[-1].lower()
            regfiles[hive] = os.path.join(self.myconfig('casedir'), item)

        if "software" not in regfiles.keys():
            self.logger().warning('SOFTWARE hive not found in partition {}. Skipping this partition'.format(p))
            return {}

        NTUSER = Find.search(r"{}/(Documents and settings|users)/.*/(NTUSER|UsrClass)\.dat$".format(p))

        usr = []
        regfiles["ntuser"] = {}
        regfiles["usrclass"] = {}

        for item in NTUSER:
            aux = re.search("(Documents and settings|Users)/([^/]*)/", item, re.I)
            user = aux.group(2)
            if user not in usr:
                usr.append(user)
                regfiles["ntuser"][user] = ""
                regfiles["usrclass"][user] = ""
            if item.lower().endswith("ntuser.dat"):
                regfiles["ntuser"][user] = os.path.join(self.myconfig('casedir'), item)
            else:
                regfiles["usrclass"][user] = os.path.join(self.myconfig('casedir'), item)

        amcache = list(Find.search("{}/Windows/AppCompat/Programs/Amcache.hve".format(p)))
        if len(amcache) != 0:
            regfiles["amcache"] = os.path.join(self.myconfig('casedir'), amcache[0])
        syscache = list(Find.search(r"{}.*/syscache.hve$".format(p)))
        if len(syscache) != 0:
            regfiles["syscache"] = os.path.join(self.myconfig('casedir'), syscache[0])

        return regfiles

    def generate_registry_output(self, p, regfiles):
        """ Generates registry output files for a partition

        Arguments:
            p (str): partition number. Ex: 'p03'
        """
        if not regfiles:
            return []

        output_path = self.myconfig('outdir')
        if p.startswith('v'):  # vshadow partition
            output_path = os.path.join(self.myconfig('voutdir'), os.path.basename(p))
        check_folder(os.path.join(output_path))

        # Get the hives associated with each plugin
        pluginshives = self.myconfig('pluginshives')
        with open(pluginshives, 'r') as f:
            hivedict = json.load(f)

        rip = self.myconfig('rip')

        ripplugins_file = self.myconfig('ripplugins')
        with open(ripplugins_file) as rf:
            ripplugins = json.load(rf)

        errorlog = self.myconfig('errorfile')
        with open(errorlog, 'a') as logfile:
            for ar in tqdm(ripplugins, total=len(ripplugins), desc=self.section):
                self.logger().info('Writing {}_{}.txt'.format(ar['file'], p))
                write_registry_file(os.path.join(output_path, '{}_{}.txt'.format(ar['file'], p)), ar['plugins'], hivedict, ar['description'],
                                    regfiles, rip, logger=self.logger(), logfile=logfile)

        return []
