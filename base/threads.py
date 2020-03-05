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

import threading
import queue
import logging
import base.job

""" A module to run jobs in separated threads """


def run_job(*args, daemon=False, **kwargs):
    """
    Runs a job from the configuration in a different thread.

    Returns:
        The new thread
    """
    logging.info('Starting new job in a different thread: job="%s" daemon=%s', args[1], daemon)
    t = threading.Thread(target=worker, args=args, kwargs=kwargs)
    t.daemon = daemon
    t.start()
    return t


def worker(*args, **kwargs):
    """ The worker that actually runs a job in a thread.

    This worker only consumes the generator returned by the job. It does nothing else
    """
    for data in base.job.run_job(*args, **kwargs):
        pass


class Fork(base.job.BaseModule):
    """ A module to send the data received from from_module up in the chain and to a job in a different thread.

    Configuration:
        - **secondary_job**: The name of the job to run in the secondary thread. This job cannot be composite (only 'modules' allowed)
          and it will receive the data in the last module of the chain.
    """
    def read_config(self):
        self.set_default_config('secondary_job', 'base.output.JSONSink')

    def run(self, path):
        self.check_params(path, check_from_module=True)

        job = self.myconfig('secondary_job')
        self.myqueue = queue.Queue()
        injected = _InjectedInput(self.config, from_module=self.myqueue)
        # the job won't run as a daemon, as it MUST acknowledge the task_done(). See InjectedIput
        t = run_job(self.config.copy(), job, daemon=False, from_module=injected)

        # the first object we get from the queue is the sentinel
        self.sentinel = object()
        self.myqueue.put(self.sentinel)
        for data in self.from_module.run(path):
            self.myqueue.put(data.copy())
            yield data
        # wait for secondary threads and queues to finish
        self.myqueue.put(self.sentinel)
        self.myqueue.join()
        t.join()
        self.myqueue = None

    def shutdown(self):
        # if queue is not None, the module chain ended with an error: send the sentinel to the queue to stop it
        if hasattr(self, 'myqueue') and self.myqueue is not None:
            self.myqueue.put(self.sentinel)
            # notice we are not waiting for the queue to finish
            self.myqueue = None


class _InjectedInput(base.job.BaseModule):
    """ A module to yield the data received injected from a queue.

    This module is not intended to be used directly in any job other than a Fork.
    """
    def run(self, path):
        self.check_params(path, check_from_module=True)
        # actually, from_module is the queue
        queue = self.from_module
        # the first object we get from the queue is the sentinel
        sentinel = self.from_module.get()
        self.from_module.task_done()

        while True:
            data = queue.get()
            if data is sentinel:
                queue.task_done()
                break
            try:
                yield data
            finally:
                queue.task_done()
