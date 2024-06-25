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

# based on https://github.com/PoorBillionaire/USN-Journal-Parser

import os
import re
import struct
from collections import OrderedDict
from datetime import datetime, timedelta
from tqdm import tqdm

import base.job
from plugins.common.RVT_disk import getSourceImage
from plugins.common.RVT_filesystem import FileSystem
from base.utils import check_folder, save_csv


class Usn(object):

    def __init__(self, infile):
        self.reasons = OrderedDict()
        self.reasons[0x1] = "DATA_OVERWRITE"
        self.reasons[0x2] = "DATA_EXTEND"
        self.reasons[0x4] = "DATA_TRUNCATION"
        self.reasons[0x10] = "NAMED_DATA_OVERWRITE"
        self.reasons[0x20] = "NAMED_DATA_EXTEND"
        self.reasons[0x40] = "NAMED_DATA_TRUNCATION"
        self.reasons[0x100] = "FILE_CREATE"
        self.reasons[0x200] = "FILE_DELETE"
        self.reasons[0x400] = "EA_CHANGE"
        self.reasons[0x800] = "SECURITY_CHANGE"
        self.reasons[0x1000] = "RENAME_OLD_NAME"
        self.reasons[0x2000] = "RENAME_NEW_NAME"
        self.reasons[0x4000] = "INDEXABLE_CHANGE"
        self.reasons[0x8000] = "BASIC_INFO_CHANGE"
        self.reasons[0x10000] = "HARD_LINK_CHANGE"
        self.reasons[0x20000] = "COMPRESSION_CHANGE"
        self.reasons[0x40000] = "ENCRYPTION_CHANGE"
        self.reasons[0x80000] = "OBJECT_ID_CHANGE"
        self.reasons[0x100000] = "REPARSE_POINT_CHANGE"
        self.reasons[0x200000] = "STREAM_CHANGE"
        self.reasons[0x80000000] = "CLOSE"

        self.attributes = OrderedDict()
        self.attributes[0x1] = "READONLY"
        self.attributes[0x2] = "HIDDEN"
        self.attributes[0x4] = "SYSTEM"
        self.attributes[0x10] = "DIRECTORY"
        self.attributes[0x20] = "ARCHIVE"
        self.attributes[0x40] = "DEVICE"
        self.attributes[0x80] = "NORMAL"
        self.attributes[0x100] = "TEMPORARY"
        self.attributes[0x200] = "SPARSE_FILE"
        self.attributes[0x400] = "REPARSE_POINT"
        self.attributes[0x800] = "COMPRESSED"
        self.attributes[0x1000] = "OFFLINE"
        self.attributes[0x2000] = "NOT_CONTENT_INDEXED"
        self.attributes[0x4000] = "ENCRYPTED"
        self.attributes[0x8000] = "INTEGRITY_STREAM"
        self.attributes[0x10000] = "VIRTUAL"
        self.attributes[0x20000] = "NO_SCRUB_DATA"

        self.sourceInfo = OrderedDict()
        self.sourceInfo[0x1] = "DATA_MANAGEMENT"
        self.sourceInfo[0x2] = "AUXILIARY_DATA"
        self.sourceInfo[0x4] = "REPLICATION_MANAGEMENT"

        self.usn(infile)

    def usn(self, infile):
        self.recordLength = struct.unpack_from("I", infile.read(4))[0]
        self.majorVersion = struct.unpack_from("H", infile.read(2))[0]
        self.minorVersion = struct.unpack_from("H", infile.read(2))[0]

        self.mftEntryNumber = -1
        self.parentMftEntryNumber = -1

        if self.majorVersion == 2:
            self.mftEntryNumber = self.convertFileReference(infile.read(6))
            self.mftSeqNumber = struct.unpack_from("H", infile.read(2))[0]
            self.parentMftEntryNumber = self.convertFileReference(infile.read(6))
            self.parentMftSeqNumber = struct.unpack_from("H", infile.read(2))[0]

        elif self.majorVersion == 3:
            self.referenceNumber = struct.unpack_from("2Q", infile.read(16))[0]
            self.pReferenceNumber = struct.unpack_from("2Q", infile.read(16))[0]

        self.usn = struct.unpack_from("Q", infile.read(8))[0]
        timestamp = struct.unpack_from("Q", infile.read(8))[0]
        self.timestamp = self.convertTimestamp(timestamp)
        reason = struct.unpack_from("I", infile.read(4))[0]
        self.reason = self.convertReason(reason)
        self.sourceInfo = struct.unpack_from("I", infile.read(4))[0]
        self.securityId = struct.unpack_from("I", infile.read(4))[0]
        fileAttributes = struct.unpack_from("I", infile.read(4))[0]
        self.fileAttributes = self.convertAttributes(fileAttributes)
        self.fileNameLength = struct.unpack_from("H", infile.read(2))[0]
        self.fileNameOffset = struct.unpack_from("H", infile.read(2))[0]
        try:
            filename = struct.unpack("{}s".format(self.fileNameLength), infile.read(self.fileNameLength))[0].decode("iso8859-15")
            self.filename = filename.replace("\x00", "")
            self.filename = self.filename
        except Exception:
            self.filename = "%error%"

    def convertFileReference(self, buf):
        byteArray = ["%02x" % i for i in list(buf[::-1])]

        byteString = ""
        for i in byteArray:
            byteString += i

        return int(byteString, 16)

    def convertTimestamp(self, timestamp):
        """ Return a Win32 FILETIME value in a human-readable format """
        try:
            return str(datetime(1601, 1, 1) + timedelta(microseconds=timestamp / 10.))
        except Exception:
            return timestamp

    def convertReason(self, reason):
        """ Return the USN reasons attribute in a human-readable format """
        reasonList = ""

        for i in self.reasons:
            if i & reason:
                reasonList += self.reasons[i] + " "

        return reasonList

    def convertAttributes(self, fileAttributes):
        """ Return the USN file attributes in a human-readable format """
        attrlist = ""
        for i in self.attributes:
            if i & fileAttributes:
                attrlist += self.attributes[i] + " "

        return attrlist


