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

import os
import sys
import argparse
import logging

import base.config
import base.job
import base.utils
import json
import datetime


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


def registerExecution(jobid, config, conffiles, job, params, paths, status, ellapsed=0.0):
    """ Register the execution of the rvt2 in a file with a timestamp.

    Attrs:
        :config: The configuration object. morgue, casename and source will be get from the DEFAULT section.
            The filename is in "rvt2:register". If filename is empty, do not register.
            If "jobname:register" is False, do not register
        :conffiles: List of extra configuration files
        :job: The name of the job
        :params: Any extra params
        :paths: The list of paths
        :status: either 'start', 'end', 'interrupted' or 'error'
        :ellapsed (float): elapsed time (in hours)
    """
    filename = config.get('rvt2', 'register', default=None)
    data = dict(
        _id=jobid,
        date=datetime.datetime.utcnow().isoformat(),
        cwd=os.getcwd(),
        rvthome=config.get('DEFAULT', 'rvthome'),
        conffiles=conffiles,
        morgue=config.get('DEFAULT', 'morgue'),
        casename=config.get('DEFAULT', 'casename'),
        source=config.get('DEFAULT', 'source'),
        job=job,
        params=params,
        paths=paths,
        status=status,
        logfile=base.utils.relative_path(config.get('logging', 'file.logfile', None), config.get('DEFAULT', 'casedir')),
        outfile=base.utils.relative_path(config.get(job, 'outfile', None), config.get('DEFAULT', 'casedir')),
        ellapsed=0.0
    )
    if status == 'start':
        data['date_start'] = data['date']
    if config.get(job, 'register', 'True') != 'False' and filename:
        # errors are ignored
        try:
            with open(filename, 'a') as f:
                f.write(json.dumps(data))
                f.write('\n')
        except Exception:
            pass


def load_default_vars(config, morgue, casename, source, jobid):
    """ Add to the configuration object the default variables: morgue, casename, source and jobid """
    config.config[base.config.DEFAULTSECT]['cwd'] = os.getcwd()
    config.config[base.config.DEFAULTSECT]['userhome'] = os.environ.get('HOME')
    config.config[base.config.DEFAULTSECT]['rvthome'] = os.path.dirname(os.path.abspath(__file__))
    config.config['rvt2']['jobid'] = jobid
    for ar, name in zip([morgue, casename, source], ['morgue', 'casename', 'source']):
        if ar is not None:
            config.config[base.config.DEFAULTSECT][name] = ar


def configure_logging(config, verbose=False, jobname=None):
    """ Configure the logging subsystem.

    Attrs:
        verbose (boolean): If true, set the logging to verbose regardless what the configuration says.
        jobname (String): The name of the job to be run. If None, use basic configuration.
            If the job defines in its section `register: False`, use basic configuration.
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
    aparser = argparse.ArgumentParser(description='Script para...')
    aparser.add_argument('-c', '--config', help='Configuration file. Can be provided multiple times and configuration is appended', action='append')
    aparser.add_argument('-v', '--verbose', help='Outputs debug messages to the standard output', action='store_true', default=False)
    aparser.add_argument('-p', '--print', help='Print the results of the job as JSON', action='store_true', default=False)
    aparser.add_argument('--params', help="Additional parameters to the job, as PARAM=VALUE", action=StoreDict, nargs='*', default={})
    aparser.add_argument('-j', '--job', help='Section name in the configuration file for the main job.', default=None)
    aparser.add_argument('--morgue', help='If provided, ovewrite the value of the morgue variable in the DEFAULT section of the configuration', default=None)
    aparser.add_argument('--casename', help='If provided, ovewrite the value of the casename variable in the DEFAULT section of the configuration', default=None)
    aparser.add_argument('--source', help='If provided, ovewrite the value of the source variable in the DEFAULT section of the configuration', default=None)
    aparser.add_argument('paths', type=str, nargs='*', help='Filename or directories to parse')
    args = aparser.parse_args(params)

    jobid = str(base.utils.generate_id())

    # read configuration from one or more -c options
    config = base.config.Config()
    load_configpaths(config, args.config)
    load_default_vars(config, args.morgue, args.casename, args.source, jobid)

    # configure the logging subsystem using a generic configuration
    configure_logging(config, args.verbose, None)
    # NOW we can log the configuration files, since the logging system is already up
    logging.debug('Configuration files: %s', args.config)

    # Load additional pythonpath
    for pythonpath in base.config.parse_conf_array(config.get('rvt2', 'pythonpath', '')):
        logging.debug('Loading pythonpath: %s', pythonpath)
        sys.path.insert(0, pythonpath)
    logging.debug('Pythonpath: %s', sys.path)
    # Load additional plugins directories
    for pluginspath in base.config.parse_conf_array(config.get('rvt2', 'plugins', '')):
        load_plugin(pluginspath, config)

    # read again configuration from one or more -c options. They MUST overwrite the configuration of the plugins
    load_configpaths(config, args.config)
    # configure default variables again. They MUST overwrite the configuration of the conf files
    load_default_vars(config, args.morgue, args.casename, args.source, jobid)

    # configure the job: if there is a Main section, use it. Else, get the default job from configuration rvt2.default_job
    if args.job is None:
        if config.has_section('Main'):
            args.job = 'Main'
        else:
            args.job = config.get('rvt2', 'default_job')

    # reload the logging system, using the configuration specific for the job
    configure_logging(config, args.verbose, args.job)

    # run job
    jobstarted = datetime.datetime.now()
    registerExecution(jobid, config, args.config, args.job, args.params, args.paths, 'start')
    try:
        for results in base.job.run_job(config, args.job, args.paths, extra_config=args.params):
            if args.print:
                print(json.dumps(results))
        registerExecution(jobid, config, args.config, args.job, args.params, args.paths, 'end', (datetime.datetime.now() - jobstarted) / 3600)
    except KeyboardInterrupt:
        registerExecution(jobid, config, args.config, args.job, args.params, args.paths, 'interrupted', (datetime.datetime.now() - jobstarted) / 3600)
    except Exception:
        registerExecution(jobid, config, args.config, args.job, args.params, args.paths, 'error', (datetime.datetime.now() - jobstarted) / 3600)
        raise


if __name__ == '__main__':
    main()
