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

import shutil
import os
import re
import datetime
from tempfile import TemporaryDirectory
import struct
import json

import base.job
from plugins.common.RVT_files import GetFiles
from base.utils import check_directory, relative_path
from base.commands import run_command
from plugins.windows.RVT_lnk import getFileTime, get_macb_from_body


# def getFileTime(data0, data1):
#     if (data0 == 0 and data1 == 0):
#         return 0
#     else:
#         data0 -= 0xd53e8000
#         data1 -= 0x019db1de
#         return int(data1 * 429.4967296 + data0 / 1e7)


class Quarantine(base.job.BaseModule):

    def run(self, path=""):
        """ Unencrypt and extract info about Eset and windows defender quarantine files """

        # Check if there's another quarantine job running
        base.job.wait_for_job(self.config, self, job_name='windows.quarantine')

        self.logger().info("Starting extraction of quarantine files")

        self.Files = GetFiles(self.config, vss=self.myflag("vss"))
        self.mountdir = self.myconfig('mountdir')

        base_path = self.myconfig('outdir')
        check_directory(base_path, create=True)

        eset_list = [os.path.join(self.myconfig('casedir'), f) for f in self.Files.search(r'Local/ESET/ESET Security/Quarantine/.*\.N(Q|D)F$')]
        defender_dirs = [os.path.join(self.myconfig('casedir'), f) for f in self.Files.search(r'ProgramData/Microsoft/Windows Defender/Quarantine/(ResourceData|Entries)$')]
        defender_list = []
        for defdir in defender_dirs:
            for root, dirs, files in os.walk(defdir):
                for name in files:
                    defender_list.append(os.path.join(root, name))

        self.dexray = os.path.join(self.myconfig('rvthome'), "plugins/external/DeXRAY.pl")
        self.dexray = '/usr/local/ncd-scripts/DeXRAY.pl'

        self.logger().info('Found {} eset quarantine files and {} defender quarantine files'.format(len(eset_list), len(defender_list)))
        outdir = os.path.join(base_path)
        check_directory(outdir, create=True)

        body_file = os.path.join(self.config.get('plugins.common', 'timelinesdir'), '{}_BODY.csv'.format(self.config.config['DEFAULT']['source']))
        data = {}
        files_list = defender_list + eset_list
        relative_files_list = files_list
        if len(files_list) > 0 and files_list[0].startswith(self.myconfig('casedir')):  # Path inside casedir
            relative_files_list = [relative_path(file, self.myconfig('casedir')) for file in files_list]

        if not (os.path.exists(body_file) and os.path.getsize(body_file) > 0):
            data = {file: ['1601-01-01T00:00:00Z'] * 4 for file in relative_files_list}
        else:
            data = get_macb_from_body(body_file, relative_files_list)
        with open(os.path.join(base_path, 'quarantine_macb_times.json'), 'w') as f_out:
            f_out.write(json.dumps(data))
            print(data)

        with open(os.path.join(base_path, 'quarantine_metadata.json'), 'w') as f_out:
            for eset_file in eset_list:
                if eset_file.upper().endswith('.NDF'):
                    f_out.write(self.parse_eset(eset_file))
                else:
                    self.decrypt(eset_file, 'eset')

            for defender_file in defender_list:
                if re.search('/Entries/', defender_file):
                    f_out.write(self.parse_defender(defender_file))
                else:
                    self.decrypt(defender_file, 'Defender')
        return []

    def parse_eset(self, path):
        """ Extracts metadata of eset's quarantine file """

        with open(path, 'rb') as fin:
            content = fin.read()

            sep = content[12:16]

            results = {}

            results['path'] = path

            indx = content.find(b'NIWI')
            lw = int.from_bytes(content[indx + 8:indx + 12], byteorder='little')
            hg = int.from_bytes(content[indx + 12:indx + 16], byteorder='little')
            results['Modification'] = datetime.datetime.fromtimestamp(getFileTime(hg, lw), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            lw = int.from_bytes(content[indx + 16:indx + 20], byteorder='little')
            hg = int.from_bytes(content[indx + 20:indx + 24], byteorder='little')
            results['Access'] = datetime.datetime.fromtimestamp(getFileTime(hg, lw), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            lw = int.from_bytes(content[indx + 24:indx + 28], byteorder='little')
            hg = int.from_bytes(content[indx + 28:indx + 32], byteorder='little')
            results['Change metadata'] = datetime.datetime.fromtimestamp(getFileTime(hg, lw), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            results['size'] = struct.unpack('<L', content[20:24])[0]

            indx = content.rfind(sep)
            try:
                results['filepath'] = content[indx + 8:].decode('utf-16le')
            except Exception:
                self.logger().warning("Unable to decode filepath for file in path {}".format(path))
                results['filepath'] = str(content[indx + 8:])

            indx = content.find(sep, 17)
            indx2 = content.find(b'\x00\x00\x00\x00', indx + 12)
            try:
                results['Malware type'] = content[indx + 12:indx2 + 1].decode('utf-16le')
            except Exception:
                self.logger().warning("Unable to decode malware type for file in path {}".format(path))
                results['Malware type'] = str(content[indx + 12:indx2 + 1])
            return json.dumps(results)

    def parse_defender(self, path):
        """ Extracts metadata of Windows defender's quarantine file """

        with TemporaryDirectory() as temp_dir:
            shutil.copy2(path, temp_dir)
            filepath = os.path.join(temp_dir, os.path.basename(path))
            run_command([self.dexray, filepath])
            decrypted_file = '%s.00000000_defender.out' % os.path.join(temp_dir, os.path.basename(path))
            results = {}

            results['path'] = path

            content = ''
            try:
                with open(decrypted_file, 'rb') as fin:
                    content = fin.read()
            except:
                self.logger().warning("Decrypted file {} not found. Skipping metadata parsing".format(decrypted_file))
                return json.dumps(results)

            lw = int.from_bytes(content[96:100], byteorder='little')
            hg = int.from_bytes(content[100:104], byteorder='little')
            results['Detection'] = datetime.datetime.fromtimestamp(getFileTime(hg, lw), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Next timestamps should be tested deeply
            try:

                indx2 = content.find(b'file\x00\x00')
                indx = content.find(b'\x00\x00\x08\x00', indx2) + 10
                lw = int.from_bytes(content[indx:indx + 4], byteorder='little')
                hg = int.from_bytes(content[indx + 4:indx + 8], byteorder='little')
                results['Modification'] = datetime.datetime.fromtimestamp(getFileTime(hg, lw), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                lw = int.from_bytes(content[indx + 12:indx + 16], byteorder='little')
                hg = int.from_bytes(content[indx + 16:indx + 20], byteorder='little')
                results['Access'] = datetime.datetime.fromtimestamp(getFileTime(hg, lw), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                lw = int.from_bytes(content[indx + 24:indx + 28], byteorder='little')
                hg = int.from_bytes(content[indx + 28:indx + 32], byteorder='little')
                results['Change metadata'] = datetime.datetime.fromtimestamp(getFileTime(hg, lw), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

            # a = 0
            # while a > -1:
            #     a1 = content.find(b'\x08\x00\x11\x60', a + 1) # Possible separator before file metadata
            #     a = a1
            #     if a > 0:
            #         print(content[a + 10:a + 19]) # lw and hg filetime date

            indx = content.find(b'\x00', 112)
            results['Malware type'] = content[112:indx].decode()
            indx2 = content.find(b'\x00\x00', indx + 8)
            results['filepath'] = content[indx + 8:indx2].decode('utf-16be')

            # # Next code is an example of possible relationship between Entries and ResourceData files
            # content = ''
            # with open('Resources/07/0708AA8C704D495E462A3C1724F22D407392137D.00000000_defender.out', 'rb') as fin:
            #     content = fin.read()

            # ba = bytearray(content[-16:]).hex()
            # print("{}-{}-{}-{}-{}".format(ba[6:8] + ba[4:6] + ba[2:4] + ba[:2], ba[8:12], ba[12:16], ba[16:20], ba[20:]))

            return json.dumps(results)

    def decrypt(self, filename, antivir):
        """ decrypt files and moves to case quarantine folder """

        with TemporaryDirectory() as temp_dir:
            shutil.copy2(filename, temp_dir)
            filepath = os.path.join(temp_dir, os.path.basename(filename))

            run_command([self.dexray, filepath])
            for i in os.listdir(temp_dir):
                if i.endswith('.out'):
                    decrypted_file = os.path.join(temp_dir, i)
            shutil.copy2(decrypted_file, self.myconfig('outdir'))
