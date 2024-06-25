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


""" The entry point to the system. """

__version__ = '20231129'

import os
import sys
import argparse
import logging
import json
import pprint
import re

import base.config
import base.job
import base.utils


def load_configpaths(config, configpaths):
    """ Load configuration from an array of paths.

    Attrs:
        :configpaths: Array of paths to load configuration from. Unexisting paths are ignored
    """
    if not configpaths:
        return
    for config_file in configpaths:
        if os.path.exists(config_file):
            config.read(config_file)


def load_plugin(pluginpath, config):
    """ Load a plugin from a path.

    Load all cfg files inside the path.
    if configuration section 'pluginame.pythonpath exists, load the python path in this section
    If funcion plugin.load_plugin() exists, run it.

    Attrs:
        :pluginpath: The absolute path to the plugin
        :config: The configuration object
    """
    name = os.path.basename(pluginpath)
    logging.debug('Loading plugin: %s from %s', name, pluginpath)
    # Add the parent path to the python path
    sys.path.insert(0, os.path.dirname(pluginpath))
    # Add any configuration file inside this directory
    config.read(pluginpath, pattern='*.cfg')
    # Set the special configuration: 'plugin:plugindir'
    config.set(name, 'plugindir', pluginpath)
    # Add any additional path defined in 'plugin:pythonpath'
    pythonpaths = base.config.parse_conf_array(config.get(name, 'pythonpath', ''))
    for pythonpath in pythonpaths:
        if pythonpath not in sys.path:
            logging.debug('Adding pythonpath: %s', pythonpath)
            sys.path.insert(0, pythonpath)
    # Run the function in 'plugin.load_plugin', if any
    try:
        mod = __import__(name, globals(), locals())
        if hasattr(mod, 'load_plugin'):
            mod.load_plugin(config)
    except Exception as exc:
        logging.warning('Exception loading module: %s', exc)


class StoreDict(argparse.Action):
    """ An argparse.Action to parse additional parameters as a dictionary.

    Parameters have the syntax `name=value`. Only the first _=_ is relevant. If the value part is not provided, assign the string 'True' to the name.

    Example:::

        >>> import argparse
        >>> parser = argparse.ArgumentParser(prog='PROG')
        >>> _= parser.add_argument('-p', '--params', action=StoreDict, nargs='*', default={})
        >>> parser.parse_args(['-p', 'one=one_value', '-p', 'two', '--params', 'three=three_value1=three_value2', 'four=four_value'])
        Namespace(params={'one': 'one_value', 'two': 'True', 'three': 'three_value1=three_value2', 'four': 'four_value'})

    """
    def __call__(self, parser, namespace, values, option_string=None):
        # get the current dictionary in the namespace, if any
        kv = getattr(namespace, self.dest, {})
        # if current value is not a list of params, convert to a list
        if not isinstance(values, (list,)):
            values = (values,)
        # parse params
        for value in values:
            if '=' in value:
                n, v = value.split('=', 1)
                kv[n] = v
            else:
                # if = is not in the param, set the name to True
                kv[value] = 'True'
        # update the current dictionary
        setattr(namespace, self.dest, kv)


def job_needs_morgue(job):
    """ Check if the specified job requires a 'morgue' """
    return False if job is None else (job not in ['help', 'show_jobs'])


def job_needs_source(job):
    """ Check if the specified job requires a 'source' """
    return False if job is None else (job not in ['help', 'show_jobs', 'status', 'show_cases', 'show_images'])


