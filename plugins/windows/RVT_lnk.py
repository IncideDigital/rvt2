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
import collections
import logging
import tempfile
import datetime
from collections import OrderedDict

import base.job
from plugins.common.RVT_filesystem import FileSystem
from plugins.common.RVT_files import GetFiles
from base.utils import check_folder, check_directory, save_csv

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
        self.attributes = collections.OrderedDict()
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
            self.logger.warning("pylnk can't open file {}. {}".format(self.archive, exc))
            return -1

        try:
            drive = self.drive_type[str(lnk.get_drive_type())]
        except Exception as exc:
            self.logger.debug("pylnk can't determine drive type for file {}. {}".format(self.archive, exc))
            drive = ""
        try:
            machine_id = lnk.get_machine_identifier().rstrip('\x00')
        except Exception as exc:
            self.logger.debug("pylnk can't get machine identifier for file {}. {}".format(self.archive, exc))
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
            self.logger.debug("pylnk can't get network path. {}".format(exc))
            network_path = ""
        try:
            file_size = lnk.get_file_size()
        except Exception as exc:
            self.logger.debug("pylnk can't get file size. {}".format(exc))
            file_size = -1

        try:
            file_objectID = lnk.get_droid_file_identifier()
            b_file_objectID = lnk.get_birth_droid_file_identifier()
            vol_objectID = lnk.get_droid_volume_identifier()
            b_vol_objectID = lnk.get_birth_droid_volume_identifier()
        except Exception as exc:
            self.logger.debug("pylnk can't get file identifier. {}".format(exc))
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
            self.logger.warning("Lnk Error. {}".format(exc))
            return -1
        lnk.close()
        return data


