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
import os.path
import re
import base.utils
from plugins.common.RVT_disk import getSourceImage
import base.job
import base.commands
import logging


class Files(base.job.BaseModule):
    """ Generates a list with all the allocated files in a disk, by visiting them. """

    def run(self, path=None):
        """ The path is ignored. """

        if self.myflag('vss'):
            self._generate_allocfiles_vss()
        else:
            self._generate_allocfiles()
        return []

    def _generate_allocfiles(self):
        """ Generates allocfiles

        Todo:
            - If file system is corrupt, alloc_files list may be different from the sleuthkit's output
        """

        mountdir = self.myconfig('mountdir')
        if not base.utils.check_directory(mountdir):
            self.logger().warning('Disk not mounted at {}'.format(mountdir))
            return

        outfile = os.path.join(self.config.get(self.section, 'outdir'), 'alloc_files.txt')
        base.utils.check_file(outfile, delete_exists=True, create_parent=True)
        find = self.myconfig('find', 'find')

        with open(outfile, 'wb') as outf:
            for p in os.listdir(mountdir):
                if p.startswith("p"):
                    relative_p_mountdir = base.utils.relative_path(os.path.join(mountdir, p), self.myconfig('casedir'))
                    base.commands.run_command([find, "-P", relative_p_mountdir + '/'], stdout=outf, logger=self.logger(), from_dir=self.myconfig('casedir'))

    def _generate_allocfiles_vss(self):
        """ Generates allocfiles from mounted vshadows snapshots  """

        disk = getSourceImage(self.myconfig)

        mountdir = self.myconfig('mountdir')
        if not base.utils.check_directory(mountdir):
            self.logger().warning('Disk not mounted')
            return

        outdir = self.config.get(self.section, 'voutdir')
        base.utils.check_directory(outdir, create=True)

        find = self.myconfig('find', 'find')
        for p in disk.partitions:
            for v, dev in p.vss.items():
                if dev != "":
                    with open(os.path.join(outdir, "alloc_{}.txt").format(v), 'wb') as f:
                        relative_v_mountdir = base.utils.relative_path(os.path.join(mountdir, v), self.myconfig('casedir'))
                        base.commands.run_command([find, '-P', relative_v_mountdir + '/'], stdout=f, logger=self.logger(), from_dir=self.myconfig('casedir'))


class GetFiles(object):
    """ This class provides method to interact with the list of all allocated files in the filesystem (alloc_files.txt) """

    def __init__(self, config, vss=False):
        self.logger = logging.getLogger('GetFiles')
        self.config = config
        self.vss = vss

    def get_alloc_txt_files(self):
        """ Return a list of all alloc_files-txt files present in the output directory for the source """
        alloc_txt_files = []
        files_instance = Files(config=self.config)
        if not self.vss:
            auxdir = self.config.get(files_instance.section, 'outdir')
            alloc_txt_files.append(os.path.join(auxdir, "alloc_files.txt"))
            if not os.path.isfile(alloc_txt_files[0]):
                self.logger.info("Alloc files not yet created. Proceeding to generate them")
                files_instance._generate_allocfiles()
        else:
            auxdir = self.config.get(files_instance.section, 'voutdir')
            if not os.path.isdir(auxdir):
                self.logger.info("Alloc files from Volume Snapshots not yet created. Proceeding to generate them.")
                files_instance._generate_allocfiles_vss()
            for file in os.listdir(auxdir):
                if file.startswith("alloc"):
                    alloc_txt_files.append(os.path.join(auxdir, file))

        return alloc_txt_files

    def search(self, regex):
        """ Return a list of allocated files matching 'regex'. """
        rgx = re.compile(regex, re.I)

        alloc_txt_files = self.get_alloc_txt_files()

        matches = []
        for file in alloc_txt_files:
            with open(file, "r") as alloc_f:
                for line in alloc_f:
                    if rgx.search(line):
                        matches.append(line.rstrip())
        return matches

    def files(self):
        """ Yield all of allocated file paths """
        for file in self.get_alloc_txt_files():
            with open(file, "r") as alloc_f:
                for path in alloc_f:
                    yield path


class FilterAllocFiles(base.job.BaseModule):
    """ Reads alloc_files and sends to from_module the filenames that match an expression.

    Configuration:
        - **regex**: the regex expression to match
        - **file_category**: if present, ignore regex and read extensions from this file_category.
        - **vss**: use virtual shadow instead of the current system (only Window images)
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('regex', r'.*')
        self.set_default_config('vss', 'False')
        self.set_default_config('file_category', '')
        file_category = self.myconfig('file_category')
        if file_category:
            # if a file_category is present, use it to filter extensions
            extension_list = base.config.parse_conf_array(self.config.get(file_category, 'extension', ''))
            new_regex = r'\.({})$$'.format('|'.join(extension_list))
            self.local_config['regex'] = new_regex

    def run(self, path=None):
        """ The path is ignored """
        self.check_params(path, check_from_module=True)
        getfiles = GetFiles(self.config, vss=self.myflag("vss"))
        for filename in getfiles.search(self.myconfig('regex')):
            for data in self.from_module.run(filename):
                yield data


class SendAllocFiles(base.job.BaseModule):
    """
    The module sends to *from_module* the path to all files inside alloc_files.
    """
    def run(self, path=None):
        """ The path is ignored """
        self.check_params(path, check_from_module=True)
        paths = GetFiles(self.config, vss=self.myflag("vss")).files()
        for filename in paths:
            filename = os.path.join(self.myconfig('casedir'), filename.rstrip('\n'))
            for data in self.from_module.run(filename):
                yield data


class ExtractPathTerms(base.job.BaseModule):
    """ Set new configuration options with user and partition obtained from a file path """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.regex_user = re.compile("(Documents and Settings|Users|home)/(?P<user>[^/]*)/")
        self.regex_partition = re.compile("/mnt/(?P<partition>[^/]*)/")

    def read_config(self):
        super().read_config()
        self.set_default_config('section', 'extract_terms')

    def run(self, path):
        user = self.get_user_from_path(path)
        partition = self.get_partition_from_path(path)
        self.config.set(self.myconfig('section'), 'user', user)
        self.config.set(self.myconfig('section'), 'partition', partition)
        for data in self.from_module.run(path):
            yield data

    def get_user_from_path(self, path):
        res = self.regex_user.search(path)
        if res is None:
            self.logger().error("Couldn't extract user from path: {}".format(path))
            return ''
        return res.group('user')

    def get_partition_from_path(self, path):
        res = self.regex_partition.search(path)
        if res is None:
            self.logger().error("Couldn't obtain partition from path: {}".format(path))
            return ''
        return res.group('partition')