def set_global_vars(config, args):
    """ Update initial variables in globals. Induce client and casename if only source is provided

    Params:
        config: The configuration object
        args: The argparse object to be updated
    """
    # Load main variables from globals, parameters or configuration
    updated_vars = {}
    for ar, name in zip([args.morgue, args.client, args.casename, args.source], ['morgue', 'client', 'casename', 'source']):
        if name in args.globals:
            updated_vars[name] = args.globals[name]
        elif name not in args.globals and not ar:
            updated_vars[name] = config.get('DEFAULT', name)
        else:
            updated_vars[name] = ar
    # Check morgue folder exists
    if not os.path.exists(updated_vars['morgue']) and job_needs_morgue(args.job):
        logging.error(f"Morgue folder ({updated_vars['morgue']}) not found in the system. Please, provide a valid 'morgue' folder")
        sys.exit(1)
    # Check 'source' is set to a non default value
    if updated_vars['source'] == 'mysource' and job_needs_source(args.job):
        logging.error(f"Please, provide non default value for 'source'")
        sys.exit(1)

    # Try to induce 'client' and 'casename' if only 'source' is provided
    # Only 'morgue' value will be taken from configuration if not provided as argument. 'client' and 'casename' should be provided
    # If 'client' and 'casename' are set on a configuration file and are different from 'myclient' and 'mycase', the execution will not stop
    # Assumptions:
    #   - source is expressed in a format like the following example: "123456-DR-AB-01-123"
    #   - full path to source is such as: "MORGUEDIR/123456-name/DR-AB-01/123456-DR-AB-01-123" where 123456-name is the 'client' and DR-AB-01 the 'casename'
    pattern = r'^(?P<caseid>\d{6})-(?P<casename>DR-[^-]+-[^_-]+)'
    arguments = re.search(pattern, updated_vars['source'])
    if not arguments and job_needs_source(args.job):
        logging.warning(f"Source ({updated_vars['source']}) does not follow the expected format. Getting 'client' and 'casename' from parameters or configuration")
    elif arguments:
        caseid = arguments.group('caseid')
        casename = arguments.group('casename')
        if not updated_vars["client"].startswith(caseid) and job_needs_source(args.job):
            logging.warning(f"'client' defined ({updated_vars['client']}) does not match with the suposed client extracted from 'source' ({updated_vars['source']})")
        if not casename.startswith(updated_vars["casename"]) and job_needs_source(args.job):
            logging.warning(f"'casename' defined ({updated_vars['casename']}) does not match with the suposed casename extracted from 'source' ({updated_vars['source']})")
    if ((updated_vars['client'] == 'myclient') or (updated_vars['casename'] == 'mycase')) and updated_vars['source']:
        if not arguments and job_needs_source(args.job):
            logging.error(f"Please, provide non default values for both 'client' and 'casename'")
            sys.exit(1)
        if arguments and os.path.exists(updated_vars['morgue']):
            for dirname in os.listdir(updated_vars['morgue']):
                if dirname.startswith(caseid) and os.path.isdir(os.path.join(updated_vars['morgue'], dirname)):
                    # Update 'client' to new deduced value only if it has not been changed from default value
                    if updated_vars['client'] == 'myclient':
                        updated_vars['client'] = dirname
                    for casedirname in os.listdir(os.path.join(updated_vars['morgue'], dirname)):
                        if casedirname == casename:
                            # Update 'casename' to new deduced value only if it has not been changed from default value
                            if updated_vars['casename'] == 'mycase':
                                updated_vars['casename'] = casedirname
                            break
                        elif casedirname != casename and job_needs_source(args.job):
                            logging.warning(f"Casename folder ({casename}) extracted from source ({updated_vars['source']}) not found in {os.path.join(args.morgue, dirname)}.")
                            logging.error(f"Please, provide non default values for both 'client' and 'casename'")
                            if updated_vars['casename'] == 'mycase':
                                sys.exit(1)
                    break
            else:
                if job_needs_source(args.job):
                    logging.warning(f"Client name not found in ({updated_vars['morgue']}) given the source ({updated_vars['source']}). Please, provide 'client' and 'casename'")
                    if updated_vars['client'] == 'myclient':
                        sys.exit(1)

    # Update global variables again
    for name in ['morgue', 'client', 'casename', 'source']:
        # WARNING: there is no validation that the new 'client' and 'casename' match the previous. Keep the previous just in case source has an extrange format
        if ar is not None and name not in args.globals:
            args.globals[name] = updated_vars[name]


def set_global_config(config, _globals, ignore_errors=False):
    """ Set global variables in the configuration object.

    Params:
        config: The configuration object
        _globals: a dictionary with global variables, in the format {"SECTION:PARAM": "VALUE"}. If no SECTION
            is provided, use "DEFAULT"
        ignore_errors: If True, ignore missing sections (do nothing)
    """
    for varname in _globals:
        sectionname = base.config.DEFAULTSECT
        newvarname = varname
        newvalue = _globals[varname]
        if ':' in varname:
            sectionname, newvarname = varname.split(':', 1)
        try:
            config.config[sectionname][newvarname] = newvalue
        except KeyError:
            if not ignore_errors:
                raise


def configure_logging(config, verbose=False, jobname=None):
    """ Configure the logging subsystem.

    Attrs:
        verbose (boolean): If true, set the logging to verbose regardless what the configuration says.
        jobname (String): The name of the job to be run. If None, use basic configuration. If the job defines in its section `register: False`, use basic configuration.
    """
    if verbose:
        config.config['logging']['console.level'] = 'DEBUG'
    if jobname is None or config.get(jobname, 'register', 'True').upper() == 'FALSE':
        base.config.configure_logging(config, basic=True)
    else:
        try:
            base.config.configure_logging(config)
        except Exception as exc:
            # after an exception, configure the basic logging system
            base.config.configure_logging(config, basic=True)
            logging.error('Couldn\'t configure the logging system: %s', exc)


