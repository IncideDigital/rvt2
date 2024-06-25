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
import struct
import time
import pylnk
import olefile
import re
import logging
import tempfile
import datetime
from collections import OrderedDict, defaultdict

import base.job
from plugins.common.RVT_files import GetFiles
from base.utils import check_folder, check_directory, save_csv, relative_path

# TODO: do not use tempfiles


class Lnk(object):
    """ Class to parse information from an lnk file.
    Arguments:
        :infile (str): absolute path to lnk file
        :encoding (str): lnk file encoding
    """
    def __init__(self, infile, encoding='cp1252', logger=''):
        self.archive = infile
        self.encoding = encoding
        self.attributes = OrderedDict()
        self.attributes[0x1] = "DATA_OVERWRITE"
        self.attributes[0x2] = "FILE_ATTRIBUTE_HIDDEN"
        self.attributes[0x4] = "FILE_ATTRIBUTE_SYSTEM"
        self.attributes[0x8] = "Reserved"
        self.attributes[0x10] = "FILE_ATTRIBUTE_DIRECTORY"
        self.attributes[0x20] = "FILE_ATTRIBUTE_ARCHIVE"
        self.attributes[0x40] = "FILE_ATTRIBUTE_DEVICE"
        self.attributes[0x80] = "FILE_ATTRIBUTE_NORMAL"
        self.attributes[0x100] = "FILE_ATTRIBUTE_TEMPORARY"
        self.attributes[0x200] = "FILE_ATTRIBUTE_SPARSE_FILE"
        self.attributes[0x400] = "FILE_ATTRIBUTE_REPARSE_POINT"
        self.attributes[0x800] = "FILE_ATTRIBUTE_COMPRESSED"
        self.attributes[0x1000] = "FILE_ATTRIBUTE_OFFLINE"
        self.attributes[0x2000] = "FILE_ATTRIBUTE_NOT_CONTENT_INDEXED"
        self.attributes[0x4000] = "FILE_ATTRIBUTE_ENCRYPTED"
        self.attributes[0x8000] = "Unknown"
        self.attributes[0x10000] = "FILE_ATTRIBUTE_VIRTUAL"

        self.drive_type = {}
        self.drive_type["0"] = "Unknown"
        self.drive_type["1"] = "No root directory"
        self.drive_type["2"] = "Removable"
        self.drive_type["3"] = "Fixed"
        self.drive_type["4"] = "Remote storage"
        self.drive_type["5"] = "Optical disc"
        self.drive_type["6"] = "RAM drive"

        self.logger = logger if logger else logging.getLogger('Lnk')

    def convertFileReference(self, buf):
        byteArray = ["%02x" % i for i in list(buf[::-1])]

        byteString = ""
        for i in byteArray:
            byteString += i

        return int(byteString, 16)

    def convertAttributes(self, fileAttributes):
        """Returns the file attributes in a human-readable format"""

        attrlist = ""
        for i in self.attributes:
            if i & fileAttributes:
                attrlist += self.attributes[i] + " "

        return attrlist

    def get_lnk_info(self):
        """ gets information about lnk file

        Output fields:
            drive_type; drive_sn; machine_id; path; network_path; size; atributes; description;
            command line arguments; file_id; volume_id; birth_file_id; birth_volume_id; f_mtime; f_atime; f_ctime
        """

        try:
            lnk = pylnk.file()
            lnk.open(self.archive)
            lnk.set_ascii_codepage(self.encoding)
        except Exception as exc:
            self.logger.debug("pylnk can't open filename=%s error=%s", self.archive, exc)
            return -1

        try:
            drive = self.drive_type[str(lnk.get_drive_type())]
        except Exception as exc:
            self.logger.debug("pylnk can't determine drive type for filename=%s error=%s", self.archive, exc)
            drive = ""
        try:
            machine_id = lnk.get_machine_identifier().rstrip('\x00')
        except Exception as exc:
            self.logger.debug("pylnk can't get machine identifier for filename=%s error=%s", self.archive, exc)
            machine_id = ""

        path = lnk.get_local_path()
        # Try to obtain local path from relative path and working directory
        if path == "" or not path:
            rel_path = lnk.get_relative_path()
            wd = lnk.get_working_directory()
            if rel_path:
                if wd and wd.find('%') == -1:  # working directory may use environment variables as '%HOMEDRIVE%%HOMEPATH%'
                    path = os.path.join(wd.replace("\\", "/"), os.path.basename(rel_path.replace("\\", "/")))
                else:
                    path = rel_path.replace("\\", "/")  # Caution: this will return a relative path instead of an absolute one
            else:
                path = ''
        else:
            path = path.replace("\\", "/")

        sn = lnk.get_drive_serial_number()
        if sn:
            sn = hex(sn)
        try:
            network_path = lnk.get_network_path()
        except Exception as exc:
            self.logger.debug("pylnk can't get network path. error={}".format(exc))
            network_path = ""
        try:
            file_size = lnk.get_file_size()
        except Exception as exc:
            self.logger.debug("pylnk can't get file size. error={}".format(exc))
            file_size = -1

        try:
            file_objectID = lnk.get_droid_file_identifier()
            b_file_objectID = lnk.get_birth_droid_file_identifier()
            vol_objectID = lnk.get_droid_volume_identifier()
            b_vol_objectID = lnk.get_birth_droid_volume_identifier()
        except Exception as exc:
            self.logger.debug("pylnk can't get file identifier. error={}".format(exc))
            file_objectID, b_file_objectID, vol_objectID, b_vol_objectID = ['', '', '', '']

        file_times = [lnk.get_file_modification_time(), lnk.get_file_access_time(), lnk.get_file_creation_time()]

        for i, date in enumerate(file_times):
            if date != datetime.datetime(1601, 1, 1, 0, 0):
                file_times[i] = file_times[i].strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                file_times[i] = ""

        try:
            data = [drive, sn, machine_id, path, network_path, file_size, self.convertAttributes(lnk.get_file_attribute_flags()), lnk.get_description(),
                    lnk.get_command_line_arguments(), file_objectID, b_file_objectID, vol_objectID, b_vol_objectID, *file_times]
        except Exception as exc:
            self.logger.debug("Lnk Error. error=%s", exc)
            return -1
        lnk.close()
        return data


