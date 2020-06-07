#!/usr/bin/env python3
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

""" Modules to index documents parsed by other modules into ElasticSearch. """

import datetime
import json
import requests
import os
import logging
import shutil
import time
import ssl

from elasticsearch import Elasticsearch
import elasticsearch.helpers
from elasticsearch.serializer import JSONSerializer
from tqdm import tqdm

import base.job
import base.config
from base.commands import estimate_iterations
from base.utils import generate_id
import uuid

__maintainer__ = 'Juanvi Vera'


class _CustomSerializer(JSONSerializer):
    """ A custom serializer for types we might find and are not supported by the standard serializer """
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return JSONSerializer.default(self, obj)


def coolOff(every=100, seconds=10):
    """ A generator to wait a number of seconds after calling 'every' times. If every == 0, do not wait ever. """
    n = 1
    while True:
        if every != 0 and n % every == 0:
            time.sleep(seconds)
        n += 1
        yield


def get_esclient(es_hosts, retry_on_timeout=False, logger=logging, username=None, password=None, cafile=None, verify_ssl=True):
    """ Get an elasticsearch.Elasticsearch object.

    Attrs:
        :es_hosts: A list of elastis servers
        :retry_on_timeout: If true, retry queries after a timeout
        :logger: The logger to use
        :cafile: Absolute path to the CA that certifies the ElasticSearch server
        :username: Username in the ElasticSearch server. If None, do nt authenticate.
        :password: Password in the ElasticSearch server. If None, do nt authenticate.
        :verify_ssl: If True, verify the SSL connection.

    Returns:
        An elasticsearch.Elasticsearch object

    Raises:
        base.job.RVTError if any of the server is available
    """

    if verify_ssl:
        context = ssl.create_default_context(cafile=cafile)
    else:
        context = ssl._create_unverified_context()
    context.check_hostname = False
    http_auth = (username, password) if username else None

    # Check if any of the hosts can be contacted
    hosts = base.config.parse_conf_array(es_hosts)
    someone_answered = False
    for host in hosts:
        if base.config.check_server(host):
            someone_answered = True
    if not someone_answered:
        logger.error('ElasticSearch hosts are not reacheable: %s', hosts)
        raise base.job.RVTError('ElasticSearch hosts are not reacheable: {}'.format(hosts))

    logger.info('Connecting to %s', hosts)
    return Elasticsearch(
        hosts,
        serializer=_CustomSerializer(), retry_on_timeout=retry_on_timeout, timeout=30,
        http_auth=http_auth,
        ssl_context=context)


def _actions(origin, tag_fields=[], logger=logging):
    """ Converts a piece of data from an origin into a data ready to be indexed using the elasticsearch library

    Attrs:
        origin: a source of data, such as a file or a generator.
        tag_fields: an array with the name of the fields to be managed as tags.
            If one of these fields is ingected, add a special operation named "tag".
            This operation will be managed by _expand_action()

    Returns:
        Each of the pieces of data in origin, filtered as decribed before.
    """
    for data in origin:
        # if origin is a string, convert to json
        if isinstance(data, str):
            data = json.loads(data)
        for tf in tag_fields:
            new_tag = data.get('_source', {}).pop('{}-new'.format(tf), None)
            if new_tag is not None:
                yield dict(
                    _op_type='tag',
                    tags_field=tf,
                    new_tag=new_tag,
                    _index=data['_index'],
                    _id=data['_id'],
                    _type=data['_type']
                )
        yield data


