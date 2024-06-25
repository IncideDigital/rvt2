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


""" Jobs and modules. """

import os
import os.path
import logging
import ast
import traceback
import shlex
import collections
import time
import datetime
import json
from base.config import parse_conf_array, default_config
import base.utils


def parse_modules_name(input_name, default='True'):
    """
    Parse a module or job name searching for local configurations.

    Parameters:
        input_name (str): The name of a module or job with an optional configuration.
            The optional configuration is appended next to the job name, as pair name=value, or only name.
            See examples below.
        default (str): The default value of a param, when only the name is given.

    Returns:
       A set. The first member if the name of the module or job. The second is the local configuration, if any.

    >>> parse_modules_name('funcname')
    ('funcname', OrderedDict())

    >>> parse_modules_name('funcname ')
    ('funcname', OrderedDict())

    >>> parse_modules_name('funcname greetings="good morning" name="Jim" morning')
    ('funcname', OrderedDict([('greetings', 'good morning'), ('name', 'Jim'), ('morning', 'True')]))
    """
    tokens = shlex.split(input_name)
    if not tokens:
        return (None, None)
    module_name = tokens[0]
    params = collections.OrderedDict()
    for param in tokens[1:]:
        if '=' in param:
            n, v = param.split('=', 1)
            params[n] = v
        else:
            # if = is not in the param, set the name to True
            params[param] = default
    return (module_name, params)


def parse_modules_chain(job_name, myparams, config):
    """
    Parse a list of modules or jobs from a conf_name, taking into account local configuration.

    Args:
        job_name (str): The name of the job. The modules of jobs will be loaded first from "jobs" and, if not found, from "modules".
          The default parameters will be loaded from "default_params".
          The chain string will be managed as a string template, where the "default_params" is applied.
          If the job does not have "jobs" or "modules" configuration, just return the name of the job. The system will
          assume this name id a class name.
        myparams (dict): The local parameters, as returned by parse_modules_name()
        config (base.config.Config): The configuration object for the application.

    Returns:
       A list of modules to load.
    """
    # read modules chain from the section configuration
    # try to read "jobs". If not, then "modules". If not, load a section with the jobname
    modules_chain = config.get(job_name, 'jobs', None)
    is_cascade = False
    if modules_chain is None:
        if config.get(job_name, 'cascade', None):
            modules_chain = config.get(job_name, 'cascade', job_name)
            is_cascade = True
        else:
            modules_chain = config.get(job_name, 'modules', job_name)
    params = ast.literal_eval(config.get(job_name, 'default_params', '{}'))
    if myparams:
        params.update(myparams)
    try:
        modules_chain = modules_chain.format(**params)
    except KeyError as exc:
        raise RVTCritical('KeyError {}: are you sure this option is defined in default_params of job={}?'.format(exc, job_name)) from None
    except ValueError:
        raise RVTCritical('ValueError: are you sure all the params are correctly written for job={}?'.format(job_name)) from None

    # convert modules_chain into an array of module names
    modules = list()
    for module in modules_chain.split('\n'):
        clean_module = module.strip()
        if clean_module:
            modules.append(clean_module)
    if is_cascade:
        modules.reverse()
    return modules


def get_path_array(job_name, myparams, extra_config, default_path, config):
    """
    Get path parameter as an array from the following options and precedence:
        1. myparams (job_with params)
        2. extra_config
        3. parameter
        4. config
    """
    path = myparams.get('path', None)
    if not path and extra_config:
        path = parse_conf_array(extra_config.get('path', None))
    if not path and default_path:
        path = default_path
    if not path and config:
        path = parse_conf_array(config.get(job_name, 'path', default=None))
    if not path:
        path = [None]
    if type(path) == str:
        path = [path]
    return path


