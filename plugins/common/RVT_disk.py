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

"""

Manages images

"""

import os
import re
import subprocess
import pytsk3
from plugins.common.RVT_partition import Partition
import logging
from base.utils import check_folder, check_file
from base.commands import run_command
import base.job
import zipfile
from tqdm import tqdm
import shutil

__maintainer__ = 'Juan Vera'


def getSourceImage(myconfig):
    # Try to scan 'imagefile' first if supplied
    imagefile = myconfig('imagefile')
    if imagefile:
        check_file(imagefile, error_missing=True)
        try:
            ext = os.path.basename(imagefile).split('.')[-1]
            return KNOWN_IMAGETYPES[ext]['imgclass'](imagefile=imagefile, imagetype=KNOWN_IMAGETYPES[ext]['type'], params=myconfig)
        except KeyError:
            raise base.job.RVTError('Image file {} has unrecognized image extension format: {}'.format(imagefile, ext))

    source = myconfig('source')
    imagedir = myconfig('imagedir')
    for ext in KNOWN_IMAGETYPES.keys():
        ifile = os.path.join(imagedir, "%s.%s" % (myconfig('source'), ext))
        if check_file(ifile):
            return KNOWN_IMAGETYPES[ext]['imgclass'](imagefile=ifile, imagetype=KNOWN_IMAGETYPES[ext]['type'], params=myconfig)
    logging.warning('Image file not found for source=%s in imagedir=%s', source, imagedir)
    return DummyImage(imagefile=None, imagetype='dummy', params=myconfig)