def _expand_action(data):
    """
    From one document or action definition passed in by the user extract the
    action/data lines needed for elasticsearch's, as described in:
    <https://elasticsearch-py.readthedocs.io/en/master/helpers.html>
    """
    # when given a string, convert to json
    if isinstance(data, str):
        data = json.loads(data)

    # make sure we don't alter the action
    data = data.copy()
    op_type = data.pop('_op_type', 'index')
    action = {op_type: {}}
    # remove from the data array those fields that are metadata for the indexation process
    # these fields are listed in the ElasticSearch documentation
    for key in ('_index', '_parent', '_percolate', '_routing', '_timestamp', 'routing',
                '_type', '_version', '_version_type', '_id',
                'retry_on_conflict', 'pipeline'):
        if key in data:
            action[op_type][key] = data.pop(key)

    # no data payload for delete
    if op_type == 'delete':
        return action, None
    elif op_type == 'index':
        return action, data.get('_source', data)
    elif op_type == 'update':
        # Update is always upsert
        return action, {'doc_as_upsert': True, 'doc': data.get('_source', data)}
    elif op_type == 'tag':
        # This operation is special: add a new tag to a tags array
        # This operation takes two parameters: tags_field is the name of the tags array, and new_tag is the new tag
        action['update'] = action.pop('tag')
        tags_field = data['tags_field']
        return action, {
            'script': {
                'source': 'if (ctx._source.containsKey("{tags_field}")) {{ if(!ctx._source["{tags_field}"].contains(params.new_tag)) {{ctx._source.{tags_field}.add(params.new_tag);}} }} else {{ctx._source.{tags_field} = [params.new_tag]}}'.format(tags_field=tags_field),
                'params': {'new_tag': data.get('new_tag')}
            }
        }


class ElasticSearchAdapter(base.job.BaseModule):
    """ A module to adapt the results from other modules to a format suitable to be indexed in bulk into ElasticSearch.

    This module also registers its own execution and results in the index defined in configuration `rvtindex`.

    Configuration:
        - **name**: the name of the index in ElasticSearch. The name will be converted to lowcase, since ES only accept lowcase names.
        - **doc_type**: the doc_type in ElasticSearch.
          Do not change the default value ``"_doc"``, it will be deprecated in ES>6.
        - **operation**: The operation for elastic search. Possible values are "index" (default) overwrites data, or
          "update" updates existing data with new information. An update does always an upsert.
        - **casename**: The name of the case
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('name', self.myconfig('source'))
        self.set_default_config('doc_type', '_doc')
        self.set_default_config('operation', 'update')
        self.set_default_config('casename', 'casename')

    def run(self, path):
        """
        Returns:
            An iterator with the adapted JSON.
        """
        self.logger().info('Indexing: %s', path)
        self.check_params(path, check_from_module=True)

        name = self.myconfig('name').lower()
        doc_type = self.myconfig('doc_type')

        exit_status = ''
        # read tags from the section
        mytags = base.config.parse_conf_array(self.myconfig('tags'))
        try:
            for fileinfo in self.from_module.run(path):
                # save custom tags for this parser, if any
                if mytags:
                    fileinfo['tags'] = mytags
                # get or generate an identifier
                _id = str(generate_id(fileinfo))
                # if the fileinfo already provides an index name, use it. If not, use the default index name
                fileindex = fileinfo.pop('_index') if '_index' in fileinfo else name
                yield dict(_index=fileindex, _type=doc_type, _id=_id, _source=fileinfo, _op_type=self.myconfig('operation'))
            exit_status = 'ended'
        except base.job.RVTError as exc:
            # After an error, log as a warning and end the module
            import traceback
            tb = traceback.format_exc()
            self.logger().warning(tb)
            self.logger().error(str(exc))
            exit_status = 'error'
        except KeyboardInterrupt:
            # if the module was interrupted
            exit_status = 'interrupted'


class ElasticSearchRegisterSource(base.job.BaseModule):
    """ Registers or updates a source in ElasticSearch.

    Configuration section:
        - **es_hosts**: a space separated list of hosts of ElasticSearch. Example: ``http://localhost:9200``. The port is mandatory.
        - **es_username**: username for the ElaticSearch server. Empty to not use authentication.
        - **es_password**: password for the ElaticSearch server. Empty to not use authentication.
        - **es_cafile**: CA file for the ElaticSearch server.
        - **verify_ssl**: True to verify the SSL certificate.
        - **name**: the name of the index in ElasticSearch. Defaults to the source name.
        - **casename**: The name of the case
        - **server**: The URL of the file server to access directly to the files.
        - **rvtindex**: The name of the index where the run of this module will be registered. The name MUST be in lowcase.
          If empty or None, the job is not registered.
        - **description**: The description of the source. If empty, do not update description.
        - **tabsdb**: A database of tabs to create
        - **tabs**: The name of the tabs in the database to create in analyzer. If empty, do not update tabs.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('es_hosts', 'localhost:9200')
        self.set_default_config('es_username', '')
        self.set_default_config('es_password', '')
        self.set_default_config('es_cafile', '')
        self.set_default_config('verify_ssl', 'True')
        self.set_default_config('name', self.myconfig('source'))
        self.set_default_config('casename', 'casename')
        self.set_default_config('server', 'http://localhost:80')
        self.set_default_config('rvtindex', 'rvtindexer')
        self.set_default_config('description', '')
        self.set_default_config('tabsdb', os.path.join(self.config.get('indexer', 'plugindir'), 'analyzer-tabs.json'))
        self.set_default_config('tabs', '')

    def load_tabs(self):
        """ Returns the tabs as configured in config, or None """
        tabs = self.myconfig('tabs')
        if not tabs:
            return None
        tabsdb = self.myconfig('tabsdb')
        if not tabsdb or not os.path.exists(tabsdb):
            self.logger().warning('The tabs database does not exists: tabsdb="%s"', tabsdb)
            return None
        with open(tabsdb) as json_file:
            registered_tabs = json.load(json_file)
            return registered_tabs.get(tabs, None)

    def run(self, path=None):
        name = self.myconfig('name')
        rvtindex = self.myconfig('rvtindex')
        metadata = dict(
            casename=self.myconfig('casename'),
            source=self.myconfig('source'),
            server=self.myconfig('server'),
            name=name,
        )

        # Update these fields only if provided
        tabs = self.load_tabs()
        if tabs is not None:
            metadata['tabs'] = tabs
        description = self.myconfig('description')
        if description:
            metadata['description'] = description

        esclient = get_esclient(
            self.myconfig('es_hosts'), retry_on_timeout=self.myflag('retry_on_timeout'), logger=self.logger(),
            username=self.myconfig('es_user'), password=self.myconfig('es_password'), cafile=self.myconfig('es_cafile'),
            verify_ssl=self.myflag('verify_ssl'))

        if esclient.exists(index=rvtindex, id=name, _source=False):
            esclient.update(index=rvtindex, id=name, body=dict(doc=metadata))
        else:
            esclient.index(index=rvtindex, id=name, body=metadata)
        return []


