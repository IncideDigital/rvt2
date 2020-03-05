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


# Uses an adapted version of Windows Prefetch Parser Based in 505Forensics (http://www.505forensics.com)

import csv
import os
import re
import logging
import struct
import pyscca

import base.job
from plugins.common.RVT_filesystem import FileSystem
from base.utils import check_folder, check_directory, save_csv
from base.commands import run_command
from plugins.common.RVT_files import GetFiles


def parse_RFC_file(fname):
    """ Parses RecentFileCache.bcf

    Args:
        fname (str): file path
    """
    magics = [b'\xfe\xff\xee\xff', b'\x11\x22\x00\x00', b'\x03\x00\x00\x00', b'\x01\x00\x00\x00']
    entries = []
    filesize = os.path.getsize(fname)
    if filesize <= 20:
        return ''

    with open(fname, "rb") as fh:
        fh.seek(0)
        for i in range(0, len(magics)):
            header = fh.read(4)
            if not header == magics[i]:
                return ''
        fh.read(4)  # Disregard this value

        while fh.tell() < filesize:
            tmp_buffer = fh.read(4)
            entry_len = (struct.unpack('<i', tmp_buffer)[0]) * 2  # For unicode
            entry = fh.read(entry_len)
            entries.append(entry.decode("utf-16"))
            fh.read(2)  # Disregard last two unicode null terminators as they break in decode

    return entries


def parse_prefetch_file(pf_file):
    """ Parse individual file. Output is placed in 'output' dictionary

    Args:
        pf_file (str): list of filenames
    Returns:
        dict: dict with prefetch file information
    """
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    logger.info("Parsing {}".format(pf_file))
    item = {}

    try:
        scca = pyscca.open(pf_file)
        res_loaded = []
        for x in range(scca.get_number_of_file_metrics_entries()):
            res_loaded.append(scca.get_filename(x))
        item["resources loaded"] = res_loaded

        last_run_times = []
        n_runs = 1
        if scca.get_format_version() > 23:
            n_runs = 8

        for x in range(n_runs):
            if scca.get_last_run_time_as_integer(x) > 0:
                last_run_times.append(scca.get_last_run_time(x).strftime("%Y-%m-%d %H:%M:%S"))  # str conversion utilized to change from datetime into human-readable
            else:
                last_run_times.append('')

        item["last run times"] = last_run_times
        item["filename"] = scca.executable_filename
        item["prefetch hash"] = format(scca.prefetch_hash, 'x').upper()
        item["run count"] = str(scca.run_count)

        volumes = []
        for i in range(scca.number_of_volumes):
            volume = [str(scca.get_volume_information(i).device_path), scca.get_volume_information(i).creation_time.strftime(
                "%Y-%m-%d %H:%M:%S"), format(scca.get_volume_information(i).serial_number, 'x').upper()]
            volumes.append(volume)
        item["Volumes"] = volumes

        return item
    except IOError as e:
        logger.error("I/O Error: {}".format(e))
        return -1
    except SystemError as e:
        logger.error("Bad signature for pf file: {}".format(e))
        return -1
    except Exception:
        logger.error("Unexpected error")
        return -1


