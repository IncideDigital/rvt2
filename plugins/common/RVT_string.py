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

import base.job
from plugins.common.RVT_disk import getSourceImage
from base.utils import check_directory
from base.commands import yield_command
from tqdm import tqdm


class StringGenerate(base.job.BaseModule):

    def __init__(self, *args, disk=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.disk = disk
        if disk is None:
            self.disk = getSourceImage(self.myconfig)
        self.string_path = self.myconfig('outdir')
        check_directory(self.string_path, create=True)

    def run(self, path=""):

        self.generate_strings()
        return []

    def generate_strings(self):
        """ Generates strings of disk partitions"""

        srch_strings = self.myconfig('srch_strings', 'srch_strings')
        tr = self.myconfig('tr', 'tr')
        dd = self.myconfig('dd', 'dd')
        mmcat = self.myconfig('mmcat', 'mmcat')

        for p in self.disk.partitions:
            if p.filesystem.startswith("Primary Table"):
                continue

            srch_params = {"ASCII": "-a -t d", "UNICODE": "-a -t d -e l"}

            self.logger().info("Generating ASCII and UNICODE for {}, partition p{}".format(self.disk.disknumber, p.partition))
            if p.isMountable:
                output_file_name = os.path.join(self.string_path, "p{}_strings".format(p.partition))
            else:
                output_file_name = os.path.join(self.string_path, "p{}_strings_unalloc".format(p.partition))

            sectorsize = 512
            if self.disk.sectorsize:
                sectorsize = self.disk.sectorsize

            if "/dev/dislocker" in p.fuse.keys():
                cmd = "{} if={} bs={} 2>/dev/null | {} {} | {} /A-Z/ /a-z/".format(dd, p.fuse["/dev/dislocker"], sectorsize, srch_strings, srch_params['ASCII'], tr)
                cmd2 = "{} if={} bs={} 2>/dev/null | {} {} | {} /A-Z/ /a-z/".format(dd, p.fuse["/dev/dislocker"], sectorsize, srch_strings, srch_params['UNICODE'], tr)
            elif self.disk.imagetype in ("aff", "aff4", "encase"):
                cmd = "{} {} {} 2>/dev/null | {} {} | {} /A-Z/ /a-z/".format(mmcat, self.disk.imagefile, p.partition, srch_strings, srch_params['ASCII'], tr)
                cmd2 = "{} {} {} 2>/dev/null | {} {} | {} /A-Z/ /a-z/".format(mmcat, self.disk.imagefile, p.partition, srch_strings, srch_params['UNICODE'], tr)
            else:
                cmd = "{} if={} skip={} count={} bs={} 2>/dev/null | {} {} | {} /A-Z/ /a-z/".format(dd, self.disk.imagefile, p.osects, int(
                    int(p.size) / int(sectorsize)), sectorsize, srch_strings, srch_params['ASCII'], tr)
                cmd2 = "{} if={} skip={} count={} bs={} 2>/dev/null | {} {} | {} /A-Z/ /a-z/".format(dd, self.disk.imagefile, p.osects, int(
                    int(p.size) / int(sectorsize)), sectorsize, srch_strings, srch_params['UNICODE'], tr)

            with open('{}.asc'.format(output_file_name), 'w') as f:
                self._save_command(cmd, f, p)
            with open('{}.uni'.format(output_file_name), 'w') as f:
                self._save_command(cmd2, f, p, encoding='UNICODE')

        self.logger().debug("Strings generated")

    def _save_command(self, cmd, outfile, partition, encoding='ASCII'):
        """ Save the results of a command to a file, showing a progress bar.

        Parameters:
            cmd (str): Command to run
            outfile (file object): Stream where stdout goes to
            partition (obj): partition object
        """
        self.logger().debug('Generating {} strings for partition {}'.format(encoding, 'p{}'.format(partition.partition)))
        # sectorsize = self.disk.sectorsize if self.disk.sectorsize else 512
        old_offset = offset = 0

        with tqdm(total=int(partition.size), desc='{} strings generation {}'.format(encoding, 'p{}'.format(partition.partition))) as pbar:
            for line in yield_command(cmd, logger=self.logger()):
                outfile.write(line)
                offset = int(line[:10])
                advance = offset - old_offset
                pbar.update(advance)
                old_offset = offset
            pbar.update(int(partition.size) - offset)
