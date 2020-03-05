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
from base.utils import check_folder
from base.commands import run_command
import base.job


class Timelines(base.job.BaseModule):
    """
    Generates timeline and body files for a disk and its VSS (if set)

    Configuration:
        - **vss**: If True, generate timelines and body files for the VSS, not the main disk (only useful on Windows systems)
        - **fls**: Path to the fls app (TSK)
        - **apfs_fls**: Path to a fls app with APFS support (TSK>?)
        - **mactime**: Path to the mactime app (TSK)
    """

    def run(self, path=None):
        """ The path is ignored, and the source image is used. """
        vss = self.myflag('vss')
        fls = self.myconfig('fls', 'fls')
        apfs_fls = self.myconfig('apfs_fls', 'fls')
        mactime = self.myconfig('mactime', 'mactime')

        disk = getSourceImage(self.myconfig)

        tl_path = self.myconfig('outdir')
        if vss:
            tl_path = self.myconfig('voutdir')

        check_folder(tl_path)

        if not vss:
            self.logger().info("Generating BODY file for %s", disk.disknumber)
            body = os.path.join(tl_path, "{}_BODY.csv".format(disk.disknumber))

            # create the body file
            with open(body, "wb") as f:
                for p in disk.partitions:
                    mountpath = base.utils.relative_path(p.mountpath, self.myconfig('casedir'))

                    if not p.isMountable:
                        continue
                    if not disk.sectorsize:
                        # unkwown sector size
                        run_command([fls, "-s", "0", "-m", mountpath, "-r", "-o", str(p.osects), "-i", "raw", disk.imagefile], stdout=f, logger=self.logger())
                    elif p.filesystem == "NoName":
                        # APFS filesystems are identified as NoName, according to our experience
                        try:
                            run_command([apfs_fls, "-B", str(p.block_number), "-s", "0", "-m", mountpath, "-r", "-o", str(p.osects), "-b", str(disk.sectorsize), "-i", "raw", disk.imagefile], stdout=f, logger=self.logger())
                        except Exception:
                            # sometimes, APFS filesystems report a wrong offset. Try again with offset*8
                            run_command([apfs_fls, "-B", str(p.block_number), "-s", "0", "-m", mountpath, "-r", "-o", str(p.osects * 8), "-b", str(disk.sectorsize), "-i", "raw", disk.imagefile], stdout=f, logger=self.logger())
                    else:
                        # we know the sector size
                        if p.encrypted:
                            run_command([fls, "-s", "0", "-m", mountpath, "-r", "-b", str(disk.sectorsize), p.loop], stdout=f, logger=self.logger())
                        else:
                            run_command([fls, "-s", "0", "-m", mountpath, "-r", "-o", str(p.osects), "-b", str(disk.sectorsize), disk.imagefile], stdout=f, logger=self.logger())

            # create the timeline using mactime
            self.logger().info("Creating timeline of {}".format(disk.disknumber))
            hsum = os.path.join(tl_path, "%s_hour_sum.csv" % disk.disknumber)
            fcsv = os.path.join(tl_path, "%s_TL.csv" % disk.disknumber)
            with open(fcsv, "wb") as f:
                run_command([mactime, "-b", body, "-m", "-y", "-d", "-i", "hour", hsum], stdout=f, logger=self.logger())
            run_command(['sed', '-i', '1,2d', hsum])  # Delete header because full path is included
        else:
            # generate body and timeline for each VSS in the disk
            for p in disk.partitions:
                for v, dev in p.vss.items():
                    if dev != "":
                        self.logger().info("Generating BODY file for {}".format(v))
                        body = os.path.join(tl_path, "{}_BODY.csv".format(v))

                        with open(body, "wb") as f:
                            mountpath = base.utils.relative_path(p.mountpath, self.myconfig('casedir'))
                            run_command([fls, "-s", "0", "-m", "%s" % mountpath, "-r", dev], stdout=f, logger=self.logger())

                        self.logger().info("Creating timeline for {}".format(v))
                        hsum = os.path.join(tl_path, "%s_hour_sum.csv" % v)
                        fcsv = os.path.join(tl_path, "%s_TL.csv" % v)
                        with open(fcsv, "wb") as f:
                            run_command([mactime, "-b", body, "-m", "-y", "-d", "-i", "hour", hsum], stdout=f, logger=self.logger())
                        run_command(['sed', '-i', '1,2d', hsum])  # Delete header because full path is included

        self.logger().info("Timelines generation done!")
        return []
