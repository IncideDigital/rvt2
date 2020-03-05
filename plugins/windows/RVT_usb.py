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
from collections import OrderedDict
import base.job
from base.utils import save_csv, check_directory
from plugins.common.RVT_files import GetFiles


class USBSetupAPI(base.job.BaseModule):

    def run(self, path=""):
        vss = self.myflag('vss')
        outdir = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(outdir, create=True)

        search = GetFiles(self.config, vss=self.myflag("vss"))
        setupapi = search.search(r"setupapi.dev.log$")

        if len(setupapi) < 1:
            self.logger().warning("File setupapi.dev.log not found")
            return []

        for setupapi_file in setupapi:
            self.logger().info('Extracting USB devices information from {}'.format(setupapi_file))
            folders = setupapi_file.split('/')
            partition = folders[2]
            if not vss:
                output_file = os.path.join(outdir, "{}_usb_setupapi.csv".format(partition))
                setupapi_path = os.path.join(self.myconfig('casedir'), setupapi_file)
                if not os.path.isfile(setupapi_path):
                    self.logger().warning("{} does not exist. Try to mount disk's partition.".format(setupapi_path))
                    continue
                save_csv(self.parse_setupapi(setupapi_path, partition), outfile=output_file)
                if os.path.getsize(output_file) == 0:
                    os.remove(output_file)
            else:
                vpartitions = [v for v in os.listdir(self.myconfig('mountdir')) if v.startswith('v') and v.find(partition) != -1]
                for vpart in vpartitions:
                    output_file = os.path.join(outdir, "{}_usb_setupapi.csv".format(vpart))
                    setupapi_path = os.path.join(self.myconfig('casedir'), '/'.join(folders[:2]), vpart, '/'.join(folders[3:]))
                    if not os.path.isfile(setupapi_path):
                        self.logger().warning("{} does not exist in vss partition {}.".format(setupapi_path, vpart))
                        continue
                    save_csv(self.parse_setupapi(setupapi_path, vpart), outfile=output_file)
                    if os.path.getsize(output_file) == 0:
                        os.remove(output_file)

        return []

    def parse_setupapi(self, setupapi_file, partition):
        """ Extracts USB sticks' data about drivers installation

        Args:
            setupapi_file (str): path to setupapi.dev.log file
            partition (str): partition identifier (ex: 'p05')
        """
        self.logger().info("Parsing setupapi.dev.log for partiton {}".format(partition))

        with open(setupapi_file, "r", encoding="cp1252") as file:
            regex = re.compile(r'>>>\s\s\[Device\sInstall\s\(Hardware\sinitiated\) - (.*USBSTOR.*)\]', re.I)
            regexstart = re.compile(r'>>>\s+Section start ([\d/:.]+)')
            regex1 = re.compile(r"\s+(ump|cmd):\s+(.*)")
            regex2 = re.compile(r"\s+dvi:\s+(HardwareID|DevDesc|DrvDesc|Provider|Signer|DrvDate|Version)\s+-\s+(.*)")
            regexend = re.compile(r'<<<\s+Section end ([\d\s/:.]+)')

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

        self.logger().info("Done parsing setupapi_file for partiton {}".format(partition))


class USBAnalysis(base.job.BaseModule):
    # TODO : recap different Usb sources and create a report
    pass