def run_job(config, job_name_with_params, path=None, extra_config=None, from_module=None, nested_logs=1, nested_registers=0, main_job=False, recursive_error=True):
    """
    Runs a job from the configuration. This jobs has 'jobs', 'modules' or 'cascade'

    Args:
        config (base.config.Config): The configuration object
        job_name_with_params (str): The name of the job to run. It must be a section in the configuration.
           This string will be parsed using parse_modules_params() and it may include additional parameters.
        path (:obj:`list` of :obj:`str`): Run the job on this paths.
        extra_config (dict): extra local configuration for all the modules in the job. Default: None
        from_module (base.job.BaseModule): use this as the from_module of the last module (only in single jobs)
        nested_logs (int): number of nested jobs to log the execution. (1) logs only the main job. (2) logs the main job and first level jobs. (0) logs nothing
        nested_registers (int): number of nested jobs to register. (1) registers only the main job. (2) registers the main job and first level jobs. (0) registers nothing
        main_job (boolean): If the present run corresponds to the main rvt execution job
        recursive_error (boolean): If True and any subjob has an error, all parent jobs will be registered as error result

    Returns:
        If the job is single (it has 'modules' or 'cascade'), a generator with the result of the execution.
        If the job is composite (it has 'jobs'), return an empty list since the result of each job is probably not related to each other.
        You MUST read each item from the returned generator.
    """

    # Get job parameters
    job_name, myparams = parse_modules_name(job_name_with_params)
    jobs = config.get(job_name, 'jobs', None)
    if extra_config:
        myconfig = extra_config.copy()
    else:
        myconfig = dict()
    myconfig.update(myparams)

    # jobid will be shared for all subjobs of the main job. Otherwise "wait_for_job" won't work as expected
    jobid = config.get('rvt2', 'jobid')

    # Keep track of possible errors to later register even if the main execution continues
    job_error = False

    # Register the start of the execution
    jobstarted = datetime.datetime.now(datetime.timezone.utc)
    (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'start')
    (nested_logs > 0) and logging.info('STARTED job={} client={} casename={} source={}'.format(
        job_name, config.get('DEFAULT', 'client'), config.get('DEFAULT', 'casename'), config.get('DEFAULT', 'source')))

    # Single job case (only modules)
    if jobs is None:
        try:
            results = run_single_job(config, job_name_with_params, default_path=path, extra_config=myconfig, from_module=from_module, log_execution=(nested_logs > 0))
            # return the resulting generator
            if results is None:
                return list()
            yield from results
        except KeyboardInterrupt:
            (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'abort', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
            raise
        except RVTCritical:
            (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'error', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
            raise
        except RVTErrorResumeExecution:
            # If the error is not critical and it is not the main job, raise special exception in order to tell an error ocurred to any jobs loop, but keep the loop running
            (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'error', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
            if not main_job:
                raise
            else:
                return list()
        except Exception as exc:
            # Include exceptions when loading modules
            (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'error', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
            if main_job:
                raise
            else:
                # Let the rest of the jobs being executed
                raise RVTErrorResumeExecution from exc

    # Multiple jobs: run each job separately
    else:
        try:
            for job in parse_modules_chain(job_name, myconfig, config):
                results = run_job(config, job, path=path, extra_config=myconfig, nested_logs=nested_logs - 1, nested_registers=nested_registers - 1, main_job=False, recursive_error=recursive_error)
                try:
                    if results:
                        # run the generator without caring about the results.
                        # Check: https://stackoverflow.com/questions/47456631/simpler-way-to-run-a-generator-function-without-caring-about-items
                        collections.deque(results, maxlen=0)
                except RVTErrorResumeExecution:
                    job_error = True
                    continue
                except Exception:
                    raise
        except KeyboardInterrupt:
            (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'abort', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
            raise
        except RVTCritical:
            (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'error', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
            raise
        except Exception as exc:
            (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'error', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
            if not main_job:
                # If the error is not critical, return special error to any outer loop in the recursion of jobs
                raise RVTErrorResumeExecution from exc
            else:
                return list()

    # Register a job as error if any of its subjobs has errors. This is done recursively if 'recursive_error' is True. Otherwise it just affects the parent job
    if job_error:
        (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'error', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))
    else:
        (nested_registers > 0) and registerExecution(jobid, config, job_name, myparams, path, 'end', (datetime.datetime.now(datetime.timezone.utc) - jobstarted))

    (nested_logs > 0) and logging.info('FINISHED job={} client={} casename={} source={}'.format(
        job_name, config.get('DEFAULT', 'client'), config.get('DEFAULT', 'casename'), config.get('DEFAULT', 'source')))
    if job_error and not main_job and recursive_error:
        raise RVTErrorResumeExecution
    return list()

def run_single_job(config, job_name_with_params, default_path=None, extra_config=None, from_module=None, log_execution=False):
    """
    Runs a job from the configuration. This job has only 'modules', it does not include 'jobs'.

    Args:
        config (base.config.Config): The configuration object
        job_name_with_params (str): The name of the job to run. It must be a section in the configuration.
           This string will be parsed using parse_modules_params() and it may include additional parameters
        default_path (:obj:`list` of :obj:`str`): Run the job on this paths. The order to read paths for a job is:
            1. job_with_params (single path); 2. extra_config; 3. this parameter 4. config
        extra_config (dict): extra local configuration for all the modules in the job. Default: None
        from_module (base.job.BaseModule): use this as the from_module of the last module in the chain
        log_execution (boolean): if True, log the start and finish of the job in the root logger

    Returns:
        A generator that yields each of the results of the execution.
    """
    job_name, myparams = parse_modules_name(job_name_with_params)
    logging.debug('Loading modules for job={} myparams="{}" extra_config="{}"'.format(job_name, myparams, extra_config))

    config.job_name = job_name
    # Get the paths the job will run on
    path = get_path_array(job_name, myparams, extra_config, default_path, config)
    if not extra_config:
        extra_config = {}
    myparams.update(extra_config)

    # initialize modules recursively
    try:
        modules = parse_modules_chain(job_name, myparams, config)
        modules.reverse()
        mymodule = from_module
        for module in modules:
            mymodule = load_module(config, module, from_module=mymodule, extra_config=extra_config)
        # mymodule points to the last module in modules array.
        # Since the modules array was reversed, mymodule points to the FIRST module
        # in the modules configuration parameter
    except Exception as exc:
        logging.error('EXCEPTION job={} client={} casename={} source={}. {}. {}'.format(
            job_name, config.get('DEFAULT', 'client'), config.get('DEFAULT', 'casename'), config.get('DEFAULT', 'source'), exc, traceback.format_exc()))
        raise

    if mymodule is None:
        logging.critical('Critical error: No module loaded for job=%s', job_name)
        raise RVTCritical('No module loaded for job={}'.format(job_name))

    for each_path in path:
        abspath = os.path.abspath(each_path) if each_path is not None else None
        if log_execution:
            logging.info('STARTED job={} on path="{}". client={} casename={} source={}'.format(job_name, abspath, mymodule.myconfig('client'), mymodule.myconfig('casename'), mymodule.myconfig('source')))
        try:
            # notice we manage exceptions, and then we cannot return the generator: it must be run by us
            results = mymodule.run(abspath)
            if results is None:
                return []
            for data in results:
                yield data
        except KeyboardInterrupt:
            logging.warn('INTERRUPTED job={} on path="{}". client={} casename={} source={}'.format(job_name, abspath, mymodule.myconfig('client'), mymodule.myconfig('casename'), mymodule.myconfig('source')))
            raise
        except RVTCritical as exc:
            logging.critical('CRITICAL job={} on path="{}". client={} casename={} source={}. {}. {}'.format(job_name, abspath, mymodule.myconfig('client'), mymodule.myconfig('casename'), mymodule.myconfig('source'), exc, traceback.format_exc()))
            raise
        except Exception as exc:
            # This except block includes RVTError
            if config.get(job_name, 'stop_on_error', 'False')[0] in 'tT1':
                logging.critical('EXCEPTION job={} on path="{}". client={} casename={} source={}. {}. {}'.format(job_name, abspath, mymodule.myconfig('client'), mymodule.myconfig('casename'), mymodule.myconfig('source'), exc, traceback.format_exc()))
                raise RVTCritical from exc
            else:
                logging.error('EXCEPTION job={} on path="{}". client={} casename={} source={}. {}. {}'.format(job_name, abspath, mymodule.myconfig('client'), mymodule.myconfig('casename'), mymodule.myconfig('source'), exc, traceback.format_exc()))
                raise RVTErrorResumeExecution from exc
        finally:
            mymodule.shutdown()
            if log_execution:
                logging.info('FINISHED job={} on path="{}". client={} casename={} source={}'.format(job_name, abspath, mymodule.myconfig('client'), mymodule.myconfig('casename'), mymodule.myconfig('source')))


def load_module(config, confsection, from_module=None, extra_config=None):
    """ Loads a module from a section name.

    Args:
        config (:obj:`base.config.Config`): global configuration object to pass to the module.
        confsection (str): The section name, and optional local configuration.
            The section name is searched in the configuration. If the section is present and it has a "module" attribute,
            load the class "module". If the section is not present or it doesn't have a "module" attribute,
            try to load the section name as a class.
            Format: SECTIONAME{'OPTION': 'VALUE', 'OPTION2': 'VALUE2'}.
        from_module (base.job.BaseModule): pass this value as the from_module configuration. Default: None
        extra_config (dict): extra local configuration for the module. Default: None.
    """
    # get the name of the parse in the section
    section, local_config = parse_modules_name(confsection)
    if not section:
        raise RVTCritical('No section provided: {}'.format(confsection))
    if extra_config is not None:
        if local_config is None:
            local_config = dict()
        local_config.update(extra_config)

    # load the "module" option, or the name of the section itself if not provided
    name = config.get(section, 'module', section)

    # load the class
    components = name.split('.')
    classname = components[-1]
    package = '.'.join(components[:-1])
    if not package:
        raise RVTCritical('No package defined for module: ' + name)
    logging.debug('Loading section=[{}] module={} from package {}'.format(section, classname, package))
    try:
        mod = __import__(package, globals(), locals(), [classname])
        parsercls = getattr(mod, classname)
        return parsercls(config, section=section, local_config=local_config, from_module=from_module)
    except AttributeError as exc:
        raise RVTCritical('Cannot load class {}.{} from section [{}]: classname not found: {}'.format(package, classname, section, exc)) from None
    except TypeError as exc:
        raise RVTCritical('Cannot load class {}.{} from section [{}]: TypeError: {}'.format(package, classname, section, exc)) from exc
    except ImportError as exc:
        raise RVTCritical('Cannot load class {}.{} from section [{}]: ImportError: {}'.format(package, classname, section, exc)) from exc


def wait_for_job(config, job, step=30, timeout=600, job_name=None, exclude_present_job=True):
    """ Manages concurrency of repeated jobs.
        If there is still an instance running of a job that is to be executed, then the new job waits the first one to finish.

    Args:
        config (:obj:`base.config.Config`): global configuration object to pass to the module.
        job (base.job.BaseModule): job object of the new job to be executed.
        step (int): time (in seconds) between consecutive state asking.
        timeout (int): maximum time (in seconds) to wait. After that, the new job is cancelled.
        job_name (str): name of the job to check it's running. By default it will be the present job name itself.
        exclude_jobid (str): Exclude the present job id in the search, since it will always be registered before the present functions is executed.
    """

    now = datetime.datetime.now(datetime.timezone.utc)
    elapsed_time = datetime.timedelta(seconds=0)
    timeout = datetime.timedelta(seconds=timeout)
    available = False

    while elapsed_time < timeout:
        if job.get_job_status(job_name=job_name, exclude_present_job=exclude_present_job) == 'start':
            job.logger().debug('There is already an instance of the same job name "{}" running. Waiting to complete. elapsed_time={}'.format(job_name, str(elapsed_time)))
            time.sleep(step)
            elapsed_time = datetime.datetime.now(datetime.timezone.utc) - now
        else:
            available = True
            break

    if available:
        return
    else:
        raise RVTError('Timeout of {}s exhausted. Job {} will be cancelled'.format(timeout, str(job)))


def registerExecution(jobid, config, job, params, paths, status, elapsed=None):
    """ Register the execution of the rvt2 in a file with a timestamp.

    Attrs:
        :config: The configuration object. client, casename and source will be get from the DEFAULT section.
            The filename is in "rvt2:register". If filename is empty, do not register.
            If "jobname:register" is False, do not register
        :job: The name of the job
        :params: Any extra params
        :paths: The list of paths
        :status: either 'start', 'end', 'abort' or 'error'
        :elapsed (datetime.timedelta): elapsed time
    """
    filename = config.get('rvt2', 'register', default=None)
    client = config.get('DEFAULT', 'client')
    casename = config.get('DEFAULT', 'casename')
    source = config.get('DEFAULT', 'source')
    casedir = config.get('DEFAULT', 'casedir')
    try:
        parameters = ast.literal_eval(config.get(job, 'default_params', '{}'))
        if params:
            parameters.update(params)
    except Exception as exc:
        logging.warn(f'Problems evaluating "default_params" for job "{job}": {exc}')

    data = dict(
        _id=jobid,
        date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        job=job,
        status=status,
        #cwd=os.getcwd(),
        #rvthome=config.get('DEFAULT', 'rvthome'),
        client=client,
        casename=casename,
        source=source,
        #user=os.getlogin(),
        params=params,
        paths=paths,
        logfile=base.utils.relative_path(config.get('logging', 'file.logfile', None), casedir),
        outfile=base.utils.relative_path(parameters.get('outfile', None), casedir),
        elapsed=str(elapsed)
    )
    if status == 'start':
        data['date_start'] = data['date']
    if config.get(job, 'register', 'True') != 'False':
        if filename:
            # errors are ignored
            try:
                with open(filename, 'a') as f:
                    f.write(json.dumps(data))
                    f.write('\n')
            except Exception:
                logging.error(f'Unable to register job execution in "{filename}". Check the folder permissions or this may cause errors later.')
        analyst = logging.getLogger('analyst')
        analyst.info(f'RVT2 job="{job}" for client="{client}", casename="{casename}" on source="{source}". Status="{status}"')


class BaseModule(object):
    """ The base for all modules. Do not use this module directly, always extend it.

    Configuration:
        - **stop_on_error**: If True, stop the execution on an error.
        - **logger_name**: The name of the logger to use.

    Parameters:
        config (base.config.Config): Global configuration for the application. If None, use config.default_config
        section (str): the name of the configuration section for this module in the global configuration object.. If None, use the classname.
        local_config (dict): local configuration for this module. This configuration overrides the values in the section in the global configuration.
        from_module (base.job.BaseModule): If in a chain, the next module in the chain, or None.
    """

    def __init__(self, config=None, section=None, local_config=None, from_module=None):
        if section is None:
            # TODO: I think this is just self.__name__ in Python >=3.6
            self.section = self.__module__ + '.' + self.__class__.__name__
        else:
            self.section = section
        if config is None:
            self.config = default_config
        else:
            self.config = config
        if local_config is None:
            self.local_config = dict()
        else:
            self.local_config = local_config
        self.from_module = from_module
        self.read_config()
        self.logger().debug('Initializing {} from section {}: {}'.format(self.__class__.__name__, section, local_config))

    def logger(self):
        """ Get the logger for this parser.

        Warning:
            Do not store the logger as an internal variable: the user may want to change the logger at any time.
        """
        logger_name = self.myconfig('logger_name', None)
        if logger_name is None:
            # if logger_name is None, return the general logging object
            return logging
        return logging.getLogger(self.myconfig('logger_name'))

    def read_config(self):
        """ Read options from the configuration section.

        This method should set default values for all available configuration options.
        The other module function will safely assume these options have correct values.
        """
        self.set_default_config('stop_on_error', 'True')
        if hasattr(self, 'section'):
            # if a section is configured, use the section as the default value for the logger name
            self.set_default_config('logger_name', self.section)
        else:
            # no section is configured: use the class name as the default value for the logger name
            self.set_default_config('logger_name', self.__class__.__name__)

    def myconfig(self, option, default=None):
        """ Get the value of a configuration for this module.

        Parameters:
            option (str): the name of the option
            default: the dafault value of the option
        """
        if self.local_config and (option in self.local_config):
            return self.local_config[option]
        if hasattr(self, 'config'):
            return self.config.get(self.section, option, default)
        return default

    def options(self):
        """ Return a dictionary with the options available to this job """
        my_options = set()
        if hasattr(self, 'config'):
            my_options.update(self.config.options(self.section))
        if self.local_config:
            my_options.update(self.local_config.keys())
        return my_options

    def myflag(self, option, default=False):
        """ A convenience method for self.config.getboolean(self.section, option, False) """
        value = self.myconfig(option, str(default))
        return value in ('True', 'true', 'TRUE', 1)

    def myarray(self, option, default=[]):
        """ A convenience method to get an array from a configuration.
            The input string may be one of two options:
            - Space separated terms. Ex: 'itemA itemB'
            - Literal python list definition. Ex: '["itemA","itemB"]'
        """
        value = self.myconfig(option, '')
        if not value:
            return default
        if value.startswith('[') and value.endswith(']'):
            return ast.literal_eval(value)
        else:
            return parse_conf_array(value)

    def set_default_config(self, option, default=None):
        """ Get the value of a configuration for this module.

        Parameters:
            option (str): the name of the option
            default (str): the dafault value of the option. It MUST be a string.
        """
        if self.myconfig(option, default=None) is None:
            if self.local_config is None:
                self.local_config = dict()
            self.local_config[option] = default

    def check_params(self, path, check_from_module=False, check_path=False, check_path_exists=False):
        """
        Check the module is configured correctly.
        Extend this function to run your own tests.

        Parameters:
            path (str): The path passed to the run() method.
            check_from_module (boolean): If True, check a from_module is defined.
            check_path (boolean): If True, check the path is not None.
            check_path_exists (boolean): If True, check the path exists.

        Raises:
            RVTError if the tests are not passed.
        """
        if check_from_module:
            if not hasattr(self, 'from_module') or self.from_module is None:
                raise RVTError('from_module not defined')
        if check_path:
            if path is None:
                raise RVTErrorNonePath('path is not provided')
            if check_path_exists:
                if not os.path.exists(path):
                    raise RVTErrorNotExistingPath('path {} does not exist'.format(path))

    def run(self, path=None):
        """ Run the job on a path

        Args:
            path (str): the path to check.

        Yields:
            If any, an iterable of elements with the output.
        """
        self.check_params(path, check_from_module=True)
        return self.from_module.run(path)

    def shutdown(self):
        """ This function will be called at the end of the execution of a job.

        The shutdown() function of the from_module is called recursively. """
        if hasattr(self, 'from_module') and self.from_module is not None and hasattr(self.from_module, 'shutdown'):
            self.from_module.shutdown()
        # request to save the local store
        self.config.store_set(option=None, save=True)

    def get_job_status(self, job_name=None, exclude_present_job=True):
        """ Find if there is any job with provided name running on the same source.
            Used to determine if the job can run or must wait to other job to finish.

        Args:
            job_name (str): name of the job to check. By default it will be the present job name itself.
            exclude_jobid (str): Exclude the present job id in the search, since it will always be registered before the present functions is executed.

        Returns:
            The last registered state for a job as such. Options: 'new', 'start', 'end', 'abort', 'error'.
        """
        if not job_name:
            job_name = self.config.job_name
        if exclude_present_job:
            jobid = self.config.get('rvt2', 'jobid')
        module = load_module(self.config, 'base.input.JSONReader', extra_config={'progress.disable': True})
        last_status = 'new'
        for register in module.run(self.config.get('rvt2', 'register', None)):
            if exclude_present_job and register["_id"] == jobid:
                continue
            if register["job"] == job_name and register["source"] == self.config.get('DEFAULT', 'source'):
                last_status = register["status"]
        return last_status


class RVTError(Exception):
    """ A special class for Exceptions inside the RVT. The module or job cannot continue. """
    pass


class RVTCritical(Exception):
    """ A special class for Exceptions inside the RVT. The rvt2 cannot continue. """
    pass


class RVTErrorNonePath(RVTError):
    """ A special class for Exceptions inside the RVT. The module or job cannot continue. """
    pass


class RVTErrorNotExistingPath(RVTError):
    """ A special class for Exceptions inside the RVT. The module or job cannot continue. """
    pass


class RVTErrorResumeExecution(RVTError):
    """ A special class for Exceptions inside the RVT. The following module or job can continue despite the error. """
    pass
