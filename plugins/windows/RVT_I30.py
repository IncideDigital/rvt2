#!/usr/bin/env python3
#
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

# Main reference: File System Forensic Analysis by Brian Carrier, tables 13.12 to 13.17
# Based on https://github.com/williballenthin/INDXParse/blob/master

import struct
import array
import os
import subprocess
import shlex
import logging
from datetime import datetime, timedelta
from collections import OrderedDict
from tqdm import tqdm

import base.job
from base.utils import check_directory, save_csv
from plugins.common.RVT_disk import getSourceImage
from plugins.common.RVT_filesystem import FileSystem

# TODO: improve efficiency of INDX_ROOT records extraction
# TODO: Filenames with short_filename format are excluded even if the name is defined this way. skip_short_filenames may be redefined to call complete_name() before skipping, but for deleted entries is not possible to distinguish them.

INDEX_NODE_BLOCK_SIZE = 4096


def parse_windows_timestamp(timestamp):
    """ Return a datetime object from a windows timestamp (only up to the second precission, strips nanoseconds). """
    # see http://integriography.wordpress.com/2010/01/16/using-phython-to-parse-and-present-windows-64-bit-timestamps/
    return datetime.utcfromtimestamp(int(float(timestamp) * 1e-7 - 11644473600))


def datetime_to_windows_timestamp(dt):
    return (dt.timestamp() + 11644473600) * 1e7


# Reference time limits to detect correct timestamps
_ts_1971 = datetime_to_windows_timestamp(datetime(1971, 1, 1, 0, 0, 0))
_ts_future = datetime_to_windows_timestamp(datetime.now() + timedelta(days=365))


