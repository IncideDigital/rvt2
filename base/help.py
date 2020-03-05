#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

"""
Jobs to assist in the use of the RVT2: list available jobs, show help about a job or module.
"""

import os
import os.path
import ast

import base.job
import base.utils


class Help(base.job.BaseModule):
    """ A module to show help about a job or module whose name is passed as the path of the module.

    Configuration section:
        - **show_vars**: List of variables in the section to show. If "ALL", show all variables. If Empty, do not show context variables.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('show_vars', '')

    def run(self, path=None):
        try:
            self.check_params(path, check_path=True)
        except base.job.RVTError:
            self.logger().error('You must provide a job name, a module name or a class name')
            return list()

        # path is always provided as an absolute path: remove the absolute part
        help_for = base.utils.relative_path(path, os.getcwd())
        help_type = self._classify_path(help_for)
        if help_type == 'plugin':
            return [self._help_for_section(help_for)]
        elif help_type == 'job':
            return [self._help_for_job(help_for, show_vars=self.myconfig('show_vars'))]
        # default: help for module
        return [self._help_for_module(help_for)]

    def _classify_path(self, path):
        " Classify the path as a plugin, job or a module "
        if self.config.get(path, 'plugindir', None) is not None:
            return 'plugin'
        if self.config.get(path, 'description', None):
            return 'job'
        if self.config.get(path, 'module', None):
            return 'module'

    def _jobs_in_section(self, section):
        " Get all jobs in a section "
        jobs = list()
        for s in self.config.sections():
            if self.config.get(s, 'help_section', '') == section:
                jobs.append(s)
        return jobs

    def _help_for_job(self, path, show_vars=False):
        description = self.config.get(path, 'description')
        if not description:
            descfilename = self.config.get(path, 'description.file', '')
            if descfilename and os.path.exists(descfilename):
                with open(descfilename) as descfile:
                    description = ''
                    for line in descfile:
                        description = description + line
        other_vars = []
        if show_vars:
            other_vars = list(self._show_vars(path))
        return dict(
            job=path,
            description=description,
            short=description.split('\n')[0],
            other_vars=other_vars,
            params=ast.literal_eval(self.config.get(path, 'default_params', '{}')),
            params_help=ast.literal_eval(self.config.get(path, 'params_help', '{}')),
        )

    def _help_for_module(self, path):
        try:
            myjob = base.job.load_module(self.config, path)
        except base.job.RVTCritical:
            return dict(module=path)

        description = (myjob.__doc__ if hasattr(myjob, '__doc__') else None)
        return dict(
            module=path,
            description=description
        )

    def _help_for_section(self, path):
        description = self.config.get(path, 'description', '')
        if not description:
            descfilename = self.config.get(path, 'description.file', '')
            if descfilename and os.path.exists(descfilename):
                with open(descfilename) as descfile:
                    description = ''
                    for line in descfile:
                        description = description + line
        jobs_in_section = self._jobs_in_section(path)
        jobs = []
        for job in jobs_in_section:
            jobs.append(self._help_for_job(job, show_vars=self.myconfig('show_vars')))
        return dict(
            section=path,
            description=description,
            jobs=jobs
        )

    def _show_vars(self, help_for):
        """ Show the variables defined in a job/module description """
        if self.config.has_section(help_for):
            var_names = base.job.parse_conf_array(self.myconfig('show_vars'))
            if len(var_names) == 1 and var_names[0] == 'ALL':
                var_names = self.config.options(help_for)
            for option in var_names:
                if self.config.config.has_option(help_for, option):
                    yield dict(var=option, value=self.config.get(help_for, option))


class AvailableJobs(base.job.BaseModule):
    """ A module to list all avaiable jobs in the rvt """
    def _is_job(self, section):
        """ Decide wether the section is a job """
        # a section is a job callable by the user if if thas a description and either cascade, modules or jobs
        return self.config.config.has_option(section, 'description') and (self.config.config.has_option(section, 'cascade') or self.config.config.has_option(section, 'modules') or self.config.config.has_option(section, 'jobs'))

    def run(self, path=None):
        for section in self.config.config.sections():
            if self._is_job(section):
                yield dict(
                    job=section,
                    section=self.config.get(section, 'help_section', default=''),
                    short=self.config.get(section, 'description', default='').split('\n')[0]
                )
