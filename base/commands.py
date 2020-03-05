#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2019, INCIDE Digital Data S.L.
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

""" Utility functions and modules to run commands. """

import os
import subprocess
import base.job
import logging
import shlex
from base.utils import relative_path

__maintainer__ = 'Juanvi Vera'


def run_command(cmd, stdout=None, stderr=None, logger=logging, from_dir=None):
    """ Runs an external command using *subprocess*.

    Parameters:
        cmd (str): The command to run, as a string or an array. If *cmd* is a string, run the command as a shell command.
        stdout (file): If provided, set the stdout to this stream
        stderr (file): If provided, set the stderr to this stream
        logger (logging.Logger): If provided, use this logger. If not, use the global *logging* system.
        from_dir (str): Run the external command from this directory. If None, run from current directory.

    Returns:
        If *stdout* is provided, returns ``None``. If no *stdout*, returns the decoded UTF-8 output.
    """

    logger.debug("Running: cmd='%s', from_dir='%s'", cmd, from_dir)
    if from_dir is not None:
        current_dir = os.getcwd()
        os.chdir(from_dir)
    try:
        if stdout is not None:
            # NOTE: you cannot run commands as shell if you pass an array!
            # In that case, only cmd[0] is run
            subprocess.run(cmd, stdout=stdout, stderr=stderr, shell=(type(cmd) == str))
            return None
        else:
            # NOTE: you cannot run commands as shell if you pass an array!
            # In that case, only cmd[0] is run
            return subprocess.check_output(cmd, stderr=stderr, shell=(type(cmd) == str)).decode()
    except Exception as exc:
        raise exc
    finally:
        if from_dir is not None:
            os.chdir(current_dir)


def yield_command(cmd, stderr=None, logger=logging, from_dir=None):
    """ Runs an external command using *subprocess* and yields the output line by line.

    Parameters:
        cmd: The command to run, as a string or an array. If *cmd* is a string, run the command as a shell command.
        logger: If provided, use this logger. If not, use the global *logging* system.
        from_dir: Run the external command from this directory. If ``None``, run from current directory.

    Yields:
        UTF-8 decoded lines from the output of the command.
    """
    logger.debug("Running: cmd='%s', from_dir='%s'", cmd, from_dir)
    if from_dir is not None:
        current_dir = os.getcwd()
        os.chdir(from_dir)
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr, shell=(type(cmd) == str)) as proc:
            for line in proc.stdout:
                yield line.decode()
    except Exception as exc:
        raise exc
    finally:
        if from_dir is not None:
            os.chdir(current_dir)


def estimate_iterations(path, cmd, from_dir=None, logger=logging):
    """ Estimate the number of iterations using an external command.

    Parameters:
        cmd (str): The path to use on the command.
        from_dir (str): If specified, run the external command from this directory.
        cmd (str): The external command to run, as a string or an array. If *cmd* is a string, run the command as a shell command.
            It is a tempalte that will be formated as ``cmd.format(path=path)``.

    Returns:
        The estimated number of iterations as an integer number. ``float('inf')`` if the number of iterations cannot be estimated.
    """
    if not cmd:
        return float('inf')
    try:
        return int(run_command(cmd.format(path=path), logger=logger, from_dir=from_dir).strip())
    except Exception as exc:
        logger.warning('Cannot estimate number of iterations: %s', exc)
        return float('inf')