class ElasticSearchRegisterCase(base.job.BaseModule):
    """ Registers or updates a case in ElasticSearch.

    Configuration:
        - **es_hosts**: a space separated list of hosts of ElasticSearch. Example: ``http://localhost:9200``. The port is mandatory.
        - **es_username**: username for the ElaticSearch server. Empty to not use authentication.
        - **es_password**: password for the ElaticSearch server. Empty to not use authentication.
        - **es_cafile**: CA file for the ElaticSearch server.
        - **verify_ssl**: True to verify the SSL certificate.
        - **casename**: The name of the case
        - **rvtindex**: The name of the index where the run of this module will be registered. The name MUST be in lowcase.
        - **description**: The description of the case. If empty, do not update the description.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('es_hosts', 'localhost:9200')
        self.set_default_config('es_username', '')
        self.set_default_config('es_password', '')
        self.set_default_config('es_cafile', '')
        self.set_default_config('verify_ssl', 'True')
        self.set_default_config('casename', 'casename')
        self.set_default_config('rvtindex', 'rvtcases')
        self.set_default_config('description', '')

    def run(self, path=None):
        casename = self.myconfig('casename')
        rvtindex = self.myconfig('rvtindex')
        metadata = dict(
            name=casename,
        )

        # Update these fields only if provided
        description = self.myconfig('description')
        if description:
            metadata['description'] = description

        esclient = get_esclient(
            self.myconfig('es_hosts'), logger=self.logger(),
            username=self.myconfig('es_user'), password=self.myconfig('es_password'), cafile=self.myconfig('es_cafile'),
            verify_ssl=self.myflag('verify_ssl'))
        if esclient.exists(index=rvtindex, id=casename, _source=False):
            esclient.update(index=rvtindex, id=casename, body=dict(doc=metadata))
        else:
            esclient.index(index=rvtindex, id=casename, body=metadata)
        return []


class ElasticSearchBulkSender(base.job.BaseModule):
    """ A module to index the results from the ``ElasticSearchAdapter`` into an ElasticSearch server.

    Configuration:
        - **es_hosts**: a space separated list of hosts of ElasticSearch. Example: ``http://localhost:9200``. The port is mandatory.
        - **es_username**: username for the ElaticSearch server. Empty to not use authentication.
        - **es_password**: password for the ElaticSearch server. Empty to not use authentication.
        - **es_cafile**: CA file for the ElaticSearch server.
        - **verify_ssl**: True to verify the SSL certificate.
        - **name**: the name of the index in ElasticSearch. If the index does not exist, create it using `mapping`.
             The name will be converted to lower case, since ES only accept lower case names.
        - **mapping**: If the index `name` must be created, use this file for initial settings and mappings.
        - **chunk_size**: The number of documents to send to elastic in each batch.
        - **tag_fields**: A space separated list of names of the fields that include tags.
          A new tag is appended using the special field "tag_field-new". For example, you
          can append to the field "tags" a tag in "tags-new".
        - **only_test**: If True, do not submit the final queries to ElasticSearch but yield them.
        - **offset**: ignore this number of lines at the beginning of the file.
        - **restartable**: if True, save the current status in the store to allow restarting the job.
        - **max_retries**: max number of retries after a HTTP 429 from the server (too many requests)
        - **retry_on_timeout**: If True, retry on TimeOut (the server is busy)
        - **progress.disable** (Boolean): If True, disable the progress bar.
        - **progress.cmd**: Run this command to know the number of actions to send.
        - **cooloff.every**: after sending cooloff.every number of items, wait cooloff.seconds.
        - **cooloff.seconds**: after sending cooloff.every number of items, wait cooloff.seconds.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('es_hosts', 'localhost:9200')
        self.set_default_config('es_username', '')
        self.set_default_config('es_password', '')
        self.set_default_config('es_cafile', '')
        self.set_default_config('verify_ssl', 'True')
        self.set_default_config('name', self.myconfig('source'))
        # self.set_default_config('mapping', os.path.join(self.myconfig('rvthome'), 'conf', 'indexer', 'es-settings.json'))
        self.set_default_config('mapping', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'es-settings.json'))
        self.set_default_config('chunk_size', '10')
        self.set_default_config('tag_fields', 'tags blindsearches')
        self.set_default_config('offset', '0')
        self.set_default_config('restartable', 'False')
        self.set_default_config('only_test', 'False')
        self.set_default_config('max_retries', '5')
        self.set_default_config('progress.disable', 'False')
        self.set_default_config('progress.cmd', 'cat "{path}" | wc -l')
        self.set_default_config('retry_on_timeout', 'True')
        self.set_default_config('cooloff.every', '300')
        self.set_default_config('cooloff.seconds', '5')

    def run(self, path):
        """
        Parameters:
            path (str): The path tp the file to upload to the ElasticSearch server.
                Each line is an action as described in <https://elasticsearch-py.readthedocs.io/en/master/helpers.html>.

                "index" actions are also compatible with `elasticdump`, and you can
                upload the file using `elasticdump` if you prefer.

                You MUST use this module if the operation from ElasticSearchAdapter
                is "update", since `elasticdump` always overwrites data.
        """
        self.logger().info('Running on: %s', path)
        self.check_params(path, check_path=True, check_path_exists=True)

        esclient = get_esclient(
            self.myconfig('es_hosts'), retry_on_timeout=self.myflag('retry_on_timeout'), logger=self.logger(),
            username=self.myconfig('es_user'), password=self.myconfig('es_password'), cafile=self.myconfig('es_cafile'),
            verify_ssl=self.myflag('verify_ssl'))

        # create the index, if it doesn't exist
        name = self.myconfig('name').lower()
        chunk_size = int(self.myconfig('chunk_size'))
        if not esclient.indices.exists(index=name):
            # read initial mapping and settings from file, if exists
            mapping_filename = self.myconfig('mapping')
            mapping = None
            if mapping_filename is not None:
                self.logger().debug('Loading mapping: %s', mapping_filename)
                with open(mapping_filename) as mapping_file:
                    mapping = json.loads(mapping_file.read())
            else:
                self.logger().warning('No mapping defined for index: %s', name)
            # create the index
            self.logger().info('Creating index %s', name)
            esclient.indices.create(index=name, body=mapping, include_type_name=False)
        else:
            self.logger().warning('The index already exists: %s', name)

        with open(path) as inputfile:
            # current_offset is: current_offset in the store, or an offset in the configuration if provided
            restartable = self.myflag('restartable')
            if restartable:
                current_offset = int(self.config.store_get('current_offset', self.myconfig('offset', '0')))
            else:
                current_offset = int(self.myconfig('offset', '0'))
            # read the initial offset
            for i in range(0, current_offset):
                inputfile.readline()
            actions = _actions(
                inputfile,
                tag_fields=base.config.parse_conf_array(self.myconfig('tag_fields')),
                logger=self.logger()
            )
            total_actions = estimate_iterations(path, self.myconfig('progress.cmd'))
            if self.myflag('only_test'):
                for action in tqdm(actions, desc=self.section, disable=self.myflag('progress.disable'), total=total_actions):
                    yield action
            else:
                cooloff = coolOff(every=int(self.myconfig('cooloff.every')), seconds=int(self.myconfig('cooloff.seconds')))
                with tqdm(total=total_actions, initial=current_offset) as pbar:
                    for ok, result in elasticsearch.helpers.streaming_bulk(
                            esclient, actions, expand_action_callback=_expand_action,
                            chunk_size=chunk_size,
                            raise_on_error=self.myflag('stop_on_error'), raise_on_exception=False,
                            max_retries=int(self.myconfig('max_retries')), initial_backoff=10):
                        if not ok:
                            self.logger().error('Cannot index to elastic document result=%s', result)
                        pbar.update(1)
                        if restartable:
                            current_offset += 1
                            self.config.store_set('current_offset', current_offset)
                        next(cooloff)
            # reset the current offset in the store
            self.config.store_set('current_offset', None)