class ParseINDX(base.job.BaseModule):
    """ Parse INDX records in a disk through carving.

    Configuration:
        - **root**: If True, parse also INDX_ROOT attributes.
        - **skip_short**: If True, do not output Windows short format filenames.
        - **only_slack**: If True, parse only the slack space in INDX_ALLOC blocks.
        - **use_localstore**: If True, store information about last parsed block in case execution is interrupted
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('root', False)
        self.set_default_config('skip_short', True)
        self.set_default_config('qonly_slack', False)
        self.set_default_config('use_localstore', True)

    def run(self, path=""):
        """ Generator of INDX entries as dictionaries. Also writes to csv files"""
        self.disk = getSourceImage(self.myconfig)
        self.sector_size = self.disk.sectorsize

        self.parseINDX_ROOTFiles = self.myflag('root', False)  # Parse also INDX_ROOT records if set
        self.skip_short_filenames = self.myflag('skip_short', False)
        self.only_slack = self.myflag('only_slack', False)

        outdir = self.myconfig('outdir')
        check_directory(outdir, create=True)

        for p in self.disk.partitions:
            if not p.isMountable:
                continue

            # Get a dictionary {inode: list of names} from 'fls' to later relate inodes to a path. 'inode' keys are strings, not int.
            part_name = ''.join(['p', p.partition])
            try:
                self.inode_fls = FileSystem(self.config).load_path_from_inode(partition=part_name)
                self.logger().debug('Correctly loaded inode-name relation file for partiton {}'.format(part_name))
            except Exception as e:
                self.logger().error(e)
                continue

            # Start the carving at next to last execution block parsed
            outfile = os.path.join(outdir, '{}{}_INDX_timeline.csv'.format(part_name, '_slack' if self.only_slack else ''))
            self.lastParsedBlk = 0
            if self.myflag('use_localstore'):
                self.lastParsedBlk = int(self.config.store_get('last_{}_block_parsed'.format(part_name), 0))
            self.logger().debug('lastParsedBlk: {}'.format(self.lastParsedBlk))

            csv_args = {'file_exists': 'APPEND', 'write_header': True}
            if self.lastParsedBlk:
                if not os.path.exists(outfile):
                    self.logger().warning('Starting new file {0} at an advanced offset. Set "last_{0}_block_parsed" at 0 in "store.ini" if a fresh start is desired'.format(outfile))
                else:
                    csv_args['write_header'] = False
            else:
                if os.path.exists(outfile):
                    self.logger().warning('Overwriting file {}'.format(outfile))
                    csv_args['file_exists'] = 'OVERWRITE'

            # Write the parsed entries to a csv file for each partition.
            save_csv(self.parse_INDX(p), config=self.config, outfile=outfile, quoting=0, **csv_args)
        return []

    def parse_INDX(self, partition=None):
        """ Main function to parse I30 files.
        Parse and yield INDX records for both ROOT and ALLOC entries in a partition. """

        # Yield INDX_ROOT records (with at least one INDX entry) for all directories in a partition.
        rootRecordsFound = 0
        if self.parseINDX_ROOTFiles:
            self.logger().info('Processing INDX_ROOT records of partition {}'.format(partition.partition))
            for rec in self.parse_INDX_ROOT_records(partition):
                rootRecordsFound += 1
                yield rec
            self.logger().info('Done with INDX_ROOT records of partition {}'.format(partition.partition))

        # Yield INDX_ALLOC records at INDEX_NODE_BLOCK_SIZE (default is 4096) offset from the start of a partition
        self.allocRecordsFound = 0
        self.slackRecordsFound = 0
        for rec in self.parse_INDX_ALLOC_records(partition):
            yield rec

        self.logger().info('Root records found: {}\nAlloc records found: {}\nAlloc slack records found: {}'.format(rootRecordsFound, self.allocRecordsFound, self.slackRecordsFound))

    def parse_INDX_ROOT_records(self, partition=None):
        """ Yield dicts of parsed INDX_ROOT entries for a partition. """
        for deleted in [False, True]:
            for b, inode, path in self.get_INDX_ROOT_files(partition, deleted=deleted):
                h = NTATTR_INDEX_ROOT_HEADER(b, 0, False, inode_fls=self.inode_fls, dir_inode=inode)
                for e in h.entries():
                    e.deleted = deleted
                    e.root_entry = True

                    fn = e.filename()
                    # Skip short filename entries if selected
                    if self.skip_short_filenames and e.short_filename:
                        continue

                    yield entry_as_dict(e, fn)

    def get_INDX_ROOT_files(self, partition, deleted=0):
        """ Yields INDX_ROOT attribute records, scanning each directory recursively in MFT.

            Arguments
            partition: Partition object.
            deleted: Get only deleted (True) or undeleted (False) directories
        """
        # Get every 'inode' associated with a directory 'path'
        imagefile = partition.imagefile if not partition.encrypted else partition.loop
        cmd = 'fls -{}prD -o {} {}'.format('d' if deleted else 'u', int(partition.osects), imagefile)

        with subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE) as proc:
            for line in proc.stdout:
                # line format output: b"d/d * 59-144-6:	    Program Files\n"
                # where * only appears on deleted files
                fields = line.strip().decode('utf-8').split()
                if deleted:
                    large_inode, path = fields[2].rstrip(':'), ' '.join(fields[3:])
                else:
                    large_inode, path = fields[1].rstrip(':'), ' '.join(fields[2:])
                inode = int(large_inode.split('-')[0])

                cmd_icat = 'icat -o {} {} {}'.format(int(partition.osects), imagefile, large_inode)
                try:
                    # self.logger().debug(': Processing INDX_ROOT of inode {}'.format(large_inode))
                    rootData = subprocess.check_output(shlex.split(cmd_icat))
                except Exception as e:
                    self.logger().error(e)
                    continue
                rootArray = array.array("B", rootData)
                if len(rootArray) > 0x20 + 0x52:  # Skip INDX_ROOT too small to have any valid entry
                    yield rootArray, inode, path

        # Get INDX_ROOT record for inode 5 (root directory). It is not listed by fls
        cmd_icat = 'icat -o {} {} {}'.format(int(partition.osects), imagefile, '5-144')
        try:
            rootData = subprocess.check_output(shlex.split(cmd_icat))
        except Exception as e:
            self.logger().error(e)
        rootArray = array.array("B", rootData)

        # Yield only INDX_ROOT big enough to contain any valid entry
        if len(rootArray) > 0x20 + 0x52:
            yield (rootArray, 5, '')

    def parse_INDX_ALLOC_records(self, partition=None):
        """ Yield dicts of parsed INDX_ALLOC entries for a partition. """
        for b, blk_offset in self.get_INDX_ALLOC_files(partition):
            # self.logger().debug('Processing INDX_ALLOC record at sector offset: {}'.format(blk_offset))
            h = NTATTR_STANDARD_INDEX_HEADER(b, 0, False, inode_fls=self.inode_fls, blk_offset=blk_offset)

            methods = [h.slack_entries] if self.only_slack else [h.entries, h.slack_entries]
            for method in methods:
                for e in method():
                    e.root_entry = False

                    fn = e.filename()
                    # Skip short filename entries if selected
                    if self.skip_short_filenames and e.short_filename:
                        continue

                    if method.__name__ == 'slack_entries':
                        e.deleted = True
                        self.slackRecordsFound += 1
                    else:
                        e.deleted = False
                        self.allocRecordsFound += 1

                    yield entry_as_dict(e, fn)

    def get_INDX_ALLOC_files(self, partition):
        """ Yields INDX_ALLOC records (single clusters), parsing the partition block by block.
        Only blocks starting with "INDX(" signature header are returned to be parsed.

        Parameters:
            partition: Partition object.
        """
        indxBytes = "494e445828000900"  # 49 4e 44 58 28 00 09 00  "INDX(" header
        offset = int(partition.obytes)
        partition_end_offset = offset + partition.size
        total_blocks = int(partition.size / INDEX_NODE_BLOCK_SIZE)
        imagefile = partition.imagefile if not partition.encrypted else partition.loop
        part_name = ''.join(['p', partition.partition])

        # Use a progress bar, showing the number of blocks processed in the partition
        with tqdm(total=total_blocks - self.lastParsedBlk, desc='Parse_I30 {}'.format(part_name)) as pbar:
            with open(imagefile, 'rb') as image:
                # Start at the beginnig of partition or at next to the last parsed block.
                # Caution: Output entries may be repeated in lastParsedBlk + 1 if execution was stopped at half parsing of that block.
                offset += (self.lastParsedBlk + 1) * INDEX_NODE_BLOCK_SIZE
                if offset >= partition_end_offset:
                    self.logger().warning('Starting block offset exceeding partition {} limits. No blocks left to parse'.format(part_name))
                    return []
                blkOffset = self.lastParsedBlk + 1

                image.seek(offset)
                # Main carving loop
                while offset < partition_end_offset:
                    byteChunk = image.read(INDEX_NODE_BLOCK_SIZE)  # Only searching for cluster aligned (4096 on Windows Server 2003) INDX records

                    if byteChunk[0:8].hex() == indxBytes:  # Compare I30 header signature
                        byteArray = array.array("B", byteChunk)

                        yield byteArray, blkOffset

                        # save the last parsed block
                        if self.myflag('use_localstore'):
                            self.config.store_set('last_{}_block_parsed'.format(part_name), str(blkOffset))

                    offset = offset + INDEX_NODE_BLOCK_SIZE
                    blkOffset += 1
                    pbar.update()

                # if the end is reached, clean last_block_parsed: next time will be a full carving again
                if self.myflag('use_localstore'):
                    self.config.store_set('last_{}_block_parsed'.format(part_name), '0')


class OverrunBufferException(Exception):
    def __init__(self, readOffs, bufLen):
        tvalue = "read: {read}, buffer length: {length}".format(
                 read=readOffs,
                 length=bufLen)
        super(OverrunBufferException, self).__init__(tvalue)


class Block(object):
    """ Base class for structure blocks in the NTFS INDX format. A block is associated with an offset into a byte-string. """
    def __init__(self, buf, offset, parent=False, inode_fls=None, dir_inode=None, **kwargs):
        """
        Arguments:
        - `buf`: Byte-string containing NTFS INDX file.
        - `offset`: The offset into the buffer at which the block starts.
        - `parent`: The parent block, which links to this block. If subclass is an ENTRY class, parent is a HEADER class
        - `inode_fls`: Dictionary associating each inode with a list of filenames
        - `dir_inode` : Inode of the directory associated with the block. Only make sense for HEADER classes
        """
        self._buf = buf
        self._offset = offset
        self._parent = parent
        self._directory_inode = dir_inode
        self._inode_fls = inode_fls

        self.logger = logging.getLogger('INDX')

    def unpack_integer(self, offset=0x00, format='<B'):
        """ Returns an integer from the buffer at 'offset', extracting in the specified 'format'.

        Arguments:
        - `offset`: The relative offset from the start of the block.
        - `format`: Struct format string.
        Throws:
        - `OverrunBufferException`
        """
        # List of available formats at https://docs.python.org/3/library/struct.html
        assert format[1] in ('b', 'B', 'h', 'H', 'i', 'I', 'l', 'L', 'q', 'Q')
        o = self._offset + offset
        try:
            return struct.unpack_from(format, self._buf, o)[0]
        except struct.error:
            raise OverrunBufferException(o, len(self._buf))

    def unpack_bytestring(self, offset, length):
        """ Returns a byte-string from the relative 'offset' with the given 'length'. """

        o = self._offset + offset
        try:
            return struct.unpack_from("<{}s".format(length), self._buf, o)[0]
        except struct.error:
            raise OverrunBufferException(o, len(self._buf))

    def pack_integer(self, offset, us_integer):
        """ Inserts the little-endian unsigned short 'us_integer' to the relative 'offset'. """
        o = self._offset + offset
        try:
            return struct.pack_into("<H", self._buf, o, us_integer)
        except struct.error:
            raise OverrunBufferException(o, len(self._buf))

    def absolute_offset(self, offset):
        """ Get the absolute offset from an offset relative to this block """
        return self._offset + offset

    def parent(self):
        """ Get the parent block. See the class documentation for what the parent link is. """
        return self._parent

    def offset(self):
        """ Equivalent to self.absolute_offset(0x0), which is the starting offset of this block. """
        return self._offset

    def blk_offset(self):
        """ Get the block offset respective to the beggining of the partition. """
        return self._blk_offset

    @staticmethod
    def align(offset, alignment):
        """ Return the offset aligned to the nearest greater given alignment
        Arguments:
        - `offset`: An integer
        - `alignment`: An integer
        """
        if offset % alignment == 0:
            return offset
        return offset + (alignment - (offset % alignment))


class NTATTR_INDEX_ROOT_HEADER(Block):
    """ INDX_ROOT block header fields. Methods to generate entry instances for the block. """
    # 0x0         DWORD TypeOfAttributeInIndex
    # 0x4         DWORD CollationSortingRule
    # 0x8         DWORD IndexRecordSizeInBytes
    # 0xC         BYTE IndexRecordSizeInBytes
    # 0x10        DWORD indexEntryOffset;
    # 0x14        DWORD sizeOfEntries;
    # 0x18        DWORD sizeOfEntriesAlloc;
    # 0x1C        BYTE flags;

    root_header_attr = dict(
        TypeOfAttributeInIndex=(0x0, '<I'),
        IndexRecordSizeInBytes=(0x8, '<I'),
        EntryStartOffset=(0x10, '<I'),
        EntrySizeOffset=(0x14, '<I'),
        EntryAllocatedSizeOffset=(0x18, '<I'),
        flags=(0x1C, '<B'),
    )

    def __init__(self, buf, offset=0, parent=False, *args, **kwargs):
        super(NTATTR_INDEX_ROOT_HEADER, self).__init__(buf, offset, False, *args, **kwargs)

        # Consistency checks of size and type:
        self.type_of_attribute = self.unpack_integer(*self.root_header_attr['TypeOfAttributeInIndex'])
        if self.type_of_attribute != 48:  # 48 is $FILE_NAME
            self.logger.warning('Type of attribute {} found. Should be 48'.format(self.type_of_attribute))
        # assert(self.type_of_attribute == 48)
        self.index_record_size = self.unpack_integer(*self.root_header_attr['IndexRecordSizeInBytes'])
        if self.index_record_size != INDEX_NODE_BLOCK_SIZE:
            self.logger.warning('Index record size: ({}) not {}'.format(self.index_record_size, INDEX_NODE_BLOCK_SIZE))
        # assert(self.index_record_size == INDEX_NODE_BLOCK_SIZE)

        self._blk_offset = self._directory_inode  # In ROOT files, show inode for reference instead of block offset

    def entry_offset(self):
        """ Get the offset of the first entry in this record. Relative to node header. """
        return self.unpack_integer(*self.root_header_attr['EntryStartOffset'])

    def entries_size(self):
        """ Get the offset at which assigned entries end. Relative to node header. """
        return self.unpack_integer(*self.root_header_attr['EntrySizeOffset'])

    def entries_allocated_size(self):
        """ Get the offset at which all entries end. Relative to node header. """
        return self.unpack_integer(*self.root_header_attr['EntryAllocatedSizeOffset'])

    def entries(self):
        """ Gnerator of INDX entries in INDX_ROOT data """
        # First entry (at offset 0x20, 0x10 with respect node header)
        e = NTATTR_DIRECTORY_INDEX_ENTRY(self._buf, 0x10 + self.entry_offset(), self, blk_offset=self.blk_offset())

        if not e.is_valid():
            self.logger.info('First ROOT allocated entry not valid at inode {}'.format(self._blk_offset))
            return

        yield e
        while e.has_next():
            e = e.next()
            yield e


class NTATTR_STANDARD_INDEX_HEADER(Block):
    """ INDX_ALLOC block header fields. Methods to generate entry instances for the block. """
    # 0x0         char magicNumber[4]; // == "INDX"
    # 0x4         unsigned short updatedSequenceArrayOffset;
    # 0x6         unsigned short sizeOfUpdatedSequenceNumberInWords;
    # 0x8         LONGLONG logFileSeqNum;
    # 0x10        LONGLONG thisVirtualClusterNumber;
    # 0x18        DWORD indexEntryOffset;
    # 0x1C        DWORD sizeOfEntries;
    # 0x20        DWORD sizeOfEntriesAlloc;
    # 0x24        BYTE flags;
    # 0x25        BYTE padding[3];
    # 0x28        unsigned short updateSeq;
    # 0x2A        WORD updatedSequenceArray[sizeOfUpdatedSequenceNumberInWords];

    header_attr = dict(
        NumFixupsOffset=(0x6, '<H'),
        EntrySizeOffset=(0x1C, '<I'),
        EntryAllocatedSizeOffset=(0x20, '<I'),
        fixupValueOffset=(0x28, '<H'),
    )

    def __init__(self, buf, offset, parent, *args, **kwargs):
        """ Constructor.
        Arguments:
        - `buf`: Byte-string containing NTFS INDX file
        - `offset`: The offset into the buffer at which the block starts.
        - `parent`: The parent block, which links to this block.
        """
        super(NTATTR_STANDARD_INDEX_HEADER, self).__init__(buf, offset, parent, *args, **kwargs)

        # Note: NTATTR_SDH_INDEX_ENTRY and NTATTR_SII_INDEX_ENTRY are not implemented.
        self.index_type = {
            'dir': NTATTR_DIRECTORY_INDEX_ENTRY,
            'sdh': NTATTR_SDH_INDEX_ENTRY,
            'sii': NTATTR_SII_INDEX_ENTRY
        }

        self._blk_offset = kwargs['blk_offset']
        self._fixup_array_offset = 0x2A
        self.num_fixups = self.unpack_integer(*self.header_attr['NumFixupsOffset'])
        self.fixup_value = self.unpack_integer(*self.header_attr['fixupValueOffset'])

        # Check if fixup array is empty
        self._valid_fixups = True
        interval_start = self._offset + self._fixup_array_offset
        interval_end = interval_start + (self.num_fixups - 1) * 2
        if self._buf[interval_start:interval_end] == "\x00\x00" * (self.num_fixups - 1):
            self._valid_fixups = False
            self.logger.warning('Fixup array is empty')

        # Change (patch) the fixup values in the buffer
        for i in range(0, self.num_fixups - 1):
            fixup_offset = 512 * (i + 1) - 2
            check_value = self.unpack_integer(fixup_offset, '<H')
            if check_value != self.fixup_value:
                self.logger.debug('Bad fixup at {}'.format(self.offset() + fixup_offset))
                continue
            new_value = self.unpack_integer(self._fixup_array_offset + 2 * i, '<H')
            self.pack_integer(fixup_offset, new_value)  # Bytes substitution in the buffer
            check_value = self.unpack_integer(fixup_offset, '<H')

        self._first_entry = self.first_entry()
        self.set_directory_inode(self._first_entry)

    def entry_offset(self):
        """ Get the offset of the first entry in this record. Relative to node header. """
        string_end = self.offset()
        string_end += self._fixup_array_offset
        string_end += 2 * self.num_fixups
        return self.align(string_end, 8)

    def entries_size(self):
        """ Get the offset at which assigned entries end. Relative to node header. """
        return self.unpack_integer(*self.header_attr['EntrySizeOffset'])

    def entries_allocated_size(self):
        """ Get the offset at which all entries end. Relative to node header. """
        return self.unpack_integer(*self.header_attr['EntryAllocatedSizeOffset'])

    def block_end_offset(self):
        """ Return the first address (offset) not a part of this block. """
        # All remaining data in the block is treated as slack when _valid_fixups is False
        if not self._valid_fixups:
            return self.offset() + INDEX_NODE_BLOCK_SIZE
        else:
            return self.offset() + self.entries_allocated_size()

    def set_directory_inode(self, first_entry=None):
        """ Return the inode of the directory associated with this block.
        Arguments:
        - `entry`: the first entry of the block, to be taken as reference
        """
        if not first_entry:
            self._directory_inode = 0
            return

        inode = first_entry.get_inode('refParentDirectory')
        if not inode:
            self.logger.info('Directory inode is 0 at block {}'.format(self.blk_offset()))
            self._directory_inode = 0
            return
        if str(inode) not in self._inode_fls:
            self.logger.info('Directory inode is invalid at block {}'.format(self.blk_offset()))
            self._directory_inode = 0
            return

        # If inode from 'refParentDirectory' of the first allocated entry exists in the MFT, take it as the parent reference for all block
        self._directory_inode = inode

    def first_entry(self, indext='dir'):
        """ Return the first entry in the allocated space, if it's a valid one. """
        try:
            entry_class = self.index_type[indext]
        except KeyError:
            raise Exception("Unsupported index type: {}.".format(indext))

        if self.entry_offset() - self.offset() >= self.entries_size():
            self.logger.debug(": No allocated entries in this INDX_ALLOC block. {} > {}".format(self.entry_offset() - self.offset(), self.entries_size()))
            return

        if not self._valid_fixups:
            self.logger.debug(": No fixups, so assuming no valid regular entries in the block {}.".format(self.blk_offset()))
            return

        # It appears in some cases, the .entry_offset field is relative from the NTATTR_STANDARD_INDEX_HEADER ("INDX(...")
        # Other times (maybe often volume root directories?) is relative from the INDEX_HEADER (first field is entries_offset).
        # To check, look for an empty value where the parent directory reference should be.
        if ("\x00" * 8) == self._buf[self.entry_offset():self.entry_offset() + 8].tostring():
            # 0x18 is relative offset from NTATTR_STANARD_INDEX_HEADER to he INDEX_HEADER sub-struct
            e = entry_class(self._buf, 0x18 + self.entry_offset(), parent=self, blk_offset=self.blk_offset())
        else:
            e = entry_class(self._buf, self.entry_offset(), parent=self, blk_offset=self.blk_offset())

        # It seems that next regular entries are also invalid if the first is not valid
        if not e.is_valid():
            self.logger.info('First allocated entry not valid at block offset {}'.format(self._blk_offset))
            self._valid_fixups = False  # That's not exact but it's used in slack_entries method
            return

        return e

    def entries(self, indext='dir'):
        """ A generator that returns each INDX entry associated with this header. """
        # self.logger.debug('Processing allocated entries for block {}'.format(self._blk_offset))
        if not self._first_entry:
            return

        e = self._first_entry
        yield e

        while e.has_next():   # TODO: assuming all but the first are valid. Not necessarily True
            # # sizeOfEntries may be wrong in some blocks, so even entries not marked as slack must be checked
            # if not e.is_valid():
            #     self.logger.warning('Invalid entry: inode: {} | filename: {} | block: {}'.format(elf._directory_inode, e.filename(), self._blk_offset)))
            #     e = e.next()
            #     continue
            e = e.next()
            yield e

    def slack_entries(self, indexdt='dir'):
        """ A generator that yields INDX entries found in the slack space associated with this header. """
        # Treat all block as slack if first allocated entry is invalid
        off = self.offset() + self.entries_size() if self._first_entry else self.offset() + 0x28
        # self.logger.debug('Deleted entries offset is {} at block {}'.format(off, self.blk_offset()))

        # NTATTR_STANDARD_INDEX_ENTRY is at least 0x52 bytes long, so don't overrun, but if we do, then we're done
        try:
            while off < self.block_end_offset() - 0x52:
                # self.logger.debug("Trying to find slack entry at {}.".format(off))
                e = NTATTR_DIRECTORY_INDEX_SLACK_ENTRY(self._buf, off, self, blk_offset=self.blk_offset())
                if e.is_empty():
                    off += 40
                    # self.logger.debug('Scanning 40 bytes forward')
                    continue

                if e.is_valid():
                    # self.logger.debug('Slack entry is valid.')
                    off = e.end_offset()
                    yield e
                else:
                    # self.logger.debug('Scanning 8 bytes forward')
                    off += 8  # I've only seen entries beggining at 0 or 8 bytes offsets
        except struct.error:
            self.logger.warning('Slack entry parsing overran buffer.')
            return
        # self.logger.debug('Done with slack entries at block {}'.format(self.blk_offset()))