class Command(base.job.BaseModule):
    """ Run a command before or after the execution of other modules.

    Configuration section:
        :run_before: If True, run the command before the execution of ``from_module``.
        :run_after: If True, run the command after the execution of ``from_module``.
        :from_dir: Run the external command from this directory
        :cmd: The external command to run. It is a python string template with two optional parameters: ``infile`` and ``outfile``
        :infile: The ``infile`` parameter, if needed. Default: empty.
        :outfile: The ``outfile`` parameter, if needed. Default: empty.
        :delete_exists: If *True*, delete the ``outfile``, if exists
        :stdout: If empty, do not overwrite ``stdout``. If provided, save ``stdout`` to this filename
        :append: If *True*, append to the ``output`` file. If *False* and the file exists, remove it
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('cmd', '')
        self.set_default_config('stdout', '')
        self.set_default_config('infile', '')
        self.set_default_config('outfile', '')
        self.set_default_config('append', 'False')
        self.set_default_config('run_before', 'False')
        self.set_default_config('run_after', 'True')
        self.set_default_config('from_dir', self.myconfig('casedir'))
        self.set_default_config('delete_exists', 'True')

    def _run_command(self):
        """ Run a command """
        cmd = self.myconfig('cmd').format(infile=self.myconfig('infile', None), outfile=self.myconfig('outfile', None))

        stdout = None
        try:
            outfilename = self.myconfig('stdout')
            if outfilename:
                base.utils.check_file(outfilename, error_exists=False)
                if self.myflag('delete_exists'):
                    stdout = open(outfilename, 'w')
                else:
                    stdout = open(outfilename, 'a')
                self.logger().debug('outfile="%s"', outfilename)
            run_command(cmd, stdout=stdout, logger=self.logger(), from_dir=self.myconfig('from_dir'))
        finally:
            if stdout is not None:
                stdout.close()

    def run(self, path=None):
        if self.myflag('run_before'):
            self._run_command()

        if self.from_module:
            for data in self.from_module.run(path):
                yield data

        if self.myflag('run_after'):
            self._run_command()


class RegexFilter(base.job.BaseModule):
    """ A module to select lines that match a list of regex expressions.
    Yields a dict with the line, regex, tag and keyword_file as keys.

    Configuration:
        - **keyword_file**: The keyword file to use. One keyword per line.
          Empty lines are ignored. Format: ``ANNOTATION:::REGEX`` or ``REGEX``.
          In the last case, the annotation will be the regex.
        - **keyword_list**: A list of regex expressions to execute.
          Overwrites keyword_file if not empty. Same format as keyword_file.
        - **keyword_dir**: Load keyword files form this directory.
        - **cmd**: Run this external command to perform a search.
        - **from_dir**: Run the external command from this directory. If ``None``, run from current directory.
        - **encoding**: The encoding to decode subprocess binary output
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('keyword_file', '')
        self.set_default_config('keyword_list', '')
        self.set_default_config('keyword_dir', os.path.join(self.myconfig('casedir'), 'searches_files'))
        self.set_default_config('cmd', 'grep -iP "{regex}" "{path}"')
        self.set_default_config('encoding', 'utf-8')
        self.set_default_config('from_dir', '')

    def run(self, path=None):
        """
        Parameters:
            path: Search regex in this file.

        Yields:
            For each line that matches, a dictionary where ``match`` is the matching line, ``regex`` is the
            regex that matched, ``tag`` the tag of the regex and ``keyword_file`` the file where the regex were read from, or *None*.
        """
        self.check_params(path, check_path=True, check_path_exists=True)

        keyword_file = os.path.join(self.myconfig('keyword_dir'), self.myconfig('keyword_file'))
        encoding = self.myconfig('encoding')

        kwlist = self.myconfig('keyword_list')
        if not kwlist:
            if not os.path.exists(keyword_file):
                raise base.job.RVTError('The keyword file does not exists: {}'.format(keyword_file))
            self.logger().debug('Keyword file: %s. Path: %s', keyword_file, path)
            with open(keyword_file) as f:
                kwlist = f.readlines()

        from_dir = self.myconfig('from_dir')
        if from_dir:
            current_dir = os.getcwd()
            os.chdir(from_dir)

        try:
            for keyword_line in kwlist:
                if ':::' in keyword_line:
                    keyword_tag, keyword_regex = keyword_line.strip().split(':::', 1)
                else:
                    keyword_tag = keyword_regex = keyword_line.strip()
                if not keyword_regex:
                    continue
                self.logger().info('Searching for keyword %s on file: %s', keyword_regex, path)

                command = self.myconfig('cmd').format(regex=keyword_regex, path=relative_path(path, from_dir))
                self.logger().debug("Running: cmd='%s', from_dir='%s'", command, from_dir if from_dir else os.getcwd())

                with subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE) as proc:
                    for line in proc.stdout:
                        line = line.strip().decode(encoding)
                        yield dict(match=line, regex=keyword_regex, tag=keyword_tag, keyword_file=keyword_file)
        except Exception as exc:
            raise exc
        finally:
            if from_dir:
                os.chdir(current_dir)
