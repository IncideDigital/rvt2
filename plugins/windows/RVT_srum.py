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

import base.job
from base.utils import check_directory, check_file
from plugins.common.RVT_files import GetFiles
from base.commands import run_command


class Srum(base.job.BaseModule):

    def run(self, path=""):
        """ Extracts SRUM artifacts of a disk """
        vss = self.myflag('vss')
        SRUM_TEMPLATE = os.path.join(self.myconfig('rvthome'), "plugins/external/srum-dump/SRUM_TEMPLATE2.xlsx")
        srum = os.path.join(self.myconfig('rvthome'), "plugins/external/srum-dump/srum_dump2.py")
        check_file(SRUM_TEMPLATE, error_missing=True)

        Search = GetFiles(self.config, vss=self.myflag("vss"))
        SOFTWARE = list(Search.search('windows/system32/config/SOFTWARE$'))
        SRUDB = list(Search.search('/windows/system32/sru/SRUDB.dat$'))
        python3 = os.path.join(self.myconfig('rvthome'), ".venv/bin/python3")

        out_folder = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(out_folder, create=True)

        if not SRUDB:
            self.logger().info("SRUDB.dat not found in any partition of the disk")
            return []

        for soft in SOFTWARE:
            partition = soft.split('/')[2]
            for srudb in SRUDB:
                if srudb.split('/')[2] == partition:
                    self.logger().info("Parsing SRUDB from partition {}".format(partition))
                    out_file = os.path.join(out_folder, 'srum_{}.xlsx'.format(partition))
                    run_command([python3, srum, "-i", os.path.join(self.myconfig('casedir'), srudb), "-t", SRUM_TEMPLATE,
                                "-r", os.path.join(self.myconfig('casedir'), soft), "-o", out_file], logger=self.logger())

                    self.convert_to_csv(out_folder, partition)
                    os.remove(out_file)
                    break
            else:
                self.logger().info("SRUDB.dat not found in partition: {}".format(partition))

        return []

    def convert_to_csv(self, folder, partition, sheets=''):
        """ Convert xlsx sheets to multiple csv's. """
        if not sheets:
            sheet_names = ['Network Usage', 'Network Connections', 'Application Resource Usage', 'Push Notification Data']
        xslx = openpyxl.load_workbook(os.path.join(folder, 'srum_{}.xlsx'.format(partition)))
        for s in sheet_names:
            sh = xslx.get_sheet_by_name(s)
            with open(os.path.join(folder, '{}_{}.csv'.format(s.replace(" ", ""), partition)), 'w') as out:
                c = csv.writer(out, delimiter=';')
                for r in sh.values:
                    c.writerow(r)