class NTATTR_STANDARD_INDEX_ENTRY(Block):
    """ Generic index entry block node fields. """

    # 0x00-0x07 entry-type-specific
    # 0x08      unsigned short  sizeOfIndexEntry;
    # 0x0A      unsigned short  sizeOfStream;
    # 0x0C      unsigned short  flags;
    generic_attr = dict(
        sizeOfIndexEntry=(0x8, '<H'),
        sizeOfStream=(0xA, '<H'),
        flags=(0xC, '<H'),
    )

    def __init__(self, buf, offset, parent, *args, **kwargs):
        """ Constructor.
        Arguments:
        - `buf`: Byte string containing NTFS INDX file
        - `offset`: The offset into the buffer at which the block starts.
        - `parent`: The parent NTATTR_STANDARD_INDEX_HEADER block, which links to this block.
        """
        super(NTATTR_STANDARD_INDEX_ENTRY, self).__init__(buf, offset, parent, *args, **kwargs)
        self._blk_offset = kwargs['blk_offset']

    def size(self):
        """ Get the size of the index entry. """
        return self.unpack_integer(*self.generic_attr['sizeOfIndexEntry'])

    def end_offset(self):
        """ Return the first address (offset) not a part of this entry. """
        size = self.size()
        if size > 0:
            return self.offset() + size
        else:
            raise Exception("0 index entry size presented to generic end_offset()")

    def has_next(self):
        """ True if the end offset of the entry does not overrun the total entries size. """
        entry_end = self.end_offset() - self.parent().offset()
        # self.logger.debug('Entry end: {} | Parent end offset: {}'.format(entry_end, self.parent().entries_size()))
        # Althougth parent.entrysize should be at least 0x10 smaller than last entries_length, substract 0x8 to catcth slack entries with 0X1C missing info
        return entry_end < self.parent().entries_size() - 0x8  # substract 0x8 just to be safe

    def next(self):
        """ Return an instance of NTATTR_STANDARD_INDEX_ENTRY, which is the next entry after this one """
        # assert self.has_next()
        return self.__class__(self._buf, self.end_offset(), self.parent(), blk_offset=self.blk_offset())


