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

import base.job
from plugins.common.RVT_disk import getSourceImage

""" Modules to mount or umount all partitions in a source."""


class Mount(base.job.BaseModule):
    """ Mount all partitions in a disk and then run from_module.

    Configuration:
        - **partitions** (str): comma separated list of partitions to mount (ex: p03,p05,v1p05). All non vss partitions by default
        - **recovery_keys** (str): comma separated list of recovery keys for encrypted partition
        - **ntfs_args** (str): specific options for mounting an NTFS partition.
        - **fat32_args** (str): specific options for mounting a FAT32 partition.
        - **ext4_args** (str): specific options for mounting an EXT4 partition.
        - **hfs_args** (str): specific options for mounting an HFS partition.
        - **vss** (bool): mount regular (False) or Volume Shadow Snapshots (True) partitions
        - **nbd_device** (str): for VMDX images (nbd), the device to use.
        - **remove_info** (bool): if True, remove previous information gathered about disk. Use this if any error occurs
    """
    def run(self, path=None):
        """ If path is provided, it is an abolsolute path to the image to mount.
        If not, search imagedir for available images """
        disk = getSourceImage(self.myconfig, imagefile=path)
        disk.mount(partitions=self.myconfig('partitions'), vss=self.myconfig('vss'), unzip_path=self.myconfig('unzip_path'))
        if self.from_module:
            for data in self.from_module.run(path):
                yield data


class UMount(base.job.BaseModule):
    """ Run from_module and then umount all partitions in a disk.

    """
    def run(self, path=None):
        """ If path is provided, it is an abolsolute path to the image to unmount.
        If not, search imagedir for available images """
        if self.from_module:
            for data in self.from_module.run(path):
                yield data
        disk = getSourceImage(self.myconfig, imagefile=path)
        disk.umount()
        return []