class UsnJrnl(base.job.BaseModule):

    def read_config(self):
        super().read_config()
        self.set_default_config('use_image', False)
        self.set_default_config('vss', False)
        self.set_default_config('volume_id', 'p01')

    def run(self, path=""):
        self.vss = self.myflag('vss')
        self.usn_path = self.myconfig('outdir')
        check_folder(self.usn_path)

        self.filesystem = ''

        if self.myflag('use_image'):
            self.run_with_image()
        else:
            if not os.path.exists(path):
                raise base.job.RVTError('UsnJrnl file {} does not exist'.format(path))
            partition = self.myconfig('volume_id')
            self.run_with_file(path, partition)

        return []

    def run_with_file(self, path, partition='p01'):
        """ Create output files of parsed UsnJrnl """
        # Check file is not empty
        if os.stat(path).st_size == 0:
            self.logger().warning('UsnJrnl file {} is empty'.format(path))
            return []

        # Create dump file
        self.logger().debug('Dumping parsed information from {}'.format(path))
        records = self.parseUsn(infile=path, partition=partition)
        outfile = os.path.join(self.usn_path, "UsnJrnl_dump_{}.csv".format(partition))
        save_csv(records, outfile=outfile, file_exists='OVERWRITE', quoting=0)

        # Create summary file from dump file
        self.logger().debug('Summarizing parsed information from {}'.format(path))
        filtered_records = self.summaryUsn(infile=outfile, partition=partition)
        out_summary = os.path.join(self.usn_path, "UsnJrnl_{}.csv".format(partition))
        save_csv(filtered_records, outfile=out_summary, file_exists='OVERWRITE', quoting=0)

    def run_with_image(self):
        """ Parse UsnJrnl files of a disk """
        disk = getSourceImage(self.myconfig, vss=self.vss)

        self.usn_jrnl_file = os.path.join(self.usn_path, "UsnJrnl")
        self.filesystem = FileSystem(self.config, disk=disk)

        if not self.vss:
            for p in disk.partitions:
                if not p.isMountable:
                    continue
                pname = ''.join(['p', p.partition])
                self._parse_usnjrnl(pname)
        else:
            for p in disk.partitions:
                for v, dev in p.vss_mounted.items():
                    if dev and self.myconfig('source').find(v) != -1:
                        self._parse_usnjrnl(v)

        # Delete the temporal UsnJrnl dumped file
        if os.path.exists(self.usn_jrnl_file):
            os.remove(self.usn_jrnl_file)
        return []

    def _parse_usnjrnl(self, pname):
        """ Get and parses UsnJrnl file for a partition """
        inode = self.filesystem.get_inode_from_path('/$Extend/$UsnJrnl:$J', pname, vss=self.vss)

        if inode == -1:
            self.logger().warning("Problem getting UsnJrnl from partition {}. File may not exist".format(pname))
            return

        # Dumps UsnJrnl file from the data stream $J
        self.logger().debug("Dumping journal file of partition {}".format(pname))
        self.filesystem.icat(inode, pname, output_filename=self.usn_jrnl_file, attribute="$J", vss=self.vss)
        self.logger().debug("Extraction of journal file completed for partition {}".format(pname))

        self.logger().debug("Creating file {}".format(os.path.join(self.usn_path, "UsnJrnl_{}.csv".format(pname))))

        self.run_with_file(self.usn_jrnl_file, pname)

    def parseUsn(self, infile, partition):
        """ Generator that returns a dictionary for every parsed record in UsnJrnl file.

        Args:
            input_file (str): path to UsnJrnl file
            partition (str): partition name
        """
        journalSize = os.path.getsize(infile)
        self.folders = dict()  # Stores filenames associated to directories

        with open(infile, "rb") as f:
            dataPointer = self.findFirstRecord(f)
            f.seek(dataPointer)

            # Estimate number of entries in UsnJrnl for progressBar.
            # Since 96 is a pessimistic average, process should terminate before progressBar reaches 100%.
            estimated_entries = int((journalSize - dataPointer) / 96)
            with tqdm(total=estimated_entries, desc='Parsing UsnJrnl dump_{}'.format(partition)) as pbar:

                total_entries_found = 0
                while True:
                    nextRecord = self.findNextRecord(f, journalSize)
                    total_entries_found += 1
                    if not nextRecord:
                        pbar.update(estimated_entries - total_entries_found)
                        break
                    u = Usn(f)
                    f.seek(nextRecord)
                    try:
                        parent_mft = str(u.parentMftEntryNumber)
                    except Exception:
                        parent_mft = -1

                    if str(u.fileAttributes).find("DIRECTORY") > -1 and u.mftEntryNumber != -1:
                        self.folders[u.mftEntryNumber] = [u.filename, u.parentMftEntryNumber]

                    if u.mftEntryNumber != -1:
                        yield OrderedDict([('Date', u.timestamp),
                                          ('MFT Entry', u.mftEntryNumber),
                                          ('Parent MFT Entry', parent_mft),
                                          ('Filename', u.filename),
                                          ('File Attributes', u.fileAttributes),
                                          ('Reason', u.reason)])
                    pbar.update()
                self.logger().debug('{} journal entries found in partition {}'.format(total_entries_found, partition))

    def summaryUsn(self, infile, partition=None):
        """ Return the relevant records from the UsnJrnl, adding full_path to filename """
        if not partition:
            partition = infile.split('_')[-1][:-4]  # infile in format 'UsnJrnl_dump_p06.csv'

        # Try to guess full path from inode if the source has a valid image and filesystem
        # TODO: use BODY
        use_path_from_inode = True
        if not self.filesystem:
            try:
                disk = getSourceImage(self.myconfig, vss=self.vss)
                if disk.__class__.__name__ == 'DummyImage':
                    self.logger().debug('No filesystem loaded for source {}'.format(self.myconfig('source')))
                    use_path_from_inode = False
                else:
                    self.filesystem = FileSystem(self.config, disk=disk)
            except Exception as exc:
                self.logger().debug('No filesystem loaded for source {}. {}'.format(self.myconfig('source'), exc))
                use_path_from_inode = False

        if use_path_from_inode:
            self.inode_fls = self.filesystem.load_path_from_inode(partition=partition, vss=self.vss)
            self.logger().debug('Correctly loaded inode-name relation file for partiton {}'.format(partition))

        folders = self.complete_dir(self.folders, partition)

        # Fields to filter
        fields = "(RENAME_OLD_NAME|RENAME_NEW_NAME|FILE_DELETE CLOSE|FILE_CREATE CLOSE)"
        out_fields = ['Date', 'Filename', 'Full Path', 'File Attributes', 'Reason', 'MFT Entry', 'Parent MFT Entry', 'Reliable Path']

        base_dir = os.path.join(self.myconfig('source'), 'mnt', partition)
        for record in base.job.run_job(self.config, 'base.input.CSVReader', path=[infile]):
            if re.search(fields, record['Reason']):
                try:
                    # Give priority to folders already found in journal
                    record['Full Path'] = os.path.join(base_dir, folders[int(record['Parent MFT Entry'])][0], record['Filename'])
                    record['Reliable Path'] = folders[int(record['Parent MFT Entry'])][1]
                except Exception:
                    # parent inode not found in journal, inode info is used to complete path
                    record['Full Path'] = ''
                    if use_path_from_inode:
                        try:
                            record['Full Path'] = os.path.join(self.inode_fls[record['Parent MFT Entry']][0], record['Filename'])
                        except:
                            record['Full Path'] = os.path.join('UNKNOWN_PARENT', record['Filename'])
                    record['Reliable Path'] = False

                yield OrderedDict([(i, record[i]) for i in out_fields])

    @staticmethod
    def findFirstRecord(infile):
        """ Returns a pointer to the first USN record found

        Modified version of Dave Lassalle's "parseusn.py"
        https://github.com/sans-dfir/sift-files/blob/master/scripts/parseusn.py

        Args:
            infile (str): filename
        """
        while True:
            data = infile.read(6553600).lstrip(b'\x00')
            if data:
                return infile.tell() - len(data)

    @staticmethod
    def findNextRecord(infile, journalSize):
        """Often there are runs of null bytes between USN records

        This function reads through them and returns a pointer to the start of the next USN record

        Args:
            infile (str): filename
            journalSize (int): size of journal file
        """
        while True:
            try:
                recordLength = struct.unpack_from("I", infile.read(4))[0]
                if recordLength:
                    infile.seek(-4, 1)
                    return (infile.tell() + recordLength)
            except struct.error:
                if infile.tell() >= journalSize:
                    return False

    def complete_dir(self, folders, partition):
        """ Reconstructs absolutepaths of inodes from information of UsnJrnl.
        If it's not possible to reach root folder (inode 5), it uses $MFT entry. Such files are marked as unreliable

        Args:
            folders (list): folders
            partition (str): partiton name
        """

        final_folders = {}  # keys:inode; values:(filename, reliable)
        final_folders[5] = ""  # Root directory
        for entr in folders.keys():
            name = ""
            parent = folders[entr][1]
            actual = entr

            while True:
                if parent == 5:
                    final_folders[entr] = (name, True)
                    break
                if parent in final_folders.keys():
                    final_folders[entr] = (os.path.join(final_folders[parent][0], folders[actual][0], name), final_folders[parent][1])
                    break

                name = os.path.join(folders[actual][0], name)
                actual = parent
                try:
                    parent = folders[parent][1]
                    continue
                except Exception:
                    # Use MFT to complete the path
                    try:
                        final_folders[entr] = (os.path.join(self.inode_fls[str(parent)][0], name), False)
                        break
                    except Exception:
                        final_folders[entr] = (os.path.join("*", name), False)
                        break

        return final_folders
