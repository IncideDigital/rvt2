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

# TODO finish script and dump to file
# Linux partitions must be mounted

import re
import datetime
import base.job
import os
import subprocess
import struct
import gzip
from plugins.common.RVT_filesystem import FileSystem
from plugins.common.RVT_disk import getSourceImage
from base.utils import check_directory


def sizeof_fmt(num):
    for unit in ['', 'K', 'M', 'G', 'T', 'P']:
        if abs(num) < 1024.0:
            return "%3.1f%s" % (num, unit)
        num /= 1024.0
    return "%.1f%s" % (num, 'Yi')


class Characterize(base.job.BaseModule):

    def run(self, path=""):
        """ Characterizes a disk image

        """

        self.disk = getSourceImage(self.myconfig)
        self.filesystem = FileSystem(self.config, disk=self.disk)
        self.characterize_Linux()
        return []

        # disk_info = self.get_image_information(self.disk)
        # os_info = self.characterize_Windows(self.disk)

        # env = Environment(loader=FileSystemLoader(os.path.abspath(os.path.dirname(__file__))))
        # template = env.get_template("templates/characterize.md")

        # analysisdir = self.myconfig('analysisdir')
        # with open(os.path.join(analysisdir, "characterize.md"), "w") as f:
        #     output_text = template.render(disk_info=disk_info, os_info=os_info, source=self.myconfig('source'))
        #     f.write(output_text)

    # def get_image_information(self, disk):

    #     disk_info = {}

    #     disk_info["Size"] = sizeof_fmt(os.stat(disk.imagefile).st_size)
    #     disk_info["npart"] = disk.getPartitionNumber()

    #     logfile = "{}.LOG".format(disk.imagefile[:-2])

    #     if not os.path.isfile(logfile):
    #         logfile = "{}.LOG".format(disk.imagefile[:6])

    #     if os.path.isfile(logfile):
    #         with open(logfile, "r") as f1:
    #             for linea in f1:
    #                 aux = re.search("\*\s*(Model\s*:\s*[^\|]*)\|\s*Model\s*:", linea)
    #                 if aux:
    #                     disk_info["model"] = aux.group(1)
    #                 aux = re.search("\*\s*(Serial\s*:\s*[^\|]*)\|\s*Serial\s*:", linea)
    #                 if aux:
    #                     disk_info["serial_number"] = aux.group(1)
    #     disk_info["partition"] = []

    #     for p in disk.partitions:
    #         if p.filesystem != "Unallocated" and not p.filesystem.startswith("Primary Table"):
    #             disk_info["partition"].append({"pnumber": p.partition, "size": sizeof_fmt(p.size), "type": p.filesystem})
    #     return disk_info

    def characterize_Linux(self):
        """

        """

        self.outfile = self.myconfig('outfile')
        check_directory(os.path.dirname(self.outfile), create=True)

        for p in self.disk.partitions:
            part_path = os.path.join(self.myconfig('mountdir'), "p%s" % p.partition)
            if not os.path.isdir(os.path.join(part_path, "etc")):
                continue
            releas_f = ""
            if os.path.isfile(os.path.join(part_path, "etc/lsb-release")) or os.path.islink(os.path.join(part_path, "etc/lsb-release")):
                releas_f = os.path.join(part_path, "etc/lsb-release")
                if os.path.islink(releas_f):
                    releas_f = os.path.join(part_path, os.path.realpath(releas_f)[1:])
            else:
                for f in os.listdir(os.path.join(part_path, "etc")):
                    if f.endswith("-release"):
                        releas_f = os.path.join(part_path, "etc", f)

            with open(self.outfile, 'w') as out_f:
                if releas_f != "":
                    out_f.write("Information of partition {}\n\n".format(p.partition))
                    f_rel = open(releas_f, "r")
                    dist_id = f_rel.readline().split("=")[-1].rstrip()
                    dist_rel = f_rel.readline().split("=")[-1].rstrip()
                    dist_coden = f_rel.readline().split("=")[-1].rstrip()
                    dist_desc = f_rel.readline().split("=")[-1].rstrip()
                    kernel_v = ""
                    f_hostname = open(os.path.join(part_path, "etc/hostname"), "r")
                    hostname = f_hostname.read().rstrip()
                    f_hostname.close()
                    f_rel.close()
                    if os.path.isfile(os.path.join(part_path, "var/log/dmesg")):
                        f_dmesg = open(os.path.join(part_path, "var/log/dmesg"), "r")
                        for linea in f_dmesg:
                            aux = re.search(r"(Linux version [^\s]*)", linea)
                            if aux:
                                kernel_v = aux.group(1)
                                break
                        f_dmesg.close()
                out_f.write("Distribution ID:\t\t{}\nDistribution Release:\t\t{}\nDistribution codename:\t\t{}\nDistribution description:\t{}\nKernel version:\t{}\nHostname:\t{}\n".format(
                    dist_id, dist_rel, dist_coden, dist_desc, kernel_v, hostname))

                install_date = ""

                if os.path.isdir(os.path.join(self.myconfig('mountdir'), "p%s" % p.partition, "root")):
                    item = os.path.join(self.myconfig('source'), 'mnt', "p%s" % p.partition, "root")
                    install_date = self.filesystem.get_macb([item])[item][3]

                for f in ["root/install.log", "var/log/installer/syslog", "root/anaconda-ks.cfg"]:
                    if os.path.isfile(os.path.join(self.myconfig('mountdir'), "p%s" % p.partition, f)):
                        item = os.path.join(self.myconfig('source'), 'mnt', "p%s" % p.partition, f)
                        install_date = self.filesystem.get_macb([item])[item][3]
                        break

                if install_date != "":
                    out_f.write("Install date:\t{}\n\n".format(install_date))

            # usuarios
            self.get_linux_lastlog(p.partition)

            temp = self.get_linux_wtmp(os.path.join(part_path, "var/log"))

            # temp = subprocess.check_output('last -f {} --time-format iso'.format(os.path.join(part_path, "var/log/wtmp")), shell=True).decode("utf-8")
            with open(self.outfile, 'a') as out_f:
                out_f.write("\nLogins:\n\n{}".format(temp))

    # Auxiliary functions
    def getrecord(self, file, uid, preserve=False):
        """
        Returns [int(unix_time),string(device),string(host)] from the lastlog formated file object, set preserve = True to preserve your position within the file

        """

        position = file.tell()
        recordsize = struct.calcsize('=L32s256s')
        file.seek(recordsize * uid)
        data = file.read(recordsize)
        if preserve:
            file.seek(position)
        try:
            returnlist = list(struct.unpack('=L32s256s', data))
            returnlist[1] = returnlist[1][:int(returnlist[1].decode().index('\x00'))]
            returnlist[2] = returnlist[2][:int(returnlist[2].decode().index('\x00'))]
            return returnlist
        except Exception:
            recordsize = struct.calcsize('L32s256s')

            returnlist = list(struct.unpack('L32s256s', data))
            returnlist[1] = returnlist[1][:int(returnlist[1].decode().index('\x00'))]
            returnlist[2] = returnlist[2][:int(returnlist[2].decode().index('\x00'))]
            return returnlist
        else:
            return False

    def get_linux_wtmp(self, log_path):
        """ Extrats login information """

        output = ""

        for fichero in os.listdir(log_path):
            if fichero == "wtmp":
                temp = subprocess.check_output(['last', '-f', os.path.join(log_path, fichero), '--time-format', 'iso'])
                output += temp.decode()
            elif re.search(r"wtmp.*\.gz", fichero):
                temp_f = open("/tmp/wtmp.temp", "wb")
                with gzip.open(os.path.join(log_path, fichero), 'rb') as f:
                    temp_f.write(f.read())
                temp_f.close()
                temp = subprocess.check_output(['last', '-f', '/tmp/wtmp.temp', '--time-format', 'iso'])
                output += temp.decode()
        return output

    def get_linux_lastlog(self, partition):
        # function to extract last logins table
        # TO DO extract UUID of loopdevices with blkid and compare with UUID of /home from /etc/fstab
        try:
            llfile = open(os.path.join(self.myconfig('mountdir'), "p%s" % partition, "var/log/lastlog"), 'rb')
        except Exception as exc:
            self.logger().error("Unable to open %s" % os.path.join(self.myconfig('mountdir'), "p%s" % partition, "var/log/lastlog"))
            raise exc

        user = dict()

        f_shadow = open(os.path.join(self.myconfig('mountdir'), "p%s" % partition, "etc/shadow"), "r")
        for linea in f_shadow:
            linea = linea.split(":")
            if len(linea[1]) > 1:  # user with password
                user[linea[0]] = []
        f_shadow.close()

        f_passwd = open(os.path.join(self.myconfig('mountdir'), "p%s" % partition, "etc/passwd"), "r")
        for linea in f_passwd:
            linea = linea.split(":")
            if linea[0] in user.keys():
                user[linea[0]].append(linea[2])
        f_passwd.close()

        lista = []
        for k in user.keys():
            lista.append(os.path.join(self.myconfig('source'), 'mnt', "p%s" % partition, "home", k))

        user2 = self.filesystem.get_macb(lista)
        with open(self.outfile, 'a') as out_f:
            out_f.write('From timeline:\n')
            out_f.write('User\tm_time\ta_time\'c_time\tb_time\n')
            for u in user2:
                out_f.write('{}\t{}\t{}\t{}\t{}\n'.format(u.split('/')[-1], *user2[u]))

            out_f.write('\nFrom lastlog:\n')
            out_f.write('User\tuid\tLast login\tIP\n')
            for user, uid in user.items():
                record = self.getrecord(llfile, int(uid[0]))
                if record and record[0] > 0:
                    out_f.write('{}\t{}\t{}\t{}\n'.format(user, uid[0], datetime.datetime.fromtimestamp(int(record[0]).strftime('%Y-%m-%dT%H:%M:%SZ')), record[2].decode()))
                elif record:
                    out_f.write('{}\t{}\t{}\t{}\n'.format(user, uid[0], " ", record[2].decode()))
                else:
                    pass
        llfile.close()