class NTATTR_DIRECTORY_INDEX_ENTRY(NTATTR_STANDARD_INDEX_ENTRY):
    """ Main class for individual entries related to directory INDX records. """
    # 0x0    LONGLONG mftReference;
    # 0x8    unsigned short sizeOfIndexEntry;
    # 0xA    unsigned short sizeOfStream;
    # 0xC    unsigned short flags;
    # 0xE    BYTE padding[2];

    # FILENAME_INFORMATION
    # 0x10    LONGLONG refParentDirectory;
    # 0x18    FILETIME creationTime;
    # 0x20    FILETIME lastModifiedTime;
    # 0x28    FILETIME MFTRecordChangeTime;
    # 0x30    FILETIME lastAccessTime;
    # 0x38    LONGLONG physicalSizeOfFile;
    # 0x40    LONGLONG logicalSizeOfFile;
    # 0x48    DWORD    flags;
    # 0x4C    DWORD    extendedAttributes;
    # 0x50    unsigned BYTE filenameLength;
    # 0x51    NTFS_FNAME_NSPACE filenameType;
    # 0x52    wchar_t filename[filenameLength];
    # 0xXX    Padding to 8-byte boundary

    attributes = dict(
        mftReference=(0x0, '<I'),
        sizeOfIndexEntry=(0x8, '<H'),
        sizeOfStream=(0xA, '<H'),
        flags=(0xC, '<H'),
        padding=(0xE, '<B'),
        refParentDirectory=(0x10, '<I'),
        creationTime=(0x18, '<Q'),
        lastModifiedTime=(0x20, '<Q'),
        MFTRecordChangeTime=(0x28, '<Q'),
        lastAccessTime=(0x30, '<Q'),
        physicalSizeOfFile=(0x38, '<Q'),
        logicalSizeOfFile=(0x40, '<Q'),
        filenameLength=(0x50, '<B')
    )

    def __init__(self, buf, offset, parent, *args, **kwargs):
        """ Constructor.
        Arguments:
        - `buf`: Array of bytes containing NTFS INDX file
        - `offset`: The offset into the buffer at which the block starts.
        - `parent`: The parent NTATTR_STANDARD_INDEX_HEADER block, which links to this block.
        """
        super(NTATTR_DIRECTORY_INDEX_ENTRY, self).__init__(buf, offset, parent, *args, inode_fls=parent._inode_fls, **kwargs)
        self._filename_offset = 0x52
        self.fn = None   # Filename. Initialize at None.
        # Through empirical testing, recovering the filename type of slack entries doesn't work well

    def end_offset(self):
        """ Return the first address (offset) not a part of this entry. """
        size = self.size()
        if size > 0:
            return self.offset() + size

        string_end = self.offset() + self._filename_offset + \
            2 * self.unpack_integer(*self.attributes['filenameLength'])
        return self.align(string_end, 8)

    def filename(self):
        """ Get filename from FILE_NAME attribute. Mark short format Windows filenames. """
        if self.fn:
            return self.fn  # Use the previous output if the method has already been called

        self.short_filename = False
        # Filename is in UTF16 encoding. Filename length is expressed in UTF16 chars, so half the length in bytes.
        try:
            self.fn = self.unpack_bytestring(self._filename_offset, 2 * self.unpack_integer(*self.attributes['filenameLength'])).decode('utf16')
            # Note: Some large filenames may have a shortfilename format. They would be wrongly marked as Windows short filenames.
            #       complete_names method allows it to happen if there is a correct match between parent_dir+FILENAME and MFTname
            base_name = self.fn.split('.')[0]
            if len(base_name) <= 8 and len(base_name) >= 3 and base_name[-2] == '~' and (base_name.isupper() or base_name[:-2].isnumeric()):
                self.short_filename = True
        except UnicodeDecodeError:
            self.fn = "ERROR DECODING FILENAME"
        except OverrunBufferException:  # In valid entries this exception should never happen.
            self.fn = "FILENAME EXCEDING BUFFER LENGTH"

        return self.fn

    def get_inode(self, attr):
        """ For inode associated attributes, extract and return the inode number. """
        return self.unpack_integer(*self.attributes[attr])

    def mft_name(self):
        """ Return the list of files associated with the entry inode.
        'NO FILENAME ASSOCIATED WITH INODE' is returned if inode have no names associated.
        """
        inode = self.get_inode('mftReference')
        # Many deleted files are associated with inode 0.
        # This method should return ['$MFT'] in that cases, and complete_name() will return 'NOT OBTAINED' except FILENAME is precisely $MFT
        # Can't use dict.get() because _inode_fls is a defaultdict and will generate a new entry if not found, making 'key in dict' invalid next time
        if str(inode) not in self._inode_fls:
            self._entry_inode = 0
            return ['NO FILENAME ASSOCIATED WITH INODE']
        self._entry_inode = inode
        return self._inode_fls[str(inode)]

    def entry_inode(self):
        return self._entry_inode

    def parent_directory(self):
        """ Return the list of directories associated with the entry parent inode. Mark unreliable directories. """
        self.reliable_inode = True
        inode = self.get_inode('refParentDirectory')
        self._parent_inode = inode  # Default assumption

        if inode and inode == self._parent._directory_inode:  # standard scenario
            return self._inode_fls[str(inode)]
        if inode == 5 and not self._parent._directory_inode:  # root directory (inode 5) is treated apart. Sometimes is confused with inode 0
            # self.logger.debug('Parent root directory for filename: {}'.format(self.filename()))
            return self._inode_fls[str(inode)]
        if inode and str(inode) in self._inode_fls:
            # Take refParentDirectory of the present entry as its parent inode but mark it as not reliable
            self.logger.debug('Inode from individual entry ({}) does not match general inode from block ({}), and may refer to a deleted directory'.format(
                inode, self._parent._directory_inode))
            self.reliable_inode = False
            return self._inode_fls[str(inode)]

        # Invalid refParentDirectory scenarios:
        if self._parent._directory_inode:
            # Take self._parent._directory_inode as parent inode but mark it as not reliable
            self.logger.debug('Inode from individual entry ({}) invalid. Taking general inode from block ({}) as reference'.format(
                inode, self._parent._directory_inode))
            self.reliable_inode = False
            self._parent_inode = self._parent._directory_inode  # TODO: take this or the inode from refParent not in fls?
            return self._inode_fls[str(self._parent._directory_inode)]
        else:  # Any parent reference is invalid. _parent_inode will be inode in case it matches an older vss reference
            self.reliable_inode = False
            return ['PARENT DIRECTORY NOT FOUND']

    def parent_inode(self):
        return self._parent_inode

    def complete_name(self):
        """ Compare full path from MFTName attribute with join(refParentDirectory, filename).
        Return a complete path if there is a match. Otherwise, mark the entries.
        """
        self._annotation = ''  # Correct match of complete filename
        for name in self.mft_name():
            for p in self.parent_directory():
                if p == '' and self.short_filename:  # Treat files in root directory first. A normal file with a short filename format will be misinterpreted
                    self._annotation = 'short filename'
                    return ''  # SHORT FILENAME FORMAT
                if name == os.path.join(p, self.fn):  # Ideal case. Normal for entries not in slack
                    self._annotation = '' if self.reliable_inode else 'unreliable'
                    self.short_filename = False   # even if the format follows a short name, if it matches with fls, then do not mark as short_filename
                    return name
                if p == 'PARENT DIRECTORY NOT FOUND':
                    # Check if at least MFTReference is coherent with filename
                    if name.split('/')[-1] == self.fn:
                        # self.logger.debug('Parent missing but MFTReference ({}) is coherent with filename ({}). Entry at block offset {}'.format(
                        #     name, self.fn, self.blk_offset()))
                        self._annotation = 'parent missing'
                        return name
                elif name == 'NO FILENAME ASSOCIATED WITH INODE' or name == "$MFT":
                    self._annotation = 'invalid Inode Reference'
                    # self.logger.debug('Wrong MFTReference for entry at block offset {}'.format(self.blk_offset()))
                    return os.path.join(p, self.fn)
                    # TODO: Assuming first name associated with an inode is the correct. Same problem when obtaining parent in entry_as_dict(). Explore other options

        # Let make the comparsion before checking for short Windows filename format
        # just in case a standard filename have a short format by chance
        if self.short_filename:
            self._annotation = 'short filename'
            return ''  # SHORT FILENAME FORMAT
        # self.logger.debug('Complete name not obtained: parent {} | child: {} | filename: {}'.format(self.parent_directory(), self.mft_name(), self.filename()))
        return ''  # NOT OBTAINED

    def is_valid(self):
        """ Check whether entry got the minimum significant info right. """
        # Skip entries with 0 length filename (no significant name could be extracted)
        if self.unpack_integer(*self.attributes['filenameLength']) == 0:
            # self.logger.debug('0 size filenameLength, skipping entry at offset {} of block {}'.format(self.offset(), self.blk_offset()))
            return False

        # TODO: Let some timestamps be invalid ?
        # Skip entries with invalid timestamps
        for timetype in ['creationTime', 'lastModifiedTime', 'MFTRecordChangeTime', 'lastAccessTime']:
            if not _ts_1971 < self.unpack_integer(*self.attributes[timetype]) < _ts_future:
                # self.logger.debug('Timestamp out of range. Skipping entry at offset {} of block {}'.format(self.offset(), self.blk_offset()))
                return False

        # Skip entries with filename not decodable or exceeding buffer
        fn = self.filename()
        if fn == "ERROR DECODING FILENAME":
            self.logger.error('Wrong filename. Skipping entry at offset {} of block {}'.format(self.offset(), self.blk_offset()))
            # self.fn = self.unpack_bytestring(self._filename_offset, 2 * self.unpack_integer(*self.attributes['filenameLength'])).decode("ascii", "replace")
            return False
        elif fn == "FILENAME EXCEDING BUFFER LENGTH":
            # self.logger.debug('Filename exceeding buffer. Skipping entry at offset {} of block {}'.format(self.offset(), self.blk_offset()))
            return False

        return True

    def parse_time(self, timestamp, safe=True):
        """ Return a datetime object from a Windows timestamp
        Arguments:
        - `timestamp`: Windows timestamp value
        - `safe`: if True return the date of the UNIX epoch if there is an exception parsing the date
        """
        if not safe:
            return parse_windows_timestamp(timestamp)
        try:
            if timestamp < 1e17:
                self.logger.info('timestamp too small: {}. Using Epoch timestamp'.format(timestamp))
                return datetime(1970, 1, 1, 0, 0, 0)
            elif timestamp > 1e18:
                self.logger.info('timestamp too big: {}. Using Epoch timestamp'.format(timestamp))
                return datetime(1970, 1, 1, 0, 0, 0)
            else:
                # Standard WIndows timestamp value
                return parse_windows_timestamp(timestamp)
        except ValueError:
            self.logger.warning("{}: Invalid timestamp, using Epoch timestamp.".format(self.absolute_offset(self.offset())))
            return datetime(1970, 1, 1, 0, 0, 0)

    def created_time(self, safe=True):
        return self.parse_time(self.unpack_integer(*self.attributes['creationTime']), safe)

    def modified_time(self, safe=True):
        return self.parse_time(self.unpack_integer(*self.attributes['lastModifiedTime']), safe)

    def changed_time(self, safe=True):
        return self.parse_time(self.unpack_integer(*self.attributes['MFTRecordChangeTime']), safe)

    def accessed_time(self, safe=True):
        return self.parse_time(self.unpack_integer(*self.attributes['lastAccessTime']), safe)

    def physical_size(self):
        return self.unpack_integer(*self.attributes['physicalSizeOfFile'])

    def logical_size(self):
        return self.unpack_integer(*self.attributes['logicalSizeOfFile'])

    def flags(self):
        return self.unpack_integer(*self.attributes['flags'])

    def annotation(self):
        """ Text for marking unreliable complete names of different sort. """
        return self._annotation


