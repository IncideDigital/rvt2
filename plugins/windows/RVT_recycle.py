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
import datetime
import subprocess
import re
import struct
from collections import OrderedDict
from itertools import chain, product
from io import BytesIO

import base.job
from base.utils import check_directory, check_file, save_csv, parse_microsoft_timestamp
from plugins.common.RVT_disk import getSourceImage
from plugins.common.RVT_filesystem import FileSystem

# TODO: extract inode from $R and associate it to file if not in bin_codes, in present timeline or an older vss, loading inode_path association for older vss


class Recycle(base.job.BaseModule):
    """ Obtain a summary of all files found in the Recycle Bin.

    Requirements:
        - Timeline body file. Run `fs_timeline` or `mft_timeline` before this job
        - (Optional) SOFTWARE hive to get user SIDs. This file must be inside the partition or among the collected artifacts

    Output file fields description:
        * Date: original file deletion date
        * Size: original deleted file size in bytes
        * File: path to file in Recycle Bin
        * OriginalName: original deleted file path
        * Inode: Inode number of the deleted file (it may not be allocated)
        * Status: allocation status of the Recycle Bin file.
        * User: user the recycle bin belongs to. If not found a SID is shown
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.vss = self.myflag('vss')
        self.mountdir = self.myconfig('mountdir')
        if not os.path.isdir(self.mountdir):
            raise base.job.RVTError(f'Mount directory does not exist. Please, mount the image or save some artifacts inside {self.mountdir}')

        # Check if a source image is provided
        self.filesystem = None
        try:
            self.disk = getSourceImage(self.myconfig, vss=self.vss)
            if not self.disk.imagefile:
                self.logger().info(f'No image found for source {self.myconfig("source")}. Proceeding to find artifacts in {self.mountdir}')
            else:
                self.filesystem = FileSystem(self.config, disk=self.disk)
        except Exception as exc:
            raise base.job.RVTError('A source image is needed. {}'.format(exc))

        # Associate a partition name with a partition object or a loop device
        if self.filesystem:
            self.partitions = {''.join(['p', p.partition]): p for p in self.disk.partitions if p.isMountable}
            if not self.partitions:
                raise base.job.RVTError('No partitions found in image {}'.format(self.disk.imagefile))
            self.vss_partitions = {v: dev for p in self.partitions.values() for v, dev in p.vss_mounted.items() if dev}
            self.logger().debug('Partitions: {}'.format(self.partitions))
            self.logger().debug('VSS Partitions: {}'.format(self.vss_partitions))

        # Assert timeline has already been generated
        self.timeline_file = os.path.join(self.myconfig('timelinesdir'), '{}_BODY.csv'.format(self.myconfig('source')))
        try:
            check_file(self.timeline_file, error_missing=True)
        except base.job.RVTError:
            raise base.job.RVTError('Timeline not found at {}. Please, generate the timeline with fs_timeline or mft_timeline before running the present job for parsing recycle bin'.format(self.timeline_file))

    def read_config(self):
        super().read_config()
        self.set_default_config('vss', False)

    def run(self, path=""):
        """ Main function to extract $Recycle.bin files. """

        output_path = self.myconfig('outdir')
        check_directory(output_path, create=True)

        # Get the users associated with each SID for every partition or mounted vss
        self.sid_user = {}
        if self.filesystem:
            for p in self.vss_partitions:
                self.sid_user[p] = self.generate_SID_user(p)
            if not self.vss:
                for p in self.partitions:
                    self.sid_user[p] = self.generate_SID_user(p)
        else:
            # Iterate all pX folders inside mountdir
            for p in [f for f in os.listdir(self.mountdir) if (os.path.isdir(os.path.join(self.mountdir,f)) and f.startswith('p'))]:
                self.sid_user[p] = self.generate_SID_user(p)
                self.logger().debug(f'Obtained the following users in partition {p}: {self.sid_user[p]}')

        # RB_codes relates a a six digit recyclebin code with a path for a file. Are updated for each partition or vss?
        self.RB_codes = {}

        self.logger().debug('Starting to parse RecycleBin')
        if self.vss:
            for partition, dev in self.vss_partitions.items():
                if dev and self.myconfig('source').find(partition) != -1:
                    self.logger().debug('Processing Recycle Bin in partition {}'.format(partition))
                    try:
                        self.parse_RecycleBin(partition)
                    except Exception as exc:
                        if self.myflag('stop_on_error'):
                            raise exc
                        continue
                    output_file = os.path.join(output_path, "{}_recycle_bin.csv".format(partition))
                    self.save_recycle_files(output_file, partition, sorting=True)
        else:
            try:
                self.parse_RecycleBin()
            except Exception as exc:
                if self.myflag('stop_on_error'):
                    raise exc
                return []
            output_file = os.path.join(output_path, "recycle_bin.csv")
            self.save_recycle_files(output_file, sorting=True)
        self.logger().debug("Done parsing Recycle Bin!")

        return []

    def parse_RecycleBin(self, partition=None):
        """ Search all Recycle.Bin files found on the timeline. Both allocated and deleted. """
        # Find the $I files first so a list of codes associated to RecycleBin files can be created
        # Then uses that list to assign names and data to $R files found later.
        self.i_files = {}
        self.r_files = []

        self.logger().debug('Timeline file: {}'.format(self.timeline_file))

        search_command = 'grep -P "{regex}" "{path}"'

        # Parse $I files in RecycleBin:
        self.logger().debug('Searching RecycleBin $I files')
        # Realloc files have metadata pointing to new allocated data that does not match the filename.
        # They cannot be recovered, but the reference to an older name can give some usefull information, so they are included
        regex = [r'\$Recycle\.Bin.*\$I', r'\$RECYCLE\.BIN.*\$I']
        module = base.job.load_module(self.config, 'base.commands.RegexFilter', extra_config=dict(cmd=search_command, keyword_list=regex))

        if not os.path.exists(self.timeline_file) or os.path.getsize(self.timeline_file) == 0:
            self.logger().error('Timeline BODY file not found or empty for partition {}. Run fs_timeline job before executing winRecycle'.format(partition))
            raise base.job.RVTError('Timeline BODY file not found or empty for partition {}. Run fs_timeline job before executing winRecycle'.format(partition))

        for line in module.run(self.timeline_file):
            self._process_I_file(line['match'], partition)

        # Parse $R files in RecycleBin:
        self.logger().debug('Searching RecycleBin $R files')
        regex = [r'\$Recycle\.Bin.*\$R', r'\$RECYCLE\.BIN.*\$R']
        module = base.job.load_module(self.config, 'base.commands.RegexFilter', extra_config=dict(cmd=search_command, keyword_list=regex))

        for line in module.run(self.timeline_file):
            self._process_R_file(line['match'], partition)

    def _process_timeline_record(self, body_record):
        """ Extract and modify relevant information of each timeline_BODY record supplied. """
        # Timeline BODY fields: "file_md5|path|file_inode|file_mode|file_uid|file_gid|file_size|file_access|file_modified|file_changerecord|file_birth"
        _, filename, inode, _, _, _, size, _, _, change_time, _ = body_record.split('|')
        # filename format for regular timeline:  'source/mnt/pXX/path' or 'source/mnt/p0/path' if single partition in image

        if filename.find('$FILE_NAME') > 0:   # Skip $FILE_NAME files
            return

        fn_splitted = filename.split('/')
        # Mark status of the file [allocated, deleted, realloc]. In realloc entries extraction makes no sense
        file_status = 'realloc' if filename[-9:] == '-realloc)' else ('deleted' if filename[-9:] == '(deleted)' else 'allocated')

        partition, SID = fn_splitted[2], fn_splitted[4]
        # Clean filename stripping the '(deleted)' ending
        filename = self.filter_deleted_ending(filename)
        user = self.get_user_from_SID(SID, partition)
        # Check the obtained partition number is coherent with the filesystem
        if self.vss:
            partition, SID = fn_splitted[2], fn_splitted[4]
            if partition not in self.partitions:
                self.logger().warning('Partition number {} obtained from timeline does not match any partition'.format(partition))
                return
        elif self.filesystem:
            try:  # Find partition object associated to selected partition number
                partition = self.partitions[partition]
            except KeyError:
                self.logger().warning('Partition number {} obtained from timeline does not match any partition'.format(partition))
                return

        size = int(size)
        inode = int(inode.split('-')[0])

        return filename, size, inode, partition, user, file_status

    def _process_I_file(self, line, p_name):
        """ Extract metadata from every $I files and store it. """
        try:
            filename, size, inode, partition, user, file_status = self._process_timeline_record(line)
        except TypeError:
            return
        p_name = p_name or partition  # In VSS, p_name is different from partition

        if size == 0 or size > 4096:  # Standard size of $I file is 544 bytes. Avoid empty or corrupted files.
            self.logger().debug('Wrong $I file size ({}). Not parsing {}'.format(size, filename))
            return

        # For allocated files, search the file in mounted disk. In case of deleted, recover from inode
        if file_status == 'allocated':
            record = os.path.join(self.myconfig('casedir'), filename)
        elif file_status == 'deleted':
            record = self.filesystem.icat(inode, p_name, vss=self.vss)
        else:  # realloc. Don't even try to parse
            return

        try:
            i_data = self.get_data(record, filename, status=file_status, user=user)
        except Exception as e:
            self.logger().error(e)
            return
        if i_data:
            rb_code = self.get_bin_name(filename, I_file=True)
            if rb_code not in self.RB_codes:  # It should not be except for vss
                self.RB_codes[rb_code] = i_data['OriginalName']
            self.i_files[rb_code] = i_data

    def _process_R_file(self, line, p_name):
        """ List $R files not parsed as $I. Updates inode in $I files"""
        try:
            filename, size, inode, partition, user, file_status = self._process_timeline_record(line)
        except TypeError:
            return

        bin_code = self.get_bin_name(filename, I_file=False)
        char_pos = filename.find('$R{}'.format(bin_code))  # First match of '#R' will be with '#Recycle', that's why '$Rcode' is looked for.
        # When a directory and its contents are sent to the Recycle Bin, only the dir has an associated $Icode file. Subfiles inside are stored as $Rcode{ending}/somesubfolder/somefile
        # Detect if $R file belongs to a directory sent to Bin
        try:
            sep_char = filename[char_pos + 8:].find('/')
            subfile = True if sep_char != -1 else False
        except IndexError:
            subfile = False

        if file_status == 'realloc':
            inode = 0  # Makes no sense to recover from inode, since it has been reallocated
        if bin_code in self.RB_codes:
            if not subfile:  # Already parsed as $I, only lacks inode
                self.update_inode(inode, bin_code, file_status)
                return
            else:  # Subfiles in the directory
                # Take the first part of the path from the corresponding $I file, append the rest
                original_name = os.path.join(self.i_files[bin_code]['OriginalName'], filename[char_pos + 9 + sep_char:])
                # Containing folder and all subfiles were deleted at the same time, otherwise another recycle code would have been generated
                del_time = self.i_files[bin_code]['Date']
        else:
            # TODO: Search inode in previous vss and get the name from there
            original_name = ''  # Can't determine original name
            del_time = datetime.datetime(1970, 1, 1).strftime("%Y-%m-%d %H:%M:%S")

        r_data = OrderedDict([('Date', del_time), ('Size', size), ('File', filename), ('OriginalName', original_name),
                              ('Inode', inode), ('Status', file_status), ('User', user)])
        if r_data:
            self.r_files.append(r_data)

    @staticmethod
    def get_bin_name(fname, I_file=True):
        """ Extract the 6 characters name assigned by the Recycle Bin

            Example:
            'source/mnt/p01/$Recycle.Bin/S-1-5-21-2334341014-1573730391-3915372428-3835/$I0T3MH9.lnk' --> '0T3MH9'
        """
        if I_file:
            pos = fname.find("$I")
            return fname[pos + 2:pos + 8]
        else:
            start = fname.find("$R")
            pos = fname[start + 2:].find("$R")
            return fname[start + pos + 4: start + pos + 10]

    def update_inode(self, inode, bin_code, file_status):
        ino = self.i_files[bin_code].get('Inode', 0)
        if not ino and inode:  # Update only when new inode is different than 0 and Inode key was 0
            self.i_files[bin_code]['Inode'] = inode

    def get_data(self, file, filepath, status='allocated', inode=0, user=''):
        """ Return a new record parsing file's metadata.
        Args:
            file (str or bytes): $I url or byte-string containing the data
            filepath (str): relative path to $I file from mount root
            status (str): allocated, deleted, realloc
            inode (int): inode of the $R file
        Returns:
            dict: keys = [Date, Size, File, OriginalName, Inode, Status, User]
        """
        self.logger().debug(f'Parsing {filepath}')
        try:
            with BytesIO(file) as f:  # file is a byte-string
                data = self.get_metadata(f, filepath)
        except TypeError:
            with open(file, 'rb') as f:  # file is an url str of a path location
                data = self.get_metadata(f, filepath)
        if data:
            data.update([('Inode', inode), ('Status', status), ('User', user)])
        return data

    def get_metadata(self, f, filepath):
        """ Parse $I file and obtain metadata
        Args:
            f (str): $I file_object
            filepath (str): relative path to $I file from mount root
        Returns:
            dict: keys = [Date, Size, File, OriginalName]
        """
        # For information about $I files structure:
        # https://df-stream.com/2016/04/fun-with-recycle-bin-i-files-windows-10/
        try:
            data = f.read()
            header = struct.unpack_from('B', data)[0]
        except Exception:
            self.logger().warning('Unrecognized $I header for file: {}'.format(filepath))
            return {}
        try:
            if header == 2:  # windows 10
                name_length = struct.unpack_from('<i', data, 24)[0]
                file_name = data[28:28 + name_length * 2].decode('utf-16').rstrip('\x00').replace('\\', '/')
            elif header == 1:
                file_name = data[24:24 + 520].decode('utf-16').rstrip('\x00').replace('\\', '/')
            else:
                self.logger().warning('Unrecognized $I header for file: {}'.format(filepath))
                return {}
        except Exception:
            self.logger().warning('Problems getting filename for file: {}'.format(filepath))
            file_name = ''
        try:
            size = struct.unpack_from('<q', data, 8)[0]
        except Exception:
            self.logger().warning('Problems getting file size for file: {}'.format(filepath))
            size = 0
        try:
            deleted_time = parse_microsoft_timestamp(struct.unpack_from('<q', data, 16)[0]).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as exc:
            self.logger().warning('Problems getting deleted timestamp for file: {}. Err: {}'.format(filepath, exc))
            deleted_time = datetime.datetime(1970, 1, 1).strftime("%Y-%m-%d %H:%M:%S")

        try:
            return OrderedDict([('Date', deleted_time),
                                ('Size', size),
                                ('File', filepath),
                                ('OriginalName', file_name)])
        except Exception:
            self.logger().debug('Wrong $I format or missing field: {}'.format(filepath))
            return {}

    def save_recycle_files(self, output_file, partition=None, sorting=True):
        """ Sort recycle bin files by date and save to 'output_file' csv. """
        if not (len(self.i_files) or len(self.r_files)):
            self.logger().debug('No RecycleBin files found{}.'.format(' in partition {}'.format(partition if partition else '')))
            return
        if sorting:
            self.RB_files = list(self.i_files.values()) + self.r_files
            self.RB_files = sorted(self.RB_files, key=lambda it: it['Date'])
        else:
            self.RB_files = chain(self.i_files.values(), self.r_files)

        check_file(output_file, delete_exists=True)
        save_csv(self.RB_files, outfile=output_file, quoting=0, file_exists='OVERWRITE')

    def generate_SID_user(self, partition):
        rip = self.config.get('plugins.common', 'rip', '/opt/regripper/rip.pl')

        try:
            software = self.locate_hives(partition)['software']
        except (KeyError, TypeError):
            self.logger().debug('No Software registry file found for partition {}'.format(partition))
            return {}

        output_profilelist = subprocess.check_output([rip, "-r", software, "-p", 'profilelist']).decode()
        # output_samparse = subprocess.check_output([rip, "-r", sam, "-p", 'samparse']).decode()

        us = {}
        is_path = False
        for i in output_profilelist.split('\n'):
            if i.startswith("Path"):
                mo = re.search("Users.(.*)", i)
                if mo is not None:
                    user = mo.group(1)
                    is_path = True
                else:
                    mo = re.search("Documents and Settings.([^\n]*)", i)
                    if mo is not None:
                        user = mo.group(1)
                        is_path = True
            else:
                if i.startswith("SID") and is_path:
                    sid = i.split(':')[1][1:]
                    is_path = False
                    us[sid] = user

        return us

    def get_user_from_SID(self, SID, partition):
        """ Return the user associated with a SID.
        Search in other partitions and vss for a user with same SID if not found in current partition. """
        try:
            return self.sid_user[partition][SID]
        except (TypeError, KeyError):
            self.logger().debug('SID {} does not have an associated user in partition {}'.format(SID, partition))
        # Warning: it's assuming only one partition has vss
        for p in self.vss_partitions:
            if p != partition:
                try:
                    return self.sid_user[p][SID]
                except(TypeError, KeyError):
                    continue
        return SID

    def locate_hives(self, partition):
        """ Return the path to the main hives, as a dictionary. """
        # Consider partition may be in the vss format vXXpYY_123456_123456
        if partition.startswith('v'):
            partition = partition[partition.find('p'):partition.find('_')]

        part_dir = os.path.join(self.mountdir, partition)
        folder_combinations = product(*((c.capitalize(), c.upper(), c) for c in ['windows', 'system32', 'config']))
        for dir in (os.path.join(*i) for i in folder_combinations):
            config_dir = os.path.join(part_dir, dir)
            if os.path.exists(config_dir):
                break
        else:   # Config folder not found
            self.logger().debug('No config directory found for partition {}'.format(partition))
            return

        hives = {}
        for j in os.listdir(config_dir):
            if j.lower() in ["software", "sam", "system", "security"]:
                hives[j.lower()] = os.path.join(config_dir, j)
                continue

        return hives

    def filter_deleted_ending(self, path):
        """ Strips ' (deleted)' or ' (deleted-realloc)' from the end of a path as given by 'fls'. """
        if path[-1] != ')':
            return path
        if path.endswith('(deleted)'):
            return path[:-10]
        if path.endswith('-realloc)'):
            return path[:-18]
        return path
