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
import csv
import openpyxl
import glob
import re

import base.job
from base.utils import check_directory, check_file
from base.commands import run_command


class Srum(base.job.BaseModule):

    def read_config(self):
        super().read_config()
        self.set_default_config('path', '')
        self.set_default_config('software_hive', os.path.join(self.config.config['DEFAULT']['mountdir'], 'p*/[Ww]indows/[Ss]ystem32/[Cc]onfig/SOFTWARE'))
        self.set_default_config('srum', os.path.join(self.myconfig('rvthome'), "plugins/external/srum-dump/srum_dump2.py"))

    def run(self, path=""):
        """ Extracts SRUM artifacts of a disk """
        srum = self.myconfig('srum')
        SRUM_TEMPLATE = os.path.join(self.myconfig('rvthome'), "plugins/external/srum-dump/SRUM_TEMPLATE3.xlsx")
        check_file(SRUM_TEMPLATE, error_missing=True)

        # Check path to SRUDB and partition
        try:
            self.check_params(path, check_path=True, check_path_exists=True)
        except Exception:
            self.logger().warning('Provided path {} does not exist. Please provide file SRUDB.dat'.format(path))
            return []
        partition_path = re.search(r'.*/(p\d+).*', path)
        if partition_path:
            partition = partition_path.group(1)
        else:
            partition = 'p01'

        # Obtain SOFTWARE hive for the same partition
        software_glob = r'{}'.format(self.myconfig('software_hive'))
        software = sorted(glob.iglob(software_glob))
        if not software:
            self.logger().warning('SOFTWARE hive not found matching {}. SRUM parsing requires this hive'.format(software_glob))
            return []
        elif len(software) > 1:
            if not partition_path:
                self.logger().warning('Unable to relate SRUDB to a partition')
                return []
            for s in software:
                partition_hive = re.search(r'.*/(p\d+).*', s)
                if partition_hive and partition_hive.group(1) == partition:
                    software_hive = s
                    break
            else:
                self.logger().warning('Unable to relate SRUDB to a partition')
                return []
        else:
            software_hive = software[0]

        python3 = os.path.join(self.myconfig('rvthome'), ".venv/bin/python3")
        out_folder = self.myconfig('outdir')
        check_directory(out_folder, create=True)
        out_file = os.path.join(out_folder, 'srum_{}.xlsx'.format(partition))

        # Use srum_dump to parse SRUM
        self.logger().debug('Parsing SRUM file {}'.format(path))
        run_command([python3, srum, "-i", path, "-t", SRUM_TEMPLATE,
                     "-r", software_hive, "-o", out_file], logger=self.logger())

        # Transform the output xlsx to csv format
        self.convert_to_csv(out_folder, partition)
        os.remove(out_file)

        return []

    def convert_to_csv(self, folder, partition, sheets=''):
        """ Convert xlsx sheets to multiple csv's. """
        if not sheets:
            sheet_names = ['Network Data Usage', 'Network Connectivity Usage', 'Application Resource Usage', 'Windows Push Notifications']
        xslx = openpyxl.load_workbook(os.path.join(folder, 'srum_{}.xlsx'.format(partition)))
        for s in sheet_names:
            sh = xslx.get_sheet_by_name(s)
            with open(os.path.join(folder, '{}_{}.csv'.format(s.replace(" ", ""), partition)), 'w') as out:
                c = csv.writer(out, delimiter=';')
                for r in sh.values:
                    c.writerow(r)