class BaseImage(object):
    """ A base class for images. Also, manages raw (dd) images """
    def __init__(self, imagefile, imagetype, params):
        self.logger = logging.getLogger('Disk')
        self.params = params
        self.morgue = self.params('morgue')
        self.disknumber = self.params('source')  # disknumber
        self.imagefile = imagefile
        self.imagetype = imagetype
        self.sectorsize = None
        self.partitions = []
        self.auxdirectories = []
        self.mmls()

    def exists(self):
        """ Returns True if the disk was found in the morgue. """
        return check_file(self.imagefile)

    def mount(self, partitions=None, vss=False, unzip_path=None):
        """ Mounts partitions of disk
        Args:
            partition (str): partition to be mounted (mounts all available partitions by default)
        Returns:
            bool: False in case of error
        """
        # TODO: partition.mount when vss mounts all vss. It will be desirable to select only one or some of them
        if not partitions:
            parts = self.partitions
        else:
            part_by_name = {''.join(['p', p.partition]): p for p in self.partitions}
            vss_by_name = {v: p for p in self.partitions for v in p.vss}
            parts = []
            try:
                for p in partitions.split(','):
                    if p.startswith('p'):
                        parts.append(part_by_name[p])
                    elif p.startswith('v'):
                        parts.append(vss_by_name[p])
            except KeyError:
                raise base.job.RVTError('Partition name {} not found'.format(p))
        if len(parts) < 1:
            raise base.job.RVTError('No partition set to be mounted')

        for p in parts:
            if p.isMountable or p.filesystem == 'HFS':
                p.mount()

    def umount(self, unzip_path=None):
        """ Unmounts all partitions"""
        # umount data partitions
        for p in self.partitions:
            p.umount()

    def _getRawImagefile(self):
        """ Get the raw image file.

        Some images (enfue, aff4...) must be mounted in order to have a raw image.
        Use this method to mount and get the path of these auxiliary mounts.
        Remember to umount these auxiliary images in umount()
        """

        return self.imagefile

    def mmls(self):
        """ Read partitions from the image """
        imagefile = self._getRawImagefile()
        self.logger.debug('Listing partitions. source=%s imagefile=%s type=%s', self.params('source'), imagefile, self.imagetype)

        img = pytsk3.Img_Info(imagefile)
        try:
            volume = pytsk3.Volume_Info(img)
            self.sectorsize = volume.info.block_size
        except Exception:
            pass

        if not volume:
            self.logger.warning("File imagefile=%s has not a partition table or is malformed. Trying to manage as a single partition" % self.imagefile)
            try:
                fs = pytsk3.FS_Info(img)
                filesystem = str(fs.info.ftype)
                filesystem = filesystem.split("TSK_FS_TYPE_")[-1]
                self.sectorsize = 512
                self.partitions.append(Partition(imagefile, int(os.stat(self.imagefile).st_size) / int(self.sectorsize), filesystem, "0", "0", self.sectorsize, self.params))
                return
            except Exception:
                self.logger.error("Error getting image partition info from imagefile=%s" % self.imagefile)
                return

        for part in volume:
            partition = "%02d" % int(part.addr)
            osects = part.start
            size = part.len
            try:
                fs = pytsk3.FS_Info(img, int(int(osects) * int(self.sectorsize)))
                filesystem = str(fs.info.ftype)
                filesystem = filesystem.split("TSK_FS_TYPE_")[-1]
            except Exception:
                filesystem = part.desc.decode()
            if filesystem.startswith('Macintosh HD'):
                filesystem = "HFS"
            if filesystem == "NoName":
                apfs_pstat = self.params('apfs_pstat', '/usr/local/src/sleuthkit-APFS/tools/pooltools/pstat')
                mosects = osects
                if self.sectorsize == 4096:  # sleuthkit-APFS uses 512 blocksize
                    # TODO: check if this must be osects *= 8
                    mosects = osects * 8
                pstat = ""
                try:
                    pstat = subprocess.check_output([apfs_pstat, "-o", str(osects), "-P", "apfs", self.imagefile]).decode()
                except Exception:
                    pstat = subprocess.check_output([apfs_pstat, "-o", str(osects * 8), "-P", "apfs", self.imagefile]).decode()
                pstat = pstat.split("\n")
                n = 0
                for p in pstat:
                    aux = re.search(r"APSB Block Number:\s+(\d+)", p)
                    if aux:
                        try:
                            partition = str(int(part.addr) * 10 + n)
                            self.partitions.append(Partition(imagefile, size, filesystem, osects, partition, self.sectorsize, self.params, aux.group(1), n))
                            n += 1
                        except Exception:
                            self.logger.error("Problems getting information about APFS partition %s with block Number %s" % (partition, aux.group(1)))
            else:
                try:
                    self.partitions.append(Partition(imagefile, size, filesystem, osects, partition, self.sectorsize, self.params))
                except Exception as exc:
                    self.logger.error("Error getting information about partition {}: {}".format(partition, exc))

    def getPartitionNumber(self):
        """ Return the number of partitions in disk """
        return len([p for p in self.partitions if p.filesystem != "Unallocated" and not p.filesystem.startswith("Primary Table")])

    def __str__(self):
        if self.exists():
            text = 'Case disk={} sectorsize={}\n\n'.format(self.disknumber, self.sectorsize)
            for p in self.partitions:
                text += "Partition: {}\n\tOffset in sectors: {}\n\tCluster Size: {}\n\tFile System: {}\n\tSize: {}".format(p.partition, p.osects, p.clustersize, p.filesystem, p.size)
                if len(p.vss) > 0:
                    text += "\n\t \tpartition {} has {} stores".format(p.partition, len(p.vss))
                if p.encrypted:
                    text += "\n\t \tpartition {} is encrypted".format(p.partition)
                text += "\n\n"
            return text
        else:
            return 'Disknumber id={} not found'.format(self.disknumber)

    def myflag(self, option, default=False):
        """ A convenience method for self.config.getboolean(self.section, option, False) """
        value = self.params(option, str(default))
        return value in ('True', 'true', 'TRUE', 1)


class DummyImage(BaseImage):
    def mount(self, partitions='', vss=False, unzip_path=None):
        pass

    def umount(self, unzip_path=None):
        pass

    def mmls(self):
        pass