class ElasticSearchQuery(base.job.BaseModule):
    """ Query ES and yield the results.

    The path is ignored.

    Configuration section:
        - **es_hosts**: An array of strings with the ES servers.
        - **es_username**: username for the ElaticSearch server. Empty to not use authentication.
        - **es_password**: password for the ElaticSearch server. Empty to not use authentication.
        - **es_cafile**: CA file for the ElaticSearch server.
        - **verify_ssl**: True to verify the SSL certificate.
        - **name**: The name of the index to query.  The name will be converted to lower case, since ES only accept lower case names.
        - **query**: The query in lucene language.
        - **source_includes**: a space separated list of fields to include in the answer. Use empty string for all fields.
        - **source_excludes**: a space separated list of fields NOT to include in the answer.
        - **progress.disable**: if True, disable the progress bar.
        - **max_results**: If the query affects to more than this number of documents, raise an RVTCritical error to stop the execution.
            Set to 0 to disable.
        - **retry_on_timeout**: If True, retry after ES returned a timeour error.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('es_hosts', 'localhost:9200')
        self.set_default_config('es_username', '')
        self.set_default_config('es_password', '')
        self.set_default_config('es_cafile', '')
        self.set_default_config('verify_ssl', 'True')
        self.set_default_config('name', self.myconfig('source'))
        self.set_default_config('query', '*')
        self.set_default_config('source_includes', '')
        self.set_default_config('source_excludes', '')
        self.set_default_config('progress.disable', 'False')
        self.set_default_config('max_results', '1000')
        self.set_default_config('retry_on_timeout', 'True')

    def run(self, path=None):
        esclient = get_esclient(
            self.myconfig('es_hosts'), retry_on_timeout=self.myflag('retry_on_timeout'), logger=self.logger(),
            username=self.myconfig('es_user'), password=self.myconfig('es_password'), cafile=self.myconfig('es_cafile'),
            verify_ssl=self.myflag('verify_ssl'))

        max_results = int(self.myconfig('max_results'))
        query = {
            'query': {
                'query_string': {
                    'query': self.myconfig('query'),
                    'default_field': '*',
                    'analyze_wildcard': True
                }
            }
        }
        name = self.myconfig('name').lower()
        total = esclient.count(index=name, body=query)['count']
        # if there are more affected documents than max_results, stop
        if max_results > 0 and total > max_results:
            raise base.job.RVTCritical('The affected documents will be more than the configured limit: total={} max_results={}. Stopping. Set max_results=0 to dismiss or change the query.'.format(total, max_results))
        for result in tqdm(elasticsearch.helpers.scan(
                           esclient,
                           index=name,
                           q=self.myconfig('query'),
                           _source_includes=base.config.parse_conf_array(self.myconfig('source_includes')),
                           _source_excludes=base.config.parse_conf_array(self.myconfig('source_excludes')),
                           raise_on_error=self.myflag('stop_on_error')
                           ), total=total, disable=self.myflag('progress.disable')):
            data = result['_source']
            data['_id'] = result['_id']
            data['_index'] = result['_index']
            yield data


class ElasticSearchQueryRelated(base.job.BaseModule):
    """ Query ES and yield all documents related to the query: containers, attachments...

    The path is ignored.

    Configuration section:
        - **es_hosts**: An array of strings with the ES servers.
        - **es_username**: username for the ElaticSearch server. Empty to not use authentication.
        - **es_password**: password for the ElaticSearch server. Empty to not use authentication.
        - **es_cafile**: CA file for the ElaticSearch server.
        - **verify_ssl**: True to verify the SSL certificate.
        - **name**: The name of the index to query. The name will converted into lower case.
        - **query**: The query in lucene language.
        - **source_includes**: a space separated list of fields to include in the answer. Use empty string for all fields.
        - **source_excludes**: a space separated list of fields NOT to include in the answer.
        - **retry_on_timeout**: If True, retry after ES returned a timeour error.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('es_hosts', 'localhost:9200')
        self.set_default_config('es_username', '')
        self.set_default_config('es_password', '')
        self.set_default_config('es_cafile', '')
        self.set_default_config('verify_ssl', 'True')
        self.set_default_config('name', self.myconfig('source'))
        self.set_default_config('query', '*')
        self.set_default_config('source_includes', '')
        self.set_default_config('source_excludes', '')
        self.set_default_config('retry_on_timeout', 'True')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        esclient = get_esclient(
            self.myconfig('es_hosts'), retry_on_timeout=self.myflag('retry_on_timeout'), logger=self.logger(),
            username=self.myconfig('es_user'), password=self.myconfig('es_password'), cafile=self.myconfig('es_cafile'),
            verify_ssl=self.myflag('verify_ssl'))

        name = self.myconfig('name').lower()
        for result in self.from_module.run(path):
            if not result.get('_id', ''):
                raise base.job.RVTError('Results must include _id')
            containerid = result.get('containerid', '')
            if containerid in ('', '0', 0, None):
                # it is a container: return the item
                yield dict(_id=result['_id'], containerid='0', _index=result.get('_index', name))
                # and its children
                for child in elasticsearch.helpers.scan(
                    esclient,
                    index=name,
                    q='containerid:{}'.format(result['_id']),
                    _source_includes=['NOFIELD'],
                    raise_on_error=self.myflag('stop_on_error')
                ):
                    yield dict(_id=result['_id'], containerid=containerid)
            else:
                # it is not a container
                # return its siblings (notice this will include the item again)
                for sibling in elasticsearch.helpers.scan(
                    esclient,
                    index=name,
                    q='containerid:{}'.format(containerid),
                    _source_includes=['containerid'],
                    raise_on_error=self.myflag('stop_on_error')
                ):
                    yield dict(_id=sibling['_id'], containerid=sibling['_source'].get('containerid', 'ERROR'), _index=sibling['_index'])
                # and the parent
                parent = esclient.get(index=name, id=containerid, _source=False)
                yield dict(_id=parent['_id'], containerid='0', _index=result.get('_index', name))


class ExportFiles(base.job.BaseModule):
    def read_config(self):
        self.set_default_config('outdir', 'export')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        mailsdir = self.config.get('plugins.common', 'mailsdir', default=None)
        casedir = self.myconfig('casedir')
        target = self.myconfig('outdir')
        for data in self.from_module.run(path):
            rel_path = data['path']
            abs_original_path = os.path.join(casedir, rel_path)
            if abs_original_path.startswith(mailsdir) and abs_original_path[-3:] in ('tml', 'txt', 'rtf'):
                rel_path = os.path.dirname(rel_path)
                abs_original_path = os.path.join(casedir, rel_path)
            target_path = os.path.join(target, rel_path)
            if not os.path.exists(target_path):
                if os.path.isdir(abs_original_path):
                    shutil.copytree(abs_original_path, target_path)
                else:
                    base.utils.check_directory(os.path.dirname(target_path), create=True)
                    shutil.copy2(abs_original_path, target_path)
            yield data
