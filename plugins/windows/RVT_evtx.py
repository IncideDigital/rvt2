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
from plugins.common.RVT_disk import getSourceImage
from plugins.common.RVT_files import GetFiles
from base.utils import check_directory, check_file
import base.job
from base.commands import run_command


class Evtx(base.job.BaseModule):
    """ Parses evtx from disk """
    def run(self, path=""):
        self.vss = self.myflag('vss')

        if not self.vss:
            evtx_path = self.myconfig('outdir')
            self.generate(evtx_path)
        else:
            disk = getSourceImage(self.myconfig)
            evtx_path = self.myconfig('voutdir')
            for p in disk.partitions:
                for v, mp in p.vss.items():
                    if mp != "":
                        self.generate(os.path.join(evtx_path, v))

        self.logger().info("Evtx Done")
        return []

    def generate(self, evtx_path):
        """ Auxiliary function """

        check_directory(evtx_path, create=True)
        evtx = self.config.get('plugins.common', 'evtxdump', '/usr/local/bin/evtxdump.pl')

        alloc_files = GetFiles(self.config, vss=self.myflag("vss"))
        if self.vss:
            evtx_files = alloc_files.search(r"{}.*\.evtx$".format(evtx_path.split('/')[-1]))
        else:
            evtx_files = alloc_files.search(r"\.evtx$")

        errorlog = self.myconfig('errorlog', os.path.join(self.myconfig('sourcedir'), "{}_aux.log".format(self.myconfig('source'))))

        for i in evtx_files:
            evtx_file = os.path.join(self.myconfig('casedir'), i)
            if not check_file(evtx_file):
                self.logger().warning('File %s does not exist', evtx_file)
                continue
            self.logger().info("Parsing {}".format(i))
            name = os.path.join(evtx_path, os.path.basename(i))[:-4] + "txt"
            
            # if the output already exists, continue
            if check_file(name):
                self.logger().debug('The output file %s ready exists. Skipping', name)
                continue

            with open(name, "wb") as f:
                with open(errorlog, 'a') as logfile:
                    run_command([evtx, evtx_file], stdout=f, stderr=logfile, logger=self.logger())