class LnkParser(base.job.BaseModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dicID = load_appID(myconfig=self.myconfig)
        self.encoding = self.myconfig('encoding', 'cp1252')

    def read_config(self):
        super().read_config()
        # appid is a file relating applications id with names. https://github.com/EricZimmerman/JumpList/blob/master/JumpList/Resources/AppIDs.txt
        self.set_default_config('appid', os.path.join(self.config.config['windows']['plugindir'], 'appID.txt'))
        self.set_default_config('volume_id', '')
        self.set_default_config('username', '')

    def run(self, path=""):
        self.volume_id = self.myconfig('volume_id')
        self.username = self.myconfig('username')
        artifacts = {'lnk': {'filename': "{}_lnk.csv", 'ending': "lnk", 'function': self.lnk_parser},
                     'autodest': {'filename': "{}_jl.csv", 'ending': ".automaticdestinations-ms", 'function': self.automaticDest_parser},
                     'customdest': {'filename': "{}_jlcustom.csv", 'ending': ".customdestinations-ms", 'function': self.customDest_parser}}
        files = {'lnk': [], 'autodest': [], 'customdest': []}

        if not os.path.isdir(path):
            raise base.job.RVTError('Provided path {} is not a directory'.format(path))

        for artifact, properties in artifacts.items():
            for file in os.listdir(path):
                if file.lower().endswith(properties['ending']):
                    files[artifact].append(os.path.abspath(os.path.join(path, file)))
            out_file = os.path.join(self.myconfig('outdir'), "{}_{}_{}.csv".format(
                self.volume_id, self.username, artifact))
            if len(files[artifact]) > 0:
                self.logger().info("Founded {} {} files".format(len(files[artifact]), artifact))
                save_csv(properties['function'](files[artifact]), config=self.config, outfile=out_file, quoting=0, file_exists='APPEND')
                self.logger().info("{} extraction done".format(artifact))
            else:
                self.logger().debug('No {} files found'.format(artifact))

        return []

    def lnk_parser(self, files_list):
        """ Parses all '.lnk' files found for a user.

        Parameters:
            files_list (list): list of absolute paths to automaticDestinations-ms files to parse
        """

        headers = ["mtime", "atime", "ctime", "btime", "drive_type", "drive_sn", "machine_id", "path", "network_path", "size", "atributes", "description",
                   "command line arguments", "file_id", "volume_id", "birth_file_id", "birth_volume_id", "f_mtime", "f_atime", "f_ctime", "file"]

        relative_files_list = files_list
        if files_list[0].startswith(self.myconfig('casedir')):  # Path inside casedir
            relative_files_list = [relative_path(file, self.myconfig('casedir')) for file in files_list]

        body_file = os.path.join(self.config.get('plugins.common', 'timelinesdir'), '{}_BODY.csv'.format(self.config.config['DEFAULT']['source']))
        data = {}
        if not (os.path.exists(body_file) and os.path.getsize(body_file) > 0):
            data = {file: ['1601-01-01T00:00:00Z'] * 4 for file in relative_files_list}
        else:
            data = get_macb_from_body(body_file, relative_files_list)

        for abs_file, rel_file in zip(files_list, relative_files_list):
            lnk = Lnk(abs_file, self.encoding, logger=self.logger())

            lnk = lnk.get_lnk_info()

            if lnk == -1:
                self.logger().debug("Problems with file {}".format(abs_file))
                yield OrderedDict(zip(headers, data[rel_file] + ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", rel_file]))
            else:
                yield OrderedDict(zip(headers, data[rel_file] + lnk + [rel_file]))

    def automaticDest_parser(self, files_list):
        """ Parses automaticDest files

        Parameters:
            files_list (list): list of absolute paths to automaticDestinations-ms files to parse
        """

        # TODO: Get the default Windows encoding and avoid trying many
        # TODO: Parse the files without DestList

        relative_files_list = files_list
        if files_list[0].startswith(self.myconfig('casedir')):  # Path inside casedir
            relative_files_list = [relative_path(file, self.myconfig('casedir')) for file in files_list]

        # Differences in DestList between versions at:
        # https://cyberforensicator.com/wp-content/uploads/2017/01/1-s2.0-S1742287616300202-main.2-14.pdf
        # Obtain the JumpList version from the header of DestList entry
        for jl in files_list:
            try:
                ole = olefile.OleFileIO(jl)
            except Exception as exc:
                self.logger().debug("Problems creating OleFileIO with file {}\n{}".format(jl, exc))
                continue
            try:
                data = ole.openstream('DestList').read()
                header_version, = struct.unpack('<L', data[0:4])
                version = 'w10' if header_version >= 3 else 'w7'
                self.logger().debug("Windows version of Jumplists: {}".format(version))
                break
            except Exception:
                continue
            finally:
                ole.close()
        if 'version' not in locals():
            self.logger().warning("Can't determine windows version. Assuming w10")
            version = 'w10'  # default

        # Offsets for diferent versions
        entry_ofs = {'w10': 130, 'w7': 114}
        id_entry_ofs = {'w10': ['<L', 88, 92], 'w7': ['<Q', 88, 96]}
        sz_ofs = {'w10': [128, 130], 'w7': [112, 114]}
        final_ofs = {'w10': 4, 'w7': 0}

        headers = ["Open date", "Application", "drive_type", "drive_sn", "machine_id", "path", "network_path", "size", "atributes", "description",
                   "command line arguments", "file_id", "volume_id", "birth_file_id", "birth_volume_id", "f_mtime", "f_atime", "f_ctime", "file"]

        # Main loop
        for abs_jl, jl in zip(files_list, relative_files_list):
            self.logger().debug("Processing Jump list : {}".format(os.path.basename(jl)))
            try:
                ole = olefile.OleFileIO(abs_jl)
            except Exception as exc:
                self.logger().debug("Problems creating OleFileIO with filename={} error={}".format(abs_jl, exc))
                continue

            if not ole.exists('DestList'):
                self.logger().debug("File {} does not have a DestList entry and can't be parsed".format(abs_jl))
                ole.close()
                continue
            else:
                if not (len(ole.listdir()) - 1):

                    self.logger().debug("Olefile has detected 0 entries in filename={}. File will be skipped".format(abs_jl))
                    ole.close()
                    continue

                dest = ole.openstream('DestList')
                data = dest.read()
                if len(data) == 0:
                    self.logger().debug("No DestList data in filename={}. File will be skipped".format(abs_jl))
                    ole.close()
                    continue
                self.logger().debug("DestList lenght: {}".format(ole.get_size("DestList")))

                try:
                    # Double check number of entries
                    current_entries, pinned_entries = struct.unpack("<LL", data[4:12])
                    self.logger().debug("Current entries: {}".format(current_entries))
                except Exception as exc:
                    self.logger().debug("Problems unpacking header Destlist with filename={} error={}".format(abs_jl, exc))
                    # continue

                ofs = 32  # Header offset
                while ofs < len(data):
                    stream = data[ofs:ofs + entry_ofs[version]]
                    name = ""
                    try:
                        name = stream[72:88].decode()
                    except Exception:
                        self.logger().info("utf-8 decoding failed")
                        try:
                            name = stream[72:88].decode("cp1252")
                        except Exception as exc:
                            self.logger().debug("cp1252 decoding failed")
                            self.logger().debug("Problems decoding name with filename={} error={}".format(abs_jl, exc))

                    name = name.replace("\00", "")

                    # Get id_entry of next entry
                    try:
                        id_entry, = struct.unpack(id_entry_ofs[version][0], stream[id_entry_ofs[version][1]:id_entry_ofs[version][2]])
                    except Exception as exc:
                        self.logger().debug("Problems unpacking id_entry with filename={} error={}".format(abs_jl, exc))
                        # self.logger().debug(stream[id_entry_ofs[version][1]:id_entry_ofs[version][2]])
                        break
                    id_entry = format(id_entry, '0x')

                    # Get MSFILETIME
                    try:
                        time0, time1 = struct.unpack("II", stream[100:108])
                    except Exception as exc:
                        self.logger().debug("Problems unpacking MSFILETIME with filename={} error={}".format(abs_jl, exc))
                        break

                    timestamp = getFileTime(time0, time1)

                    # sz: Length of Unicodestring data
                    try:
                        sz, = struct.unpack("h", stream[sz_ofs[version][0]:sz_ofs[version][1]])
                        # self.logger().debug("sz: {}".format(sz))
                    except Exception as exc:
                        self.logger().debug("Problems unpaking unicode string size with filename={} error={}".format(abs_jl, exc))
                        # self.logger().debug(stream[sz_ofs[version][0]:sz_ofs[version][1]])
                        break

                    ofs += entry_ofs[version]
                    sz2 = sz * 2   # Unicode 2 bytes

                    # Get unicode path
                    path = ""
                    try:
                        path = data[ofs:ofs + sz2].decode()
                    except UnicodeDecodeError:
                        try:
                            path = data[ofs:ofs + sz2].decode("iso8859-15")
                        except Exception as exc:
                            self.logger().debug("Problems decoding path with filename=%s error=%s", abs_jl, exc)
                    path = path.replace("\00", "")

                    temp = tempfile.NamedTemporaryFile()
                    # Move to the next entry
                    ofs += sz2 + final_ofs[version]
                    try:
                        aux = ole.openstream(id_entry)
                    except Exception as exc:
                        self.logger().debug("Problems with file filename=%s error=%s", abs_jl, exc)
                        self.logger().debug("ole.openstream failed")
                        temp.close()
                        break
                    datos = aux.read()
                    temp.write(datos)
                    temp.flush()

                    # Extract lnk data
                    lnk = Lnk(temp.name, self.encoding, logger=self.logger())
                    lnk = lnk.get_lnk_info()

                    temp.close()

                    n_hash = os.path.basename(jl).split(".")[0]
                    if lnk == -1:
                        yield OrderedDict(zip(headers, [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)), self.dicID.get(n_hash, n_hash), "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", jl]))
                    else:
                        yield OrderedDict(zip(headers, [time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)), self.dicID.get(n_hash, n_hash)] + lnk + [jl]))

            ole.close()

    def customDest_parser(self, files_list):
        """ Parses customDest files

        Parameters:
            files_list (list): list of customDestinations-ms files to parse
        """
        # regex = re.compile("\x4C\x00\x00\x00\x01\x14\x02\x00")
        split_str = b"\x4C\x00\x00\x00\x01\x14\x02\x00"

        headers = ["Application", "drive_type", "drive_sn", "machine_id", "path", "network_path", "size", "atributes", "description",
                   "command line arguments", "file_id", "volume_id", "birth_file_id", "birth_volume_id", "f_mtime", "f_atime", "f_ctime", "file"]

        relative_files_list = files_list
        if files_list[0].startswith(self.myconfig('casedir')):  # Path inside casedir
            relative_files_list = [relative_path(file, self.myconfig('casedir')) for file in files_list]

        for abs_jl, jl in zip(files_list, relative_files_list):
            with open(abs_jl, "rb") as f:
                data = f.read()

            lnks = data.split(split_str)
            for lnk_b in lnks[1:]:
                f_temp = tempfile.NamedTemporaryFile()
                f_temp.write(b"\x4C\x00\x00\x00\x01\x14\x02\x00" + lnk_b)
                f_temp.flush()
                lnk = Lnk(f_temp.name, self.encoding, logger=self.logger())
                lnk = lnk.get_lnk_info()
                f_temp.close()

                n_hash = os.path.basename(jl).split(".")[0]
                if lnk == -1:
                    yield OrderedDict(zip(headers, [self.dicID.get(n_hash, n_hash), "", "", "", "", "", "", "", "", "", "", "", "", jl]))
                else:
                    yield OrderedDict(zip(headers, [self.dicID.get(n_hash, n_hash)] + lnk + [jl]))