def main(params=sys.argv[1:]):
    """ The entry point of the system. Run from the command line and get help using --help.

    Read configuration files and run jobs.

    Attrs:
        :params: The parameters to configure the system
    """

    jobid = str(base.utils.generate_id())
    INITIAL_CONF = {
        'rvt2:version': __version__,
        'rvthome': os.path.dirname(os.path.abspath(__file__)),
        'userhome': os.environ.get('HOME'),
        'cwd': os.getcwd(),
        'rvt2:jobid': jobid
    }

    aparser = argparse.ArgumentParser(description='The Revealer Toolkit for forensic analysis')
    aparser.add_argument('-v', '--verbose', help='outputs debug messages to the standard output', action='store_true', default=False)
    aparser.add_argument('-V', '--version', help='outputs version and current configuration and exit', action='store_true', default=False)
    aparser.add_argument('-c', '--config', help='additional configuration files. Can be provided multiple times and configuration is appended', action='append')
    aparser.add_argument('--globals', help="additional configuration, as SECTION:PARAM=VALUE. You can provide several parameters, end the list with a --. If a section name is not provided, use DEFAULT", action=StoreDict, nargs='*', default=INITIAL_CONF)
    aparser.add_argument('-m', '--morgue', help='value of the morgue variable in the DEFAULT section of the configuration. Shortcut to --globals morgue=MORGUE', default=None)
    aparser.add_argument('--client', help='value of the client variable in the DEFAULT section of the configuration. Shortcut to --globals client=CLIENT', default=None)
    aparser.add_argument('--casename', help='value of the casename variable in the DEFAULT section of the configuration. Shortcut to --globals casename=CASENAME', default=None)
    aparser.add_argument('-s', '--source', help='value of the source variable in the DEFAULT section of the configuration. Shortcut to --globals source=SOURCE', default=None)
    aparser.add_argument('-j', '--job', help='section name in the configuration file for the main job.', default=None)
    aparser.add_argument('--params', help="additional parameters to the job, as PARAM=VALUE. You can provide seveal parameters, end the list with a --", action=StoreDict, nargs='*', default={})
    aparser.add_argument('-p', '--print', help='print the results of the job as JSON', action='store_true', default=False)
    aparser.add_argument('paths', type=str, nargs='*', help='Filename or directories to parse')
    args = aparser.parse_args(params)

    # Sanitize morgue variables
    if args.morgue:
        args.morgue = args.morgue.rstrip('/')
    if args.globals.get('morgue',''):
        args.globals['morgue'] = args.globals['morgue'].rstrip('/')

    # Update initial variables in globals
    # Notice "--globals morgue=SOMETHING" has preference over "--morgue SOMETHING"
    for ar, name in zip([args.morgue, args.client, args.casename, args.source], ['morgue', 'client', 'casename', 'source']):
        if ar is not None and name not in args.globals:
            args.globals[name] = ar

    if args.version:
        pprint.pp(args.globals)
        sys.exit(0)

    # First configuration step, in case the initilization of the system needs these parameters. It will be read again later
    # Read configuration from one or more -c options
    config = base.config.default_config
    load_configpaths(config, args.config)
    # Configure global variables.
    # Since plugins are not loaded yet, ignore errors of missing sections
    set_global_config(config, args.globals, ignore_errors=True)

    # Configure the logging subsystem using a generic configuration
    configure_logging(config, args.verbose, None)
    # NOW we can log the configuration files, since the logging system is already up
    logging.debug('Configuration files: %s', args.config)

    # Induce 'client' and 'casename' if only 'source' is set
    set_global_vars(config, args)
    set_global_config(config, args.globals, ignore_errors=True)

    # Load additional pythonpath
    for pythonpath in base.config.parse_conf_array(config.get('rvt2', 'pythonpath', '')):
        logging.debug('Loading pythonpath: %s', pythonpath)
        sys.path.insert(0, pythonpath)
    logging.debug('Pythonpath: %s', sys.path)
    # Load additional plugins directories
    for pluginspath in base.config.parse_conf_array(config.get('rvt2', 'plugins', '')):
        load_plugin(pluginspath, config)

    # Read again configuration from one or more -c options. They MUST overwrite the configuration of the plugins
    load_configpaths(config, args.config)
    # Configure global variables. They MUST overwrite the configuration
    set_global_config(config, args.globals)

    # configure the job: if there is a Main section, use it. Else, get the default job from configuration rvt2.default_job
    if args.job is None:
        if config.has_section('Main'):
            args.job = 'Main'
        else:
            args.job = config.get('rvt2', 'default_job')

    # reload the logging system, using the configuration specific for the job
    configure_logging(config, args.verbose, args.job)

    # run job
    try:
        for results in base.job.run_job(config, args.job, args.paths, extra_config=args.params, nested_logs=2, nested_registers=2, main_job=True, recursive_error=False):
            if args.print:
                print(json.dumps(results))
    except KeyboardInterrupt:
        pass
    except Exception:
        raise


if __name__ == '__main__':
    main()
