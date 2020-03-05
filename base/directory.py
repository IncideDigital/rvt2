#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 INCIDE Digital Data S.L.
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

""" Modules to parse directories and subdirectories."""

import os
import glob
import re
import shutil
import base.job
import base.config
import base.commands
from tqdm import tqdm


class DirectoryFilter(base.job.BaseModule):
    """
    The module gets a *path* to a directory and sends to *from_module* the path to all files inside this path.
    Optionally, the walker only manages a set of extensions, or excludes files using a regular expression.

    Module description:
        - **path**: the abolute path to a file or directory.
        - **from_module**: mandatory. If path is a file, this module is transparent.
            If *path* is a directory, list all the files to the subdirectories (filters might apply) and call to *from_module*
            for each one of them.
        - **yields**: whatever *from_module* yields each time is called.

    Configuration:
        - **void_extension** (Boolean): If True, files without an extension are always parsed even if a filter is set.
        - **followlinks** (Boolean): If True, follow symbolic links
        - **filter**: List of file categories to parse. If not provided, parse all files. Categories are section names to be read.
        - **progress.disable** (Boolean): If True, disable the progress bar.
        - **progress.cmd** (String): The shell command to run to estimate the number of subdirectories in the path.
        - **exclude_pattern**: If the path of the files matches this pattern, exclude the file.
        - **restartable**: If True, use the local store to save the name of the last directory fully parsed.
          The parsing won't continue until this directory is found.

    Todo:
        Files in the last parsed directory might be parsed twice
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('void_extension', 'True')
        self.set_default_config('followlinks', 'False')
        self.set_default_config('filter', '')
        # if there are filters, fill the self.filter_extensions dictionary
        filters = base.config.parse_conf_array(self.myconfig('filter'))
        # if this set is not None, only files with these extensions are parsed. If None, parse all files
        if filters:
            filter_extensions = list()
            for myfilter in filters:
                for extension in base.config.parse_conf_array(self.config.get(myfilter, 'extension', '')):
                    filter_extensions.append(extension)
            self.filter_extensions = set(filter_extensions)
            self.logger().info('Parsing only: %s', self.filter_extensions)
        else:
            self.filter_extensions = None
        # progress configuration
        self.set_default_config('progress', 'True')
        self.set_default_config('progress.cmd', 'find . -type d | wc -l')
        self.set_default_config('exclude_pattern', '')
        self.set_default_config('restartable', 'False')

        self.exclude_pattern = self.myconfig('exclude_pattern')

    def _should_process_file(self, myfile):
        """ Returns True if a path must be passed to the default from_module.

        Parameters:
            myfile (str): The path (directory and filename) to the file to parse. """
        if self.from_module is None:
            return False
        # broken links do not exist. Links and fifos won't be processed
        if not os.path.exists(myfile) or not os.path.isfile(myfile):
            return False
        # if myfile is in the exclude pattern, return False
        if self.exclude_pattern and re.search(self.exclude_pattern, myfile):
            return False
        # if there is not a filter_extensions, return true
        if self.filter_extensions is None:
            return True
        # check if the extension of myfile is in filter_extensions, or empty
        extension = os.path.splitext(myfile)[1]
        if extension:
            if extension[1:].lower() in self.filter_extensions:
                return True
        elif self.myflag('void_extension'):
            # the no extension case
            return True
        return False

    def run(self, path=None):
        """ Gets a path and calls to from_module for each file in the directory or subdirectories. """
        self.check_params(path, check_from_module=True, check_path=True, check_path_exists=True)

        if os.path.isfile(path):
            # parse a single file
            for info in self.from_module.run(path):
                yield info
        elif os.path.isdir(path):
            # parse a directory
            for info in self._parse_directory(path):
                yield info
        else:
            raise base.job.RVTError('Unknown file type (does it exist?): {}'.format(path))

    def _estimate_subdirectories(self, path):
        """ Estimate the number of subdirectories in the path. Path must be a directory """
        total_subdirectories = float('inf')
        if not self.myflag('progress.disable'):
            # estimating the number of subdirectories may be very long. Do not estimate if progress is disabled
            total_subdirectories = base.commands.estimate_iterations(path, self.myconfig('progress.cmd'))
        # Notice total_interations is the number of subdirectories, not files
        self.logger().info('total_subdirectories=%s', total_subdirectories)
        return total_subdirectories

    def _parse_directory(self, path):
        """ Parse a directory """
        total_iterations = self._estimate_subdirectories(path)
        # if the local store is configured, get the last parsed directory
        lastParsed = None
        if self.myflag('restartable'):
            lastParsed = self.config.store_get('last_dir_parsed', None)
        # walk
        for root, dirs, files in tqdm(os.walk(path, followlinks=self.myflag('followlinks')), total=total_iterations, disable=self.myflag('progress.disable'), desc=self.section):
            for myfile in files:
                filepath = os.path.join(root, myfile)
                # if lastParsed is set, skip until root == lastParsed
                if lastParsed is not None:
                    if root == lastParsed:
                        lastParsed = None
                    else:
                        self.logger().debug('Skipping path="%s" reason="already parsed"', filepath)
                        continue
                # parse the file
                if self._should_process_file(filepath):
                    for info in self.from_module.run(filepath):
                        yield info
                else:
                    self.logger().debug('Skipping path="%s" reason="filtered out"', filepath)
                # save the last parsed root
                if self.myflag('restartable'):
                    self.config.store_set('last_dir_parsed', root)
        # if we arrive to the end, clean last_dir_parsed: next time will be a full parsing again
        if self.myflag('restartable'):
            self.config.store_set('last_dir_parsed', None)


class FileParser(base.job.BaseModule):
    """ Call a job for each file in a path that matches a regex.

    Module description:
        - **path**: run *from_module* on this *path*. If the *path* matches a regex, call also to a configured *jobname*
        - **from_module**: optional. If None, not used.
        - **yields**: whatever *from_module* and *jobname* yield each time they are called.

    Configuration:
        - **parsers**: A list of regex and modules. First, the regular expression matching a filename; second, the jobname to run on this filename.
    """
    def read_config(self):
        base.job.BaseModule.read_config(self)
        self.set_default_config('parsers', '')
        parsers = base.config.parse_conf_array(self.myconfig('parsers'))
        self.regex_list = []
        for regex, parser in zip(parsers[0:len(parsers):2], parsers[1:len(parsers):2]):
            self.regex_list.append((re.compile(regex, flags=re.I), parser))

    def run(self, path=None):
        if self.from_module is not None:
            for fileinfo in self.from_module.run(path):
                yield fileinfo
        for regex, parser in self.regex_list:
            if regex.match(path):
                self.logger().info('Matched path: {}'.format(path))
                for fileinfo in base.job.run_job(self.config.copy(), parser, path=[path]):
                    yield fileinfo


class GlobFilter(base.job.BaseModule):
    """
    The module gets a *glob pattern* as a path, and runs to *from_module* all items matching the pattern.

    See: https://docs.python.org/3.6/library/glob.html

    Module description:
        - **path**: a glob pattern. Run *from_module* on all items matching this pattern.
        - **from_module**: mandatory.
        - **yields**: whatever *from_module* yields each time it is called.

    Configuration:
        - **recursive**: Passes this parameters to ``glob.iglob``: whether the path must run recursively or not.
        - **ftype**: either "file", "directory" or "all".
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('recursive', 'True')
        self.set_default_config('ftype', 'all')

    def run(self, path=None):
        """ Parses objects matching a glob pattern.

        If the glob can match files and directories, you probably want to feed the results to a `DirectoryFilter`.

        Parameters:
            path(str): the glob pattern. It will be recursive. See https://docs.python.org/3.6/library/glob.html

        """
        self.check_params(path, check_from_module=True, check_path=True)
        ftype = self.myconfig('ftype').lower()

        # parse all files matching the glob
        for filepath in glob.iglob(path, recursive=self.myflag('recursive')):
            try:
                if ftype == 'all' or \
                    (ftype == 'file' and os.path.isfile(filepath)) or \
                    (ftype == 'directory' and os.path.isdir(filepath)):
                    for info in self.from_module.run(filepath):
                        yield info
            except Exception as exc:
                if self.myflag('stop_on_error'):
                    raise
                self.logger().warning(exc)