class LnkExtract(base.job.BaseModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dicID = load_appID(myconfig=self.myconfig)
        self.encoding = self.myconfig('encoding', 'cp1252')

    def read_config(self):
        super().read_config()
        # appid is a file relating applications id with names. https://github.com/EricZimmerman/JumpList/blob/master/JumpList/Resources/AppIDs.txt
        self.set_default_config('appid', os.path.join(self.config.config['windows']['plugindir'], 'appID.txt'))

    def run(self, path=""):
        """ Parses lnk files, jumplists and customdestinations """

        # Check if there's another recentfiles job running
        base.job.wait_for_job(self.config, self, job_name='windows.recentfiles')
        base.job.wait_for_job(self.config, self, job_name='windows.recentfiles_default')

        self.logger().info("Starting extraction of lnk files")

        # Since lnk may be anywhere, this job must rely on allocfiles. Accepting a glob pattern will be much slower
        self.Files = GetFiles(self.config)
        self.mountdir = self.myconfig('mountdir')
        self.users = get_user_list(self.mountdir)
        all_recentfiles = self.sort_recent_allocated_files()

        lnk_path = self.myconfig('outdir')
        check_folder(lnk_path)

        base_class = LnkParser(config=self.config)
        artifacts_funcs = {'lnk': base_class.lnk_parser, 'autodest': base_class.automaticDest_parser, 'customdest': base_class.customDest_parser}

        for sort_values, files in all_recentfiles.items():
            partition, user, artifact = sort_values
            self.logger().debug("Founded {} {} files for user {} at {}".format(len(files), artifact, user, partition))
            out_file = os.path.join(lnk_path, "{}_{}_{}.csv".format(partition, user, artifact))
            if len(files) > 0:
                save_csv(artifacts_funcs[artifact](files), config=self.config, outfile=out_file, quoting=0, file_exists='OVERWRITE')
                self.logger().info("{} extraction done for user {} at {}".format(artifact, user, partition))

        self.logger().info("RecentFiles extraction done")
        return []

    def sort_recent_allocated_files(self):
        """ Get and sort all recentfiles allocated in disk by type, partition and user """

        all_recentfiles = defaultdict(list)
        artifacts = {'lnk': {'filename': "{}_lnk.csv", 'regex': r"\.lnk$"},
                     'autodest': {'filename': "{}_jl.csv", 'regex': r"\.automaticDestinations-ms$"},
                     'customdest': {'filename': "{}_jlcustom.csv", 'regex': r"\.customDestinations-ms$"}}

        for artifact_name, artifact in artifacts.items():
            files_list = [os.path.join(self.myconfig('casedir'), f) for f in self.Files.search(artifact['regex'])]
            files_set = set(files_list)

            # files_list items format: '1231456-01-1/mnt/p0X/Users/Default_User/file.lnk'
            for user_path in self.users:
                partition, user = (user_path.split("/")[0], user_path.split("/")[2])
                for file in files_list:
                    if re.search(user_path, file):
                        all_recentfiles[(partition, user, artifact_name)].append(file)
                        files_set.discard(file)

            for file in files_set:  # Remaining recentfiles not under Users
                partition = relative_path(file, self.myconfig('casedir')).split('/')[2]
                all_recentfiles[(partition, 'NO_USER', artifact_name)].append(file)

        return all_recentfiles


class LnkExtractAnalysis(base.job.BaseModule):

    def read_config(self):
        super().read_config()
        self.set_default_config('lnk_dir', self.config.get('plugins.windows.RVT_lnk.LnkExtract', 'outdir'))

    def run(self, path=""):
        """ Creates a report based on the output of LnkExtract """

        self.logger().info("Generating lnk files report")

        self.mountdir = self.myconfig('mountdir')
        lnk_path = self.myconfig('lnk_dir')
        report_lnk_path = self.myconfig('outdir')

        check_directory(lnk_path, error_missing=True)
        check_folder(report_lnk_path)

        outfile = os.path.join(report_lnk_path, 'recentfiles.csv')
        save_csv(self.report_recent(lnk_path), config=self.config, outfile=outfile, quoting=0)

        return []

    def report_recent(self, path):
        """ Create a unique csv combining output from lnk and jumplists """

        file_types = {'lnk': '_lnk.csv', 'jlauto': '_autodest.csv', 'jlcustom': '_customdest.csv'}
        headers = ["last_open_date", "first_open_date", "application", "path", "drive_type", "drive_sn", "machine_id", "size", "file"]
        transform_name = {'lnk': {"last_open_date": "mtime", "first_open_date": "btime"},
                          'jlauto': {"last_open_date": "Open date", "application": "Application"},
                          'jlcustom': {"last_open_date": "f_atime", "application": "Application"}}

        for file in sorted(os.listdir(path)):
            for t, ends in file_types.items():
                if file.endswith(ends):
                    typ = t
                    break
            else:
                continue
            partition = file.split('_')[0]
            user = file[len(partition) + 1:-len(file_types[typ])]
            for line in base.job.run_job(self.config, 'base.input.CSVReader', path=[os.path.join(path, file)]):
                # Merge 'path' and 'network_path' fields. One of them is usually empty and the origin can be obtained anyway with 'machine_id' field
                line['path'] = line.get('path', '') or line.get('network_path', '')
                res = OrderedDict([(h, line.get(transform_name[typ].get(h, h), '')) for h in headers])
                res.update({'artifact': typ, 'user': user, 'partition': partition})
                yield res


class LnkExtractFolder(base.job.BaseModule):

    def run(self, path):
        """ Parses lnk files from a folder

        Args:
            path (string): path with lnk files
        """
        if not os.path.isdir(path):
            self.logger().debug("%s folder not exists", path)
            return

        print("drive_type|drive_sn|machine_id|path|network_path|size|atributes|description|command line arguments|f_mtime|f_atime|f_ctime|file")

        for f in os.listdir(path):
            if not f.lower().endswith(".lnk"):
                continue
            lnk = Lnk(f, path, self.encoding)

            lnk = lnk.get_lnk_info()
            if lnk == -1:
                self.logger().debug("Problems with file {}".format(f))
                print("|".join(["", "", "", "", "", "", "", "", "", "", "", "", f]))
                print("|".join(["", "", "", "", "", ""]))
            else:
                print("|".join(['None' if v is None else str(v) for v in lnk]))


# Auxiliar functions
def load_appID(myconfig=None):
    """ Return a dictionary associating JumpList ID with applications."""
    # list obtained at http://www.forensicswiki.org/wiki/List_of_Jump_List_IDs (2018/02/09)
    dicID = dict()
    jump_file = myconfig('appid')
    with open(jump_file, "r") as file:
        for line in file:
            line = line.split(";")
            dicID[line[0]] = line[1].rstrip()
    return dicID


def getFileTime(data0, data1):
    if (data0 == 0 and data1 == 0):
        return 0
    else:
        data0 -= 0xd53e8000
        data1 -= 0x019db1de
        return int(data1 * 429.4967296 + data0 / 1e7)


def get_user_list(mount_path):
    """ Get a set of paths to 'User' folders in every partition.
        Example of a value: 'p01/Documents and Settings/Default_User'
    """
    users = set()
    for p in sorted(os.listdir(mount_path)):
        if p.startswith("p"):
            user_path = os.path.join(mount_path, p, "Users")
            if not os.path.isdir(user_path):
                user_path = os.path.join(mount_path, p, "Documents and Settings")
            if os.path.isdir(user_path):
                for u in sorted(os.listdir(user_path)):
                    if os.path.isdir(os.path.join(user_path, u)):
                        users.add(os.path.join(user_path, u).split("%s/" % mount_path)[-1])
    return users


def get_macb_from_body(bodyfile, file_list):
    with open(bodyfile, 'r') as f:
        import csv
        # fieldnames = ['md5', 'path', 'inode', 'mode_as_string', 'UID', 'GID', 'size', 'atime', 'mtime', 'ctime', 'crtime']
        r = csv.reader(f, delimiter="|")
        dates = {}
        # reduced_files_list = ['/' + '/'.join(file.split('/')[3:]) for file in file_list]
        files_set = set(file_list)
        for row in r:
            file = row[1]
            if file in files_set:
                dates[file] = [datetime.datetime.fromtimestamp(int(row[8]), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               datetime.datetime.fromtimestamp(int(row[7]), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               datetime.datetime.fromtimestamp(int(row[9]), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               datetime.datetime.fromtimestamp(int(row[10]), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]

        for file in file_list:
            if file not in dates:
                dates[file] = ['1601-01-01T00:00:00Z'] * 4

        return dates
