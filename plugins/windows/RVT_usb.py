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
from collections import OrderedDict, Counter
import base.job
from base.utils import save_csv, check_directory
from plugins.common.RVT_files import GetFiles


class USBSetupAPI(base.job.BaseModule):

    def read_config(self):
        super().read_config()
        self.set_default_config('volume_id', None)
        self.set_default_config('outdir', self.config.config['plugins.windows']['usbdir'])

    def run(self, path=""):
        """ Extracts USB drives data about drivers installation from setupapi.dev.log

            Arguments:
                ** path ** (str): path to setupapi.dev.log file. If this argument is not provided,
                                  all files with this pattern will be searched in allocated files.
        """

        outdir = self.myconfig('outdir')
        check_directory(outdir, create=True)

        # Case when path is provided
        if path:
            if not os.path.exists(path):
                self.logger().warning('Provided path does not exist: {}'.format(path))
                return []
            self.logger().debug('Extracting USB devices information from {}'.format(path))
            partition = self.myconfig('volume_id')
            output_file = os.path.join(outdir, "usb_setupapi{}.csv".format('_{}'.format(partition) if partition else ''))
            save_csv(self.parse_setupapi(path), outfile=output_file, file_exists='OVERWRITE')
            if os.path.getsize(output_file) == 0:  # Remove unnecessary empty files
                os.remove(output_file)
            return []

        # Search in allocfiles if path is not provided
        search = GetFiles(self.config)
        setupapi = search.search(r"setupapi.dev.log$")
        if len(setupapi) < 1:
            self.logger().warning("File setupapi.dev.log not found")
            return []

        files_by_partition = Counter()
        for i, setupapi_file in enumerate(setupapi):
            self.logger().debug('Extracting USB devices information from {}'.format(setupapi_file))
            setupapi_path = os.path.join(self.myconfig('casedir'), setupapi_file)
            if not os.path.isfile(setupapi_path):
                self.logger().warning("{} does not exist. Try to mount disk's partition.".format(setupapi_path))
                continue

            # Set a name for the output file based on the partition is found
            partition = setupapi_file.split('/')[2]  # allocfiles format: source/mnt/pXX/path
            files_in_partition = files_by_partition[partition]
            output_file = os.path.join(outdir, "usb_setupapi_{}{}.csv".format(partition, '_{}'.format(files_in_partition) if files_in_partition else ''))
            files_by_partition[partition] += 1

            self.logger().debug('Saving output in {}'.format(output_file))
            save_csv(self.parse_setupapi(setupapi_path), outfile=output_file, file_exists='OVERWRITE')
            # Remove unnecessary empty files
            if os.path.getsize(output_file) == 0:
                os.remove(output_file)

        return []

    def parse_setupapi(self, setupapi_file):
        """ Extracts USB sticks' data about drivers installation

        Args:
            setupapi_file (str): path to setupapi.dev.log file
        """

        with open(setupapi_file, "r", encoding="cp1252") as file:
            regex = re.compile(r'>>>\s\s\[Device\sInstall\s\(Hardware\sinitiated\) - (.*USBSTOR.*)\]', re.I)
            regexstart = re.compile(r'>>>\s+Section start ([\d /:.]+)')
            regex1 = re.compile(r"\s+(ump|cmd):\s+(.*)")
            regex2 = re.compile(r"\s+dvi:\s+(HardwareID|DevDesc|DrvDesc|Provider|Signer|DrvDate|Version)\s+-\s+(.*)")
            regexend = re.compile(r'<<<\s+Section end ([\d /:.]+)')

            for line in file:
                aux = regex.search(line)
                if aux:
                    a = OrderedDict([("Device", aux.group(1)), ("Start", ""), ("End", ""), ("UMP", ""),
                                    ("HardwareID", ""), ("DevDesc", ""), ("DrvDesc", ""), ("Provider", ""),
                                    ("Signer", ""), ("DrvDate", ""), ("Version", ""), ("Status", "")])

                    line = file.readline()
                    a["Start"] = regexstart.search(line).group(1)
                    while True:
                        line = file.readline()
                        aux = regex1.search(line)
                        if aux and a["UMP"] == "":
                            a["UMP"] = aux.group(2)
                            continue
                        aux = regex2.search(line)
                        if aux and a[aux.group(1)] == "":
                            a[aux.group(1)] = aux.group(2)
                            continue
                        aux = regexend.search(line)
                        if aux:
                            a["End"] = aux.group(1)
                            line = file.readline()
                            if line.find("SUCCESS") > 0:
                                a["Status"] = "SUCCESS"
                            else:
                                a["Status"] = "ERROR"
                            break

                    yield a


class USBAnalysis(base.job.BaseModule):
    # TODO : recap different Usb sources and create a report
    pass