class FileClassifier(base.job.BaseModule):
    """
    Classifies a piece of data according to its content-type, extension or path.

    This class can be used as a module or as a stand-alone object.

    Configuration section:
        - **categories**: list of categories to use. Categories are section names with extension and content type.
        - **check_extension**: When used as module: if True, check path extension; if False, check only content_type to decide a the category.

    Example:
        >>> import base.config
        >>> import base.job
        >>> c = base.config.Config(filenames=['conf/file_categories.cfg'])
        >>> fc = FileClassifier(c, local_config=dict(categories='compressed office'))
        >>> print(fc.classifyByExtension('.docx'))
        office
        >>> print(fc.classifyByContentType('application/x-compress'))
        compressed
        >>> print(fc.classify(dict(extension='.docx')))
        office
        >>> print(fc.classify(dict(extension='.docx', content_type='application/x-compress')))
        compressed
        >>> print(fc.classify(dict(path='filename')))
        None
        >>> print(fc.classify(dict(path='filename.docx')))
        office

    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def read_config(self):
        super().read_config()
        self.set_default_config('categories', '')
        self.set_default_config('check_extension', 'True')

        categories = base.config.parse_conf_array(self.myconfig('categories'))
        # this dictionary maps content_type -> category name
        self._inverted_extensions = dict()
        # this dictionary maps content_type -> category name
        self._inverted_categories = dict()
        for category in categories:
            for content_type in base.config.parse_conf_array(self.config.get(category, 'content_type', '')):
                if content_type not in self._inverted_categories:
                    self._inverted_categories[content_type] = category
            for extension in base.config.parse_conf_array(self.config.get(category, 'extension', '')):
                if extension not in self._inverted_extensions:
                    self._inverted_extensions[extension] = category

    def classifyByExtension(self, extension):
        """ Classifies an extension.

        Parameters:
            :extension: The extension to classify. For example, '.docx'.

        Returns:
            The name of the category, or None
        """
        if not extension:
            return None
        if extension.startswith('.'):
            extension = extension[1:]
        extension = extension.lower()
        return self._inverted_extensions.get(extension, None)

    def classifyByContentType(self, content_type):
        """ Classifies a content type.

        Parameters:
            :extension: The extension to classify. For example, 'application/x-msaccess'.

        Returns:
            The name of the category, or None
        """
        if not content_type:
            return None
        return self._inverted_categories.get(content_type, None)

    def classifyByPath(self, path):
        """ Classifies a path. This method extracts the extension from the path and calls to `classifiyByExtension`. """
        if not path:
            return None
        return self.classifyByExtension(os.path.splitext(path)[-1])

    def classify(self, data):
        """ Classifies a piece of data. Data is a dictionary that must include either `content_type`, `extension` or `path`. """
        # first, try classifying using the content_type
        ct = data.get('content_type', None)
        if ct:
            c = self.classifyByContentType(ct)
            if c:
                return c
        if not self.myflag('check_extension'):
            return None
        # if not classified, classify using the extension
        e = data.get('extension', None)
        if e:
            c = self.classifyByExtension(e)
            if c:
                return c
        # if not classified, classify using the path
        return self.classifyByPath(data.get('path', ''))

    def run(self, path=None):
        """ Classifies all items sent by `from_module` """
        self.check_params(path, check_from_module=True)
        for data in self.from_module.run(path):
            if 'category' not in data:
                data['category'] = self.classify(data)
            yield data


class DirectoryClear(base.job.BaseModule):
    """ Remove the the file or directory specified by 'target'.
        Useful when certain jobs that append results to file are called again, avoiding duplication of output. """

    def run(self, path=None):
        # self.check_params(path, check_from_module=True, check_path=True)
        target_path = self.myconfig('target', None)
        if not target_path:
            raise base.job.RVTError('Target path to remove not selected'.format(target_path))
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
            return []
        elif os.path.isfile(target_path):
            os.remove(target_path)
            return []
        self.logger().info('{} not recognized as file or directory'.format(target_path))
        return []
        # raise base.job.RVTError('{} not recognized as file or directory'.format(target_path))


class MirrorOptions(base.job.BaseModule):
    """ Return the value of the local options """
    def run(self, path=None):
        params = dict(path=base.utils.relative_path(path, self.myconfig('casedir')))
        if self.local_config:
            params.update(self.local_config)
        if hasattr(self, 'section') and hasattr(self, 'config'):
            if self.config.has_section(self.section):
                params.update(self.config.options(self.section))
        return [params]