class ZipImage(BaseImage):
    """ Manages a ZIP file: its contents are unzipped into a single partition """

    def mmls(self):
        pass

    def mount(self, unzip_path=None, partitions='', vss=False):
        """ Extracts contents of zip imagefile to unzip_path"""
        if zipfile.is_zipfile(self.imagefile):
            try:
                if unzip_path is None:
                    partition_name = self.params('partname', 'p01')
                    unzip_path = self.params(os.path.join(self.params('mountdir'), partition_name))
                base.utils.check_directory(unzip_path, create=True, delete_exists=False)

                with zipfile.ZipFile(self.imagefile, 'r') as myzip:
                    bkid = myzip.namelist()[0]
                    self.logger.debug('Extracting file imagefile=%s to mountauxdir=%s', self.imagefile, unzip_path)
                    # check wether the directory already exists
                    if not base.utils.check_directory(os.path.join(unzip_path, bkid)):
                        for zn in tqdm(myzip.namelist(), desc='Unzip image', disable=self.myflag('progress.disable')):
                            myzip.extract(zn, unzip_path)
                    else:
                        self.logger.warning('The unzip directory already exists: %s. Won\'t unzip', os.path.join(unzip_path, bkid))
            except Exception as exc:
                self.logger.warning('Cannot read zip file: %s', exc)

    def umount(self, unzip_path=None):
        if unzip_path is None:
            partition_name = self.params('partname', 'p01')
            unzip_path = self.params(os.path.join(self.params('mountdir'), partition_name))
        shutil.rmtree(unzip_path)


class AFFImage(BaseImage):
    """ Manages an AFF4 image """
    def _getRawImagefile(self):
        fuse_path = os.path.join(self.params('mountauxdir'), "aff")
        imagefile = os.path.join(fuse_path, "%s.raw" % os.path.basename(self.imagefile))
        self.auxdirectories.append(fuse_path)
        if not os.path.exists(imagefile):
            affuse = self.params('affuse', '/usr/bin/affuse')
            check_folder(fuse_path)
            try:
                run_command(["sudo", affuse, self.imagefile, fuse_path])
                fuse_path = os.path.join(self.params('mountauxdir'), "aff")
                imagefile = os.path.join(fuse_path, "%s.raw" % os.path.basename(self.imagefile))
            except Exception:
                self.logger.error("Cannot mount AFF imagefile=%s", self.imagefile)
                raise base.job.RVTError("Cannot mount AFF imagefile={}".format(self.imagefile))
        return imagefile

    def umount(self, unzip_path=None):
        super().umount()
        # unmount auxiliary images (encase and aff4)
        umount = self.params('umount', '/bin/umount')
        for mp in self.auxdirectories:
            run_command(["sudo", umount, '-l', mp])


class EncaseImage(BaseImage):
    """ Manages an EncaseImage image """
    def _getRawImagefile(self):
        # convert an Encase image to dd using ewfmount
        fuse_path = os.path.join(self.params('mountauxdir'), "encase")
        imagefile = os.path.join(fuse_path, "ewf1")
        self.auxdirectories.append(fuse_path)
        if not os.path.exists(imagefile):
            ewfmount = self.params('ewfmount', '/usr/bin/ewfmount')
            check_folder(fuse_path)
            try:
                run_command([ewfmount, self.imagefile, "-X", "allow_root", fuse_path])
            except Exception:
                self.logger.error("Cannot mount Encase imagefile=%s", self.imagefile)
                raise base.job.RVTError("Cannot mount Encase imagefile={}".format(self.imagefile))
        return imagefile

    def umount(self, unzip_path=None):
        super().umount()
        # unmount auxiliary images (encase and aff4)
        umount = self.params('umount', '/bin/umount')
        for mp in self.auxdirectories:
            run_command(["sudo", umount, '-l', mp])


KNOWN_IMAGETYPES = {
    "001": dict(type='raw', imgclass=BaseImage),
    "dd": dict(type='raw', imgclass=BaseImage),
    "raw": dict(type='raw', imgclass=BaseImage),
    "aff": dict(type='aff', imgclass=AFFImage),
    "aff4": dict(type='aff4', imgclass=AFFImage),
    "E01": dict(type='encase', imgclass=EncaseImage),
    "zip": dict(type='zip', imgclass=ZipImage),
}
# NOT_MOUNTABLE_PARTITIONS = ("Primary Table", "GPT Header", "Safety Table", "Partition Table", "Unallocated")