class LnkExtract(base.job.BaseModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dicID = load_appID(myconfig=self.myconfig)
        self.vss = self.myflag('vss')
        self.encoding = self.myconfig('encoding', 'cp1252')

    def read_config(self):
        super().read_config()
        # appid is a file relating applications id with names. https://github.com/EricZimmerman/JumpList/blob/master/JumpList/Resources/AppIDs.txt
        self.set_default_config('appid', os.path.join(self.config.config['windows']['plugindir'], 'appID.txt'))

    def run(self, path=""):
        """ Parses lnk files, jumlists and customdestinations

        """
        self.logger().info("Extraction of lnk files")

        self.Files = GetFiles(self.config, vss=self.myflag("vss"))
        self.filesystem = FileSystem(self.config)
        self.mountdir = self.myconfig('mountdir')

        lnk_path = self.myconfig('{}outdir'.format('v' if self.vss else ''))
        check_folder(lnk_path)

        users = get_user_list(self.mountdir, self.vss)
        artifacts = {'lnk': {'filename': "{}_lnk.csv", 'regex': r"{}/.*\.lnk$", 'function': self.lnk_parser},
                     'autodest': {'filename': "{}_jl.csv", 'regex': r"{}/.*\.automaticDestinations-ms$", 'function': self.automaticDest_parser},
                     'customdest': {'filename': "{}_jlcustom.csv", 'regex': r"{}/.*\.customDestinations-ms$", 'function': self.customDest_parser}}

        for user in users:
            usr = "{}_{}".format(user.split("/")[0], user.split("/")[2])

            for a_name, artifact in artifacts.items():
                out_file = os.path.join(lnk_path, artifact['filename'].format(usr))
                files_list = list(self.Files.search(artifact['regex'].format(user)))
                self.logger().info("Founded {} {} files for user {} at {}".format(len(files_list), a_name, user.split("/")[-1], user.split("/")[0]))
                if len(files_list) > 0:
                    save_csv(artifact['function'](files_list), config=self.config, outfile=out_file, quoting=0, file_exists='OVERWRITE')
                    self.logger().info("{} extraction done for user {} at {}".format(a_name, user.split("/")[-1], user.split("/")[0]))

        self.logger().info("RecentFiles extraction done")
        return []

    def lnk_parser(self, files_list):
        """ Parses all '.lnk' files found for a user.

        Parameters:
            files_list (list): list of automaticDestinations-ms files to parse (relative to casedir)
        """

        headers = ["mtime", "atime", "ctime", "btime", "drive_type", "drive_sn", "machine_id", "path", "network_path", "size", "atributes", "description",
                   "command line arguments", "file_id", "volume_id", "birth_file_id", "birth_volume_id", "f_mtime", "f_atime", "f_ctime", "file"]

        data = self.filesystem.get_macb(files_list, vss=self.vss)

        for file in files_list:
            lnk = Lnk(os.path.join(self.myconfig('casedir'), file), self.encoding, logger=self.logger())

            lnk = lnk.get_lnk_info()

            if lnk == -1:
                self.logger().warning("Problems with file {}".format(file))
                yield OrderedDict(zip(headers, data[file] + ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", file]))
            else:
                yield OrderedDict(zip(headers, data[file] + lnk + [file]))

    def automaticDest_parser(self, files_list):
        """ Parses automaticDest files

        Parameters:
            files_list (list): list of automaticDestinations-ms files to parse
        """

        # TODO: Get the default Windows encoding and avoid trying many
        # TODO: Parse the files without DestList

        # Differences in DestList between versions at:
        # https://cyberforensicator.com/wp-content/uploads/2017/01/1-s2.0-S1742287616300202-main.2-14.pdf
        # Obtain the JumpList version from the header of DestList entry
        for jl in files_list:
            try:
                ole = olefile.OleFileIO(os.path.join(self.myconfig('casedir'), jl))
            except Exception as exc:
                self.logger().warning("Problems creating OleFileIO with file {}\n{}".format(jl, exc))
                continue
            try:
                data = ole.openstream('DestList').read()
                header_version, = struct.unpack('<L', data[0:4])
                version = 'w10' if header_version >= 3 else 'w7'
                self.logger().info("Windows version of Jumplists: {}".format(version))
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
        for jl in files_list:
            self.logger().info("Processing Jump list : {}".format(jl.split('/')[-1]))
            try:
                ole = olefile.OleFileIO(os.path.join(self.myconfig('casedir'), jl))
            except Exception as exc:
                self.logger().warning("Problems creating OleFileIO with file {}\n{}".format(jl, exc))
                continue

            if not ole.exists('DestList'):
                self.logger().warning("File {} does not have a DestList entry and can't be parsed".format(jl))
                ole.close()
                continue
            else:
                if not (len(ole.listdir()) - 1):
                    self.logger().warning("Olefile has detected 0 entries in file {}\nFile will be skipped".format(jl))
                    ole.close()
                    continue

                dest = ole.openstream('DestList')
                data = dest.read()
                if len(data) == 0:
                    self.logger().warning("No DestList data in file {}\nFile will be skipped".format(jl))
                    ole.close()
                    continue
                self.logger().debug("DestList lenght: {}".format(ole.get_size("DestList")))

                try:
                    # Double check number of entries
                    current_entries, pinned_entries = struct.unpack("<LL", data[4:12])
                    self.logger().debug("Current entries: {}".format(current_entries))
                except Exception as exc:
                    self.logger().warning("Problems unpacking header Destlist with file {}\n{}".format(jl, exc))
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
                            self.logger().info("cp1252 decoding failed")
                            self.logger().warning("Problems decoding name with file {}\n{}".format(jl, exc))

                    name = name.replace("\00", "")

                    # Get id_entry of next entry
                    try:
                        id_entry, = struct.unpack(id_entry_ofs[version][0], stream[id_entry_ofs[version][1]:id_entry_ofs[version][2]])
                    except Exception as exc:
                        self.logger().warning("Problems unpacking id_entry with file {}\n{}".format(jl, exc))
                        # self.logger().debug(stream[id_entry_ofs[version][1]:id_entry_ofs[version][2]])
                        break
                    id_entry = format(id_entry, '0x')

                    # Get MSFILETIME
                    try:
                        time0, time1 = struct.unpack("II", stream[100:108])
                    except Exception as exc:
                        self.logger().warning("Problems unpacking MSFILETIME with file {}\n{}".format(jl, exc))
                        break

                    timestamp = getFileTime(time0, time1)

                    # sz: Length of Unicodestring data
                    try:
                        sz, = struct.unpack("h", stream[sz_ofs[version][0]:sz_ofs[version][1]])
                        # self.logger().debug("sz: {}".format(sz))
                    except Exception as exc:
                        self.logger().warning("Problems unpaking unicode string size with file {}\n{}".format(jl, exc))
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
                            self.logger().warning("Problems decoding path with file {}\n{}".format(jl, exc))
                    path = path.replace("\00", "")

                    temp = tempfile.NamedTemporaryFile()
                    # Move to the next entry
                    ofs += sz2 + final_ofs[version]
                    try:
                        aux = ole.openstream(id_entry)
                    except Exception as exc:
                        self.logger().warning("Problems with file {}\n{}".format(jl, exc))
                        self.logger().warning("ole.openstream failed")
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

        self.logger().info("Jumlists parsed")

    def customDest_parser(self, files_list):
        """ Parses customDest files

        Parameters:
            files_list (list): list of customDestinations-ms files to parse
        """
        # regex = re.compile("\x4C\x00\x00\x00\x01\x14\x02\x00")
        split_str = b"\x4C\x00\x00\x00\x01\x14\x02\x00"

        headers = ["Application", "drive_type", "drive_sn", "machine_id", "path", "network_path", "size", "atributes", "description",
                   "command line arguments", "file_id", "volume_id", "birth_file_id", "birth_volume_id", "f_mtime", "f_atime", "f_ctime", "file"]

        for jl in files_list:
            with open(os.path.join(self.myconfig('casedir'), jl), "rb") as f:
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

        self.logger().info("customDestinations parsed")


class LnkExtractAnalysis(base.job.BaseModule):

    def run(self, path=""):
        """ Creates a report based on the output of LnkExtract.

        """
        vss = self.myflag('vss')
        self.logger().info("Generating lnk files report")

        self.mountdir = self.myconfig('mountdir')

        lnk_path = self.config.get('plugins.windows.RVT_lnk.LnkExtract', '{}outdir'.format('v' * vss))
        report_lnk_path = self.myconfig('{}outdir'.format('v' * vss))

        check_directory(lnk_path, error_missing=True)
        check_folder(report_lnk_path)

        outfile = os.path.join(report_lnk_path, 'recentfiles.csv')
        save_csv(self.report_recent(lnk_path), config=self.config, outfile=outfile, quoting=0)

        return []

    def report_recent(self, path):
        """ Create a unique csv combining output from lnk and jumplists """

        file_types = {'lnk': '_lnk.csv', 'jlauto': '_jl.csv', 'jlcustom': '_jlcustom.csv'}
        headers = ["last_open_date", "first_open_date", "application", "path", "network_path", "drive_type", "drive_sn", "machine_id", "size", "file"]
        transform_name = {'lnk': {"last_open_date": "mtime", "first_open_date": "btime"},
                          'jlauto': {"last_open_date": "Open date", "application": "Application"}, 'jlcustom': {"application": "Application"}}

        for file in sorted(os.listdir(path)):
            for typ, ends in file_types.items():
                if file.endswith(ends):
                    t = typ
                    break
            else:
                continue
            partition = file.split('_')[0]
            user = file[len(partition) + 1:-len(file_types[t])]
            for line in base.job.run_job(self.config, 'base.input.CSVReader', path=[os.path.join(path, file)]):
                res = OrderedDict([(h, line.get(transform_name[t].get(h, h), '')) for h in headers])
                res.update({'artifact': t, 'user': user})
                yield res


class LnkExtractFolder(base.job.BaseModule):

    def run(self, path):
        """ Parses lnk files from a folder

        Args:
            path (string): path with lnk files
        """
        if not os.path.isdir(path):
            self.logger().warning("%s folder not exists" % path)
            return

        print("drive_type|drive_sn|machine_id|path|network_path|size|atributes|description|command line arguments|f_mtime|f_atime|f_ctime|file")

        for f in os.listdir(path):
            if not f.lower().endswith(".lnk"):
                continue
            lnk = Lnk(f, path, self.encoding)

            lnk = lnk.get_lnk_info()
            if lnk == -1:
                self.logger().warning("Problems with file {}".format(f))
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


def get_user_list(mount_path, vss=False):

    users = set()
    for p in sorted(os.listdir(mount_path)):
        if (vss and p.startswith("v")) or (not vss and p.startswith("p")):
            user_path = os.path.join(mount_path, p, "Users")
            if not os.path.isdir(user_path):
                user_path = os.path.join(mount_path, p, "Documents and Settings")
            if os.path.isdir(user_path):
                for u in sorted(os.listdir(user_path)):
                    if os.path.isdir(os.path.join(user_path, u)):
                        users.add(os.path.join(user_path, u).split("%s/" % mount_path)[-1])
    return users
