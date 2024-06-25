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
        """ Classify the path as a plugin, job or a module.
        
        To classify a path, this function checks the configuration section:
        
        - If it has a 'plugindir' option, returns 'plugin'
        - It it has a  'description', returns 'job'
        - else, returns 'module' and hope for the best """
        if self.config.get(path, 'plugindir', None) is not None:
            return 'plugin'
        if self.config.get(path, 'description', None):
            return 'job'
        return 'module'

    def _jobs_in_section(self, section):
        " Get all jobs in a section "
        jobs = list()
        for s in self.config.sections():
            if self.config.get(s, 'help_section', '') == section:
                jobs.append(s)
        return jobs

    def _get_jobs_in_job(self, section):
        "Get the job name for all subjobs in a job"
        if 'jobs' not in self.config.options(section):
            return []
        jobs_chain = self.config.get(section, 'jobs', None)
        subjobs = list()
        for subjob in [j for j in jobs_chain.split('\n') if j]:
            subjob_name = subjob.strip().split()[0]
            subjobs.append(subjob_name)
        return subjobs

    def _help_for_job(self, path, show_vars=False):
        description = self.config.get(path, 'description')
        if not description:
            descfilename = self.config.get(path, 'description.file', '')
            if descfilename and os.path.exists(descfilename):
                with open(descfilename) as descfile:
                    description = ''
                    for line in descfile:
                        description = description + line
        if description is None:
            self.logger().warn('job="%s" has no description', path)
            description = ''
        jobs = []
        for job in self._get_jobs_in_job(path):
            jobs.append(self._help_for_job(job, show_vars=self.myconfig('show_vars')))
        other_vars = []
        if show_vars:
            other_vars = list(self._show_vars(path))
        try:
            return dict(
                job=path,
                description=description,
                short=description.split('\n')[0],
                jobs = jobs,
                other_vars=other_vars,
                params=ast.literal_eval(self.config.get(path, 'default_params', '{}')),
                params_help=ast.literal_eval(self.config.get(path, 'params_help', '{}')),
            )
        except SyntaxError:
            raise SyntaxError(f'Malformatted option param for path="{path}". Maybe an error in default_params or params_help?')

    def _help_for_module(self, path):
        """ path is a module name """
        try:
            mymodule = base.job.load_module(self.config, path)
        except base.job.RVTCritical:
            return dict(module=path)

        description = (mymodule.__doc__ if hasattr(mymodule, '__doc__') else None)
        return dict(
            module=path,
            description=description
        )

    def _help_for_section(self, section):
        """ Get the help message for a section.

        Description is got:

        - from option 'section.description'
        - Reading markdown from file in option 'section.description.file'
        - loading 'section' and getting its '__doc__'
        - empty
        """
        description = self.config.get(section, 'description', '')
        if not description:
            descfilename = self.config.get(section, 'description.file', '')
            if descfilename and os.path.exists(descfilename):
                with open(descfilename) as descfile:
                    description = ''
                    for line in descfile:
                        description = description + line
        if not description:
            try:
                mymodule = __import__(section, globals(), locals())
                description = (mymodule.__doc__ if hasattr(mymodule, '__doc__') else None)
            except Exception:
                description = ''
        jobs_in_section = self._jobs_in_section(section)
        jobs = []
        for job in jobs_in_section:
            jobs.append(self._help_for_job(job, show_vars=self.myconfig('show_vars')))
        return dict(
            section=section,
            description=description,
            jobs=jobs
        )

    def _show_vars(self, help_for):
        """ Show the variables defined in a job/module description """
        if self.config.has_section(help_for):
            var_names = self.myarray('show_vars')
            if len(var_names) == 1 and var_names[0] == 'ALL':
                var_names = self.config.options(help_for)
            for option in var_names:
                if self.config.config.has_option(help_for, option):
                    yield dict(var=option, value=self.config.get(help_for, option))


class AvailableJobs(base.job.BaseModule):
    """ A module to list all available jobs in the rvt.

    Configuration section:
        - **only_section**: show jobs only in a specific section.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('only_section', '')

    def _selected_job(self, section):
        """ Decide wether a section in the configuration meet requirements to be displayed in the main list.
            - Has a description
            - Is assigned to a help_section
            - Has either cascade, modules or jobs
        """
        return self.config.config.has_option(section, 'description') and \
            self.config.config.has_option(section, 'help_section') and \
            (self.config.config.has_option(section, 'cascade') or self.config.config.has_option(section, 'modules') or self.config.config.has_option(section, 'jobs'))

    def run(self, path=None):
        only_section = self.myconfig('only_section', '')
        for section in self.config.config.sections():
            if self._selected_job(section):
                job_section = self.config.get(section, 'help_section', default='')
                if only_section and job_section != only_section:
                    continue
                yield dict(
                    job=section,
                    section=job_section,
                    short=self.config.get(section, 'description', default='').split('\n')[0]
                )