class Prefetch(base.job.BaseModule):
    """ Parse prefetch """

    def run(self, path=""):
        self.search = GetFiles(self.config, vss=self.myflag("vss"))
        self.vss = self.myflag('vss')
        self.filesystem = FileSystem(self.config)
        self.parse_Prefetch()
        return []

    def parse_Prefetch(self):
        self.logger().info("Parsing prefetch files")

        base_path = self.myconfig('{}outdir'.format('v' if self.vss else ''))
        check_directory(base_path, create=True)
        prefetch_dir = self.search.search(r"Windows/Prefetch$")

        if not prefetch_dir:
            self.logger().info('Prefetch file not found')
            return []

        for pdir in prefetch_dir:
            partition = pdir.split("/")[-3]
            csv_file = open(os.path.join(base_path, "prefetch_%s.csv" % partition), "w")
            writer = csv.writer(csv_file, delimiter=";", quotechar='"')
            pf_output1 = open(os.path.join(base_path, "prefetch_dump_%s.txt" % partition), "w")
            pdir_path = os.path.join(self.myconfig('casedir'), pdir)
            try:
                file_list = [os.path.join(pdir, file) for file in os.listdir(pdir_path) if file.endswith(".pf")]
            except IOError:
                self.logger().error('Unable to list files in directory {}'.format(pdir_path))
                continue
            except Exception as exc:
                self.logger().error(exc)
                continue

            if len(file_list) == 0:
                continue

            tl_files = self.filesystem.get_macb(file_list, self.vss)

            flag = True
            for file in os.listdir(pdir_path):
                prefetch_file = os.path.join(pdir_path, file)
                prefetch_rel_path = os.path.join(pdir, file)
                if file.endswith(".pf") and os.path.getsize(prefetch_file) > 0:  # Parse only non empty .pf files
                    item = parse_prefetch_file(prefetch_file)
                else:
                    continue

                if item == -1:
                    self.logger().error("Problems parsing {}".format(file))
                    pf_output1.write("Filename:\t\t{}\nBirth time:\t\t{}\nPrefetch Hash:\t\t\nExecutable Filename:\t\nRun count:\t\t\n".format(
                        file, tl_files[prefetch_rel_path][3]))
                    writer.writerow([file, "", "", tl_files[prefetch_rel_path][3], tl_files[prefetch_rel_path][0]] + [""] * 7)
                    continue

                if flag:
                    headers = ["Filename", "Executable", "Run count", "Birth time"] + ["Run time {}".format(str(i)) for i in range(len(item["last run times"]))]
                    writer.writerow(headers)
                    flag = False

                pf_output1.write("Filename:\t\t{}\nCreation time:\t\t{}\nPrefetch Hash:\t\t{}\nExecutable Filename:\t{}\nRun count:\t\t{}\n".format(
                    file, tl_files[prefetch_rel_path][3], item["prefetch hash"], item["filename"], item["run count"]))
                for i, fecha in enumerate(item["last run times"]):
                    pf_output1.write("\tRun time {}:\t\t{}\n".format(str(i), fecha))
                pf_output1.write("\nFilenames\nNumber of Filenames:\t{}\n".format(str(len(item["resources loaded"]))))
                for i in item["resources loaded"]:
                    pf_output1.write("\t{}\n".format(i))
                pf_output1.write("\nVolumes\nNumber of Volumes:\t{}\n".format(str(len(item["Volumes"]))))
                for v in item["Volumes"]:
                    pf_output1.write("\tDevice path:\t{}\n\tCreation time:\t{}\n\tSerial Number:\t{}\n\n".format(v[0], v[1], v[2]))
                pf_output1.write("################################################\n")

                writer.writerow([file, item["filename"], item["run count"], tl_files[prefetch_rel_path][3]] + [i for i in item["last run times"]])
            pf_output1.close()
            csv_file.close()

        self.logger().info("Parsing prefetch files finished")


class RFC(base.job.BaseModule):
    """ Parses RecentFileCache.bcf """

    def run(self, path=""):
        self.search = GetFiles(self.config, vss=self.myflag("vss"))
        self.logger().info("Parsing RecentFileCache.bcf")
        self.parse_RFC()
        return []

    def parse_RFC(self):
        base_path = self.myconfig('outdir')
        check_folder(base_path)

        rfc_list = list(self.search.search("RecentFileCache.bcf$"))
        if len(rfc_list) == 0:
            self.logger().info("No RecentFileCache.bcf files founded in disk")
            return

        for file in rfc_list:
            self.logger().info("Parsing {}".format(file))
            partition = file.split("/")[2]
            outfile = os.path.join(base_path, "rfc_{}.csv".format(partition))
            try:
                rfc = ({'Application': i} for i in parse_RFC_file(os.path.join(self.myconfig('casedir'), file)))
                save_csv(rfc, config=self.config, outfile=outfile, quoting=0, file_exists='OVERWRITE')
            except Exception:
                self.logger().warning("Problems parsing {}".format(file))

        self.logger().info("Parsing RecentFileCache.bcf finished")


class BAM(base.job.BaseModule):

    def run(self, path=""):
        self.search = GetFiles(self.config, vss=self.myflag("vss"))
        self.vss = self.myflag('vss')
        self.logger().info("Parsing BAM from registry")
        self.parse_BAM()
        return []

    def parse_BAM(self):
        base_path = self.myconfig('{}outdir'.format('v' if self.vss else ''))
        check_folder(base_path)
        SYSTEM = list(self.search.search(r"windows/System32/config/SYSTEM$"))

        partition_list = set()
        for f in SYSTEM:
            aux = re.search(r"([vp\d]*)/windows/System32/config", f, re.I)
            partition_list.add(aux.group(1))

        bam_file = {p: os.path.join(base_path, "bam_%s.txt" % p) for p in partition_list}
        ripcmd = self.config.get('plugins.common', 'rip', '/opt/regripper/rip.pl')

        for f in SYSTEM:
            with open(bam_file[f.split("/")[2]], 'w') as of:
                of.write("-----------------------------------------------------------------------\n{}\n-----------------------------------------------------------------------\n\n".format(f))
                of.write(run_command([ripcmd, "-r", os.path.join(self.myconfig('casedir'), f), "-p", "bam"], logger=self.logger()))
                of.write("\n\n")

        self.logger().info("Finished extraction of Background Activity Moderator (BAM)")