class NTATTR_DIRECTORY_INDEX_SLACK_ENTRY(NTATTR_DIRECTORY_INDEX_ENTRY):
    """ Specific methods related to INDX entries in the slack space of blocks. """

    def __init__(self, buf, offset, parent, *args, **kwargs):
        """ Constructor.
        Arguments:
        - `buf`: Byte string containing NTFS INDX file
        - `offset`: The offset into the buffer at which the block starts.
        - `parent`: The parent NTATTR_STANDARD_INDEX_HEADER block, which links to this block.
        """
        super(NTATTR_DIRECTORY_INDEX_SLACK_ENTRY, self).__init__(buf, offset, parent, *args, **kwargs)

    def is_empty(self):
        return (b"\x00" * 52) == self._buf[self.offset():self.offset() + 52].tostring()

    def is_valid(self):
        # TODO: this is_valid should be more permissive than the one in NTATTR_DIRECTORY_INDEX_ENTRY
        return super(NTATTR_DIRECTORY_INDEX_SLACK_ENTRY, self).is_valid()


class NTATTR_SDH_INDEX_ENTRY(NTATTR_STANDARD_INDEX_ENTRY):
    pass


class NTATTR_SII_INDEX_ENTRY(NTATTR_STANDARD_INDEX_ENTRY):
    pass


def entry_as_dict(entry, filename=False):
    """ Return a dictionary with the relevant information for a parsed INDX entry. """
    # Column 'BlkOffsetOrInode': INDX_ROOT records return an inode, INDX_ALLOC records a block offset
    fn = filename if filename else entry.filename()
    slack = entry.offset() if entry.deleted else 0
    # entry_type = 'ROOT' if entry.root_entry else 'ALLOC'
    entry.parent_directory()  # must be executed before getting entry.complete_name()

    return OrderedDict([('Filename', fn),
                       ('Path', entry.complete_name()),
                       ('Modify Date', entry.modified_time()),
                       ('Access Date', entry.accessed_time()),
                       ('Metadata Change Date', entry.changed_time()),
                       ('Birth Date', entry.created_time()),
                       ('Physical Size', entry.physical_size()),
                       ('Logical Size', entry.logical_size()),
                       ('Inode File', entry.entry_inode()),
                       ('Inode Parent', entry.parent_inode()),
                       ('Block Offset', entry.blk_offset()),
                       ('In Slack Space', bool(slack)),
                       ('Annotation', entry.annotation())])
