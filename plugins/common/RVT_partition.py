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
from base.utils import check_folder, check_file
from base.commands import run_command

non_mounting_partitions = ("Primary Table", "GPT Header", "Safety Table", "Unallocated")


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

        self.mountdir = self.myconfig('mountdir')
        self.mountpath = os.path.join(self.myconfig('mountdir'), 'p%s' % partition)
        self.mountaux = self.myconfig('mountauxdir')
        self.imagefile = imagefile
        self.filesystem = filesystem
        self.size = int(size) * int(sectorsize)
        self.fuse = {}
        self.osects = osects
        self.loop = ""
        self.obytes = int(osects) * int(sectorsize)
        self.vss = {}
        self.isMountable = True
        self.check_bitlocker()
        self.block_number = bn  # needed for using sleuthkit in APFS
        self.voln = voln  # needed to mount APFS volumes

        for unm in non_mounting_partitions:
            if self.filesystem.startswith(unm):
                self.isMountable = False
                self.clustersize = sectorsize
                return

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

        if self.filesystem.startswith('NTFS') or self.filesystem.startswith('Basic data partition') or self.encrypted:
            self.get_vss_number_stores()

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
        for linea in output.split("\n"):
            aux = re.search(r"Number of stores:\s*(\d+)", str(linea))
            if aux:
                nstores = aux.group(1)
                self.logger.info("Partition {} has {} mounting points".format(self.partition, nstores))
                for i in range(1, int(nstores) + 1):
                    self.vss["v{}p{}".format(i, self.partition)] = ""

        self.logger.debug("Partition {} has {} vss".format(self.partition, len(self.vss)))

    def mount(self):
        """ Main mounting method for partitions. Calls specific function depending on Filesystem type """

        self.logger.debug('Mounting partition={} of type={} from imagefile={}'.format(self.partition, self.filesystem, self.imagefile))
        vss = self.myflag('vss')

        self.refreshMountedImages()

        if self.loop != "" and not self.vss:
            self.logger.info("Partition partition={} is already mounted".format(self.partition))
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
            self.logger.info("Bitlocker partition p{} already mounted".format(self.partition))
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
            except Exception:
                self.logger.error("Problems mounting partition p%s" % self.partition)
                return -1
        else:
            self.logger.info("Trying to mount with recovery keys at {}".format(self.mountaux))
            mountauxpath = os.path.join(self.mountaux, "p%s" % self.partition)
            for rk in rec_key.split(','):  # loop wih different recovery keys, comma separated
                try:
                    cmd = "sudo {} -p{} -O {} -V {} -r {}".format(dislocker, rk, self.obytes, self.imagefile, mountauxpath)
                    run_command(cmd, logger=self.logger)
                    time.sleep(4)
                    self.refreshMountedImages()
                    self.mount_NTFS(os.path.join(mountauxpath, "dislocker-file"), offset=False)
                    break
                except Exception:
                    pass

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

        if len(self.vss) > 0:
            vp = os.path.join(self.mountaux, "vp%s" % self.partition)
            if len(self.fuse) == 0 or "/dev/fuse" not in self.fuse.keys():
                check_folder(vp)
                if self.encrypted:
                    run_command(["sudo", vshadowmount, "-X", "allow_root", self.loop, vp], logger=self.logger)
                else:
                    run_command([vshadowmount, "-X", "allow_root", self.imagefile, "-o", str(self.obytes), vp], logger=self.logger)
            for p in self.vss.keys():
                if self.vss[p] == "":
                    mp = os.path.join(self.mountdir, p)
                    self.mount_NTFS(imagefile=os.path.join(vp, "vss%s" % p[1:].split("p")[0]), mountpath=mp, offset=False)
        self.refreshMountedImages()

    def umount(self):
        """ Unmounts all partitions """
        self.refreshMountedImages()

        for v, mp in self.vss.items():
            if mp != "":
                self.logger.info("Unmounting vss partition {}".format(v))
                self.umountPartition(mp)

        for f, mp in self.fuse.items():
            if mp != "" and f != "dislocker":
                self.logger.info("Unmounting fuse partition {}".format(mp))
                self.umountPartition(mp)

        if self.loop != "":
            self.logger.info("Unmounting partition p{}".format(self.partition))
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

    def refreshMountedImages(self):
        """ Updates information about loop devices mounted. """

        df = self.myconfig('df', '/bin/df')
        mount = self.myconfig('mount', '/bin/mount')

        # clear info
        self.loop = ""
        self.fuse = {}
        for v in self.vss.keys():
            self.vss[v] = ""

        output = subprocess.check_output(df).decode()
        output = output.split('\n')
        for linea in output:
            aux = re.match(r"(/dev/loop\d+) .*({}|{})/(p{}|v\d+p{})".format(self.myconfig('mountdir'), self.myconfig('mountauxdir'), self.partition, self.partition), linea)
            if aux:
                if aux.group(3).startswith("p"):
                    self.loop = aux.group(1)
                elif aux.group(3).startswith("v"):
                    self.vss[aux.group(3)] = aux.group(1)

        output = subprocess.check_output(mount).decode()
        output = output.split("\n")
        for linea in output:
            aux = re.search("(fuse|dislocker) on ({}/v?p{}) type fuse".format(self.myconfig('mountauxdir'), self.partition), str(linea))
            if aux:
                self.fuse["{}".format(aux.group(1))] = aux.group(2)
                continue

            aux = re.search("(bindfs|affuse) on ({}/p{}) type fuse".format(self.mountdir, self.partition), str(linea))
            if aux:
                self.fuse[aux.group(1)] = aux.group(2)
                continue
            aux = re.match("({}/p{}) on ({}/p{}) type fuse".format(self.myconfig('mountauxdir'), self.partition, self.mountdir, self.partition), str(linea))
            if aux:
                self.fuse[aux.group(1)] = aux.group(2)
            aux = re.match(r"({}/v?p{}/fvde\d+) on ({}/p{}) type hfsplus".format(self.myconfig('mountauxdir'), self.partition, self.mountdir, self.partition), str(linea))
            if aux:
                self.fuse[aux.group(1)] = aux.group(2)

    def myflag(self, option, default=False):
        """ A convenience method for self.config.getboolean(self.section, option, False) """
        value = self.myconfig(option, str(default))
        return value in ('True', 'true', 'TRUE', 1)

    def check_bitlocker(self):
        """ Check if partitions is encrypted with bitlocker """

        self.encrypted = False
        initBitlocker = b"\xeb\x58\x90\x2d\x46\x56\x45\x2d\x46\x53\x2d"
        with open(self.imagefile, "rb") as f:
            f.seek(self.obytes)
            a = f.read(11)
            if a == initBitlocker:
                self.encrypted = True
                self.logger.info("Partition {} is encrypted".format(self.partition))

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
