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

import logging
import pytsk3
import os
import subprocess
import re
import time
import getpass
import grp
import json
import datetime
from collections import defaultdict
from base.utils import check_folder, check_file, check_directory, relative_path
from base.commands import run_command

non_mountable_partitions = ("Primary Table", "GPT Header", "Safety Table", "Unallocated")


class Partition(object):
    """ Stores relevant information about a partition. Allows to mount the partiton
    """

    def __init__(self, imagefile, size, filesystem, osects, partition, sectorsize, myconfig, bn="", voln=""):
        self.logger = logging.getLogger(__name__)
        self.myconfig = myconfig
        self.partition = partition

        # Try to load variables from a previously generated json file
        vars = self.load_partition()
        if vars:
            for var, value in vars.items():
                setattr(self, var, value)
            self.refreshMountedImages()
            self.save_partition()
            return

        # Initialize basic attributes for a partition
        self.mountdir = self.myconfig('mountdir')
        self.mountpath = os.path.join(self.myconfig('mountdir'), 'p%s' % partition)
        self.mountaux = self.myconfig('mountauxdir')
        self.imagefile = imagefile  # path to the source image
        self.filesystem = filesystem  # filesystem name according to mmls
        self.size = int(size) * int(sectorsize)
        self.fuse = {}
        self.osects = osects
        self.loop = ""  # Loop device for partiton
        self.obytes = int(osects) * int(sectorsize)
        self.vss = []  # list of all vss on a partition
        self.vss_mounted = defaultdict(dict)  # Mount point for all vss
        self.vss_info = defaultdict(dict)
        self.isMountable = True
        self.check_bitlocker()  # Check if a partition uses bitlocker and set self.encrypted
        self.block_number = bn  # needed for using sleuthkit in APFS
        self.voln = voln  # needed to mount APFS volumes

        # Skip partitions know to be non mountable
        for unm in non_mountable_partitions:
            if self.filesystem.startswith(unm):
                self.isMountable = False
                self.clustersize = sectorsize
                return

        # Obtain clustersize and block_size
        try:
            img = pytsk3.Img_Info(imagefile)
            fs = pytsk3.FS_Info(img, offset=int(self.osects) * int(sectorsize))
            self.clustersize = fs.info.block_size
        except Exception:
            # self.logger.warning("Problems getting information about partition %s" % self.partition)
            if self.encrypted or self.filesystem == "NoName" or self.filesystem == "HFS":
                self.clustersize = 4096
            else:
                self.clustersize = 512
                self.isMountable = False
        self.refreshMountedImages()

        # Check for VSS
        if self.filesystem.startswith('NTFS') or self.filesystem.startswith('Basic data partition') or self.encrypted:
            self.get_vss_number_stores()

        # Save partition information to be easily retrieved later
        self.refreshMountedImages()
        self.save_partition()

    def get_vss_number_stores(self):
        """ Describes VSS found in the partition """
        vshadowinfo = self.myconfig('vshadowinfo', '/usr/local/bin/vshadowinfo')
        output = ""
        DEVNULL = open(os.devnull, 'wb')
        if self.obytes == 0:
            try:
                if not self.encrypted:
                    output = subprocess.check_output([vshadowinfo, self.imagefile], stderr=DEVNULL).decode()
                else:
                    output = subprocess.check_output([vshadowinfo, self.loop], stderr=DEVNULL).decode()
            except Exception:
                pass
        else:
            try:
                if not self.encrypted:
                    output = subprocess.check_output([vshadowinfo, self.imagefile, "-o", str(self.obytes)], stderr=DEVNULL).decode()
                else:
                    output = subprocess.check_output([vshadowinfo, self.loop], stderr=DEVNULL).decode()
            except Exception:
                pass  # No vss found

        DEVNULL.close()
        self._parse_vshadowinfo_output(output)

        self.logger.debug("Partition {} has {} vss".format(self.partition, len(self.vss)))

    def _parse_vshadowinfo_output(self, output):
        """ Save VSS information from standard vshadowinfo report.
            Expected format example:

            ```
            vshadowinfo 20191221

            Volume Shadow Snapshot information:
                Number of stores:	3

            Store: 1
                Identifier		    : 14b69590-d821-11e9-9689-340288e6d6f5
                Shadow copy set ID	: 001a795a-417d-4755-b2fb-3ac2e7644532
                Creation time		: Sep 16, 2019 01:34:38.186677500 UTC
                Shadow copy ID		: c1034e89-99f5-404c-9afd-d63d5e1dec0a
                Volume size		    : 111 GiB (119186362368 bytes)
                Attribute flags		: 0x0042000d

            Store: 2
                ...
            ```
        """
        number_of_stores = 0
        current_store = 0
        for line in output.split("\n"):
            if not number_of_stores:
                aux = re.search(r"Number of stores:\s*(\d+)", str(line))
                if aux:
                    number_of_stores = aux.group(1)
                    self.logger.debug("Partition {} has {} mounting points".format(self.partition, number_of_stores))
            if line.startswith('Store'):
                current_store = re.search(r"Store: (\d+)", str(line)).group(1)
            elif line.lstrip().startswith('Identifier'):
                self.vss_info[current_store]['id'] = re.search(r"\s*Identifier\s*: (.+)", str(line)).group(1)
            elif line.lstrip().startswith('Shadow copy ID'):
                self.vss_info[current_store]['shadow_id'] = re.search(r"\s*Shadow copy ID\s*: (.+)", str(line)).group(1)
            elif line.lstrip().startswith('Creation time'):
                date_string = re.search(r"\s*Creation time\s*: (.+)", str(line)).group(1)
                try:
                    creation_time = datetime.datetime.strptime(date_string[:-7], "%b %d, %Y %H:%M:%S.%f").isoformat()
                except Exception:
                    creation_time = ""
                self.vss_info[current_store]['creation_time'] = creation_time

        self.vss = ["v{}p{}".format(i, self.partition) for i in range(1, int(number_of_stores) + 1)]

    def mount(self):
        """ Main mounting method for partitions. Calls specific function depending on Filesystem type """

        self.logger.debug('Mounting partition={} of type={} from imagefile={}'.format(self.partition, self.filesystem, self.imagefile))
        vss = self.myflag('vss')

        self.refreshMountedImages()

        if self.loop != "" and not self.vss:
            self.logger.debug("Partition partition={} is already mounted".format(self.partition))
            return 0

        try:
            if self.encrypted:
                self.mount_bitlocker()
                if vss and len(self.vss) > 0:
                    self.vss_mount()
            elif self.filesystem.startswith("HFS"):
                self.mount_HFS()
            elif self.filesystem.lower().startswith("ext4"):
                self.mount_ext()
            elif self.filesystem == "NoName":
                self.mount_APFS()
            elif self.filesystem.startswith("FAT"):
                self.mount_fat()
            else:
                if not self.loop:
                    self.mount_NTFS()
                if vss and len(self.vss) > 0:
                    self.vss_mount()
        except Exception as exc:
            self.logger.error("Error mounting partition: {}. imagefile={} partition=p{}".format(exc, self.imagefile, self.partition))
        self.refreshMountedImages()

    def mount_NTFS(self, imagefile=None, mountpath=None, offset=True):
        """ mount NTFS partition

        Confiugration section:
            :ntfs_args: arguments for mount. offset and sizelimit will be automatically appended to these arguments.
                This parameter will be managed as a format string. The current group id will be passed as an option `gid`.

        Args:
            imagefile (str): imagefile path (used for auxiliary mount point). If None, use self.imagefile.
            mountpath (str): mount the image on this path. If None, use `source/mnt/pXX`.
            offset (bool): Used to ignore disk offset (used for auxiliary mount point)
        """
        args = self.myconfig('ntfs_args').format(gid=grp.getgrgid(os.getegid())[2])
        if offset and self.obytes != 0:
            args = "%s,offset=%s,sizelimit=%s" % (args, self.obytes, self.size)
        mount = self.myconfig('mount', '/bin/mount')
        if not mountpath:
            mountpath = os.path.join(self.mountdir, "p%s" % self.partition)
        if not imagefile:
            imagefile = self.imagefile
        check_folder(mountpath)
        run_command(["sudo", mount, imagefile, "-t", "ntfs-3g", "-o", args, mountpath], logger=self.logger)

    def mount_bitlocker(self):
        if 'dislocker' in self.fuse.keys():
            self.logger.debug("Bitlocker partition p{} already mounted".format(self.partition))
            return
        rec_key = self.myconfig('recovery_keys')
        dislocker = self.myconfig('dislocker', '/usr/bin/dislocker')
        mountauxpath = os.path.join(self.mountaux, "p%s" % self.partition)
        check_folder(mountauxpath)
        import time

        if rec_key == "":
            self.logger.warning("Recovery key not available on partition p%s. Trying without key" % self.partition)
            try:
                cmd = "sudo {} -c -O {} -V {} -r {}".format(dislocker, self.obytes, self.imagefile, mountauxpath)
                run_command(cmd, logger=self.logger)
                time.sleep(4)
                self.refreshMountedImages()
                self.mount_NTFS(os.path.join(mountauxpath, "dislocker-file"), offset=False)
            except Exception as exc:
                self.logger.error("Problems mounting bitlocker partition p%s: %s", self.partition, str(exc))
                return -1
        else:
            self.logger.debug("Trying to mount with recovery keys at {}".format(self.mountaux))
            mountauxpath = os.path.join(self.mountaux, "p%s" % self.partition)
            for rk in rec_key.split(','):  # loop wih different recovery keys, comma separated
                try:
                    cmd = "sudo {} -p{} -O {} -V {} -r {}".format(dislocker, rk, self.obytes, self.imagefile, mountauxpath)
                    run_command(cmd, logger=self.logger)
                    time.sleep(4)
                    self.refreshMountedImages()
                    self.mount_NTFS(os.path.join(mountauxpath, "dislocker-file"), offset=False)
                    break
                except Exception as exc:
                    self.logger.error("Problems mounting bitlocker partition p%s: %s", self.partition, str(exc))
                    return -1

    def mount_fat(self, imagefile=None, mountpath=None, offset=True):
        args = self.myconfig('fat_args').format(gid=grp.getgrgid(os.getegid())[0])
        if offset and self.obytes != 0:
            args = "%s,offset=%s,sizelimit=%s" % (args, self.obytes, self.size)
        mount = self.myconfig('mount', '/bin/mount')
        if not mountpath:
            mountpath = os.path.join(self.mountdir, "p%s" % self.partition)
        if not imagefile:
            imagefile = self.imagefile
        check_folder(mountpath)
        run_command(["sudo", mount, self.imagefile, "-o", args, mountpath], logger=self.logger)

    def mount_HFS(self, imagefile="", mountpath="", offset=True):
        # TODO: avoid infinite recursion if mount fails after having called fvdemount
        if mountpath == "":
            mountpath = os.path.join(self.mountaux, "p%s" % self.partition)
        if imagefile == "":
            imagefile = self.imagefile

        mount = self.myconfig('mount', '/bin/mount')
        check_folder(mountpath)
        args = "%s,sizelimit=%s" % (self.myconfig('hfs_args'), self.size)
        if offset and self.obytes != 0:
            args = "%s,offset=%s,sizelimit=%s" % (self.myconfig('hfs_args'), self.obytes, self.size)
        try:
            run_command(["sudo", mount, imagefile, "-o", args, mountpath], logger=self.logger)
            self.bindfs_mount()
        except Exception:
            self.fvde_mount()

    def mount_ext(self):
        mount = self.myconfig('mount', '/bin/mount')
        mountpath = os.path.join(self.mountaux, "p%s" % self.partition)
        check_folder(mountpath)
        args = "%s,sizelimit=%s" % (self.myconfig('ext4_args'), self.size)
        if self.obytes != 0:
            args = "%s,offset=%s,sizelimit=%s" % (self.myconfig('ext4_args'), self.obytes, self.size)
        try:
            run_command(["sudo", mount, self.imagefile, "-o", args, mountpath], logger=self.logger)
        except Exception:
            args = args + ',norecovery'
            run_command(["sudo", mount, self.imagefile, "-o", args, mountpath], logger=self.logger)
        self.bindfs_mount()

    def mount_APFS(self):
        apfsmount = self.myconfig('apfsmount', '/usr/local/bin/apfs-fuse')
        mountpath = os.path.join(self.mountaux, "p%s" % self.partition)
        check_folder(mountpath)
        run_command(["sudo", apfsmount, "-s", str(self.obytes), "-v", str(self.voln), self.imagefile, mountpath], logger=self.logger)
        self.bindfs_mount()

    def bindfs_mount(self):
        user = getpass.getuser()
        group = grp.getgrgid(os.getegid())[0]

        mountaux = os.path.join(self.mountaux, "p%s" % self.partition)
        check_folder(self.mountpath)
        bindfs = self.myconfig('bindfs', '/usr/bin/bindfs')
        run_command(["sudo", bindfs, "-p", "550", "-u", user, "-g", group, mountaux, self.mountpath], logger=self.logger)

    def fvde_mount(self):
        self.logger.debug('Obtaining encrypted partition')
        fvdemount = self.myconfig('fvdemount', '/usr/local/bin/fvdemount')
        password = self.myconfig('password')
        mountpoint = os.path.join(self.mountaux, "vp%s" % self.partition)
        check_folder(mountpoint)
        # TODO: get 'EncryptedRoot.plist.wipekey' from recovery partition: https://github.com/libyal/libfvde/wiki/Mounting
        encryptedfile = os.path.join(self.myconfig('sourcedir'), 'EncryptedRoot.plist.wipekey')
        run_command(['sudo', fvdemount, "-e", encryptedfile, "-p", password, "-X", "allow_root", "-o", str(self.obytes), self.imagefile, mountpoint], logger=self.logger)
        time.sleep(2)  # let it do his work
        self.mount_HFS(imagefile=os.path.join(mountpoint, 'fvde1'), mountpath=os.path.join(self.mountaux, "p%s" % self.partition), offset=False)

    def vss_mount(self):
        vshadowmount = self.myconfig('vshadowmount', '/usr/local/bin/vshadowmount')

        # Create auxiliar fuse mount point
        vp = os.path.join(self.mountaux, "vp%s" % self.partition)
        if len(self.fuse) == 0 or "fuse" not in self.fuse.keys():
            self.logger.debug('Mounting auxiliary vss point: {}'.format(vp))
            check_directory(vp, create=True)
            if self.encrypted:
                run_command(["sudo", vshadowmount, "-X", "allow_root", self.loop, vp], logger=self.logger)
            else:
                run_command([vshadowmount, "-X", "allow_root", self.imagefile, "-o", str(self.obytes), vp], logger=self.logger)

        # Create as many new sources as VSS existing, and mount them
        for p in self.vss:
            # Skip already mounted sources
            skip_mounting = False
            for mounted in self.vss_mounted:
                if mounted.startswith(p):
                    skip_mounting = True
                    break
            if skip_mounting:
                self.logger.debug("VSS partition {} is already mounted".format(p))
                continue
            # New source name format: 'source_vXpY_timestamp'
            vss_source_name = '_'.join([self.myconfig('source'), p,
                                       datetime.datetime.fromisoformat(self.vss_info[p.split('p')[0][1:]]['creation_time']).strftime("%y%m%d_%H%M%S")])
            new_source_dir = os.path.join(self.myconfig('casedir'), vss_source_name)
            check_directory(new_source_dir, create=True)
            mp = os.path.join(new_source_dir, 'mnt', 'p{}'.format(p.split('p')[1]))
            self.logger.debug('Mounting vss partition at {}'.format(mp))
            self.mount_NTFS(imagefile=os.path.join(vp, "vss%s" % p[1:].split("p")[0]), mountpath=mp, offset=False)

        self.refreshMountedImages()

    def umount(self):
        """ Unmounts all partitions """
        self.refreshMountedImages()

        for v, mp in self.vss_mounted.items():
            if mp != "":
                self.logger.debug("Unmounting vss partition {}".format(v))
                self.umountPartition(mp)

        for f, mp in self.fuse.items():
            if mp != "" and f != "dislocker":
                self.logger.debug("Unmounting fuse partition {}".format(mp))
                self.umountPartition(mp)

        if self.loop != "":
            self.logger.debug("Unmounting partition p{}".format(self.partition))
            self.umountPartition(self.loop)
        if 'dislocker' in self.fuse.keys():
            self.umountPartition(self.fuse['dislocker'])

        self.refreshMountedImages()

    def umountPartition(self, path):
        """ Umount path """

        umount = self.myconfig('umount', '/bin/umount')
        time.sleep(1)
        try:
            run_command(["sudo", umount, '-l', path], logger=self.logger)
        except Exception:
            self.logger.error("Error unmounting {}".format(path))
        # Remove partition info file if 'remove_info' is True:
        self.load_partition()

    def refreshMountedImages(self):
        """ Updates information about mounting points. """

        df = self.myconfig('df', '/bin/df')
        mount = self.myconfig('mount', '/bin/mount')

        # clear info
        self.loop = ""
        self.fuse = {}
        self.vss_mounted = defaultdict(dict)

        # Get the mountdir and mountauxdir for original sources
        original_source = self.myconfig('source')
        aux = re.search(r"(.*)_v\d+p\d+_\d{6}_\d{6}", original_source)
        if aux:  # If source provided is a vss. Used by other jobs calling getSourceImage
            original_source = aux.group(1)
        mountdir = relative_path(self.myconfig('mountdir'), self.myconfig('casedir'))
        mountdir = os.path.join(self.myconfig('casedir'), original_source, mountdir[mountdir.find('/') + 1:])
        mountauxdir = relative_path(self.myconfig('mountauxdir'), self.myconfig('casedir'))
        mountauxdir = os.path.join(self.myconfig('casedir'), original_source, mountauxdir[mountauxdir.find('/') + 1:])

        # Update info obtained by 'df'
        output = subprocess.check_output(df).decode().split('\n')
        self._parse_df(output, mountdir, mountauxdir)

        # Update info obtained by 'mount'
        output = subprocess.check_output(mount).decode().split("\n")
        self._parse_mount(output, mountauxdir)

        self.logger.debug('Loop devices for partition {}: {}'.format(self.partition, str(self.loop)))
        self.logger.debug('Fuse devices for partition {}: {}'.format(self.partition, str(self.fuse)))
        self.logger.debug('VSS loop devices for partition {}: {}'.format(self.partition, str(self.vss_mounted)))

    def _parse_df(self, output, mountdir, mountauxdir):
        """ Find regex patterns in 'df' output to identify mounting points """
        for line in output:
            aux = re.match(r"(/dev/loop\d+) .*({}|{})/(p{}|v\d+p{})".format(mountdir, mountauxdir, self.partition, self.partition), line)
            if aux:
                if aux.group(3).startswith("p"):
                    self.loop = aux.group(1)
            # Vss mounted
            original_source = self.myconfig('source')
            aux = re.search(r"(.*)_v\d+p\d+_\d{6}_\d{6}", original_source)
            if aux:  # If source provided is a vss. Used by other jobs calling getSourceImage
                original_source = aux.group(1)
            aux = re.match(r"(/dev/loop\d+) .*{}/{}_(v.*)/mnt/(p{})".format(self.myconfig('casedir'), original_source, self.partition), line)
            if aux:
                self.vss_mounted[aux.group(2)] = aux.group(1)

    def _parse_mount(self, output, mountauxdir):
        """ Find regex patterns in 'mount' output to identify mounting points """
        for line in output:
            aux = re.search("(fuse|dislocker) on .*({}/?v?p{}) type fuse".format(mountauxdir, self.partition), str(line))
            if aux:
                self.fuse["{}".format(aux.group(1))] = aux.group(2)
                continue

            aux = re.search("(bindfs|affuse) on ({}/p{}) type fuse".format(self.mountdir, self.partition), str(line))
            if aux:
                self.fuse[aux.group(1)] = aux.group(2)
                continue
            aux = re.match("({}/p{}) on ({}/p{}) type fuse".format(mountauxdir, self.partition, self.mountdir, self.partition), str(line))
            if aux:
                self.fuse[aux.group(1)] = aux.group(2)
            aux = re.match(r"({}/v?p{}/fvde\d+) on ({}/p{}) type hfsplus".format(mountauxdir, self.partition, self.mountdir, self.partition), str(line))
            if aux:
                self.fuse[aux.group(1)] = aux.group(2)

    def myflag(self, option, default=False):
        """ A convenience method for self.config.getboolean(self.section, option, False) """
        value = self.myconfig(option, str(default))
        return value in ('True', 'true', 'TRUE', 1)

    def check_bitlocker(self):
        """ Check if partition is encrypted with bitlocker """

        self.encrypted = False
        initBitlocker = b"\xeb\x58\x90\x2d\x46\x56\x45\x2d\x46\x53\x2d"
        with open(self.imagefile, "rb") as f:
            f.seek(self.obytes)
            a = f.read(11)
            if a == initBitlocker:
                self.encrypted = True
                self.logger.debug("Partition {} is encrypted".format(self.partition))

    def save_partition(self):
        """ Write partition variables in a JSON file """
        check_folder(self.myconfig('auxdir'))
        outfile = os.path.join(self.myconfig('auxdir'), 'p{}_info.json'.format(self.partition))
        skipped_vars = ['logger', 'myconfig']
        with open(outfile, 'w') as out:
            try:
                jsondata = json.dumps({k: v for k, v in self.__dict__.items() if k not in skipped_vars}, indent=4)
                out.write(jsondata)
            except TypeError as exc:
                raise exc

    def load_partition(self):
        """ Load partition variables from JSON file. Avoids running mmls every time """

        infile = os.path.join(self.myconfig('auxdir'), 'p{}_info.json'.format(self.partition))
        if self.myflag('remove_info') and check_file(infile):
            try:
                os.remove(infile)
            except Exception:
                self.logger.error("Error while deleting file: {}".format(infile))
            return False

        self.logger.debug('Loading partition {} information'.format(self.partition))
        if check_file(infile) and os.path.getsize(infile) != 0:
            with open(infile) as inputfile:
                try:
                    return json.load(inputfile)
                except Exception:
                    self.logger.warning('JSON file {} malformed'.format(infile))
                    return False
        return False

    def __str__(self):
        return("""
            Image file = {}
            Partition path = {}
            Partition filesystem = {}
            Partition offset = {}
            Partition size = {}
            Partition clusters size = {}
            """.format(self.imagefile, self.mountpath, self.filesystem, self.obytes, self.size, self.clustersize))
