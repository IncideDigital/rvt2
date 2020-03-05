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


""" Tika management.

In this file:

- `metadata` refers to a file metadata as returned by Tika. `Metadata` may not
  have a name suitable for coding, such as the slash in `content-type` and the
  name depends on the file type and the specific parser Tika, and there are
  hundred of  different names. Metadata with the same semantics in different
  file types may have different names. For example, `dc:author`, `author`,
  `metadata:author`...
- `field` refers to a metadata in the dictionary the modules in this file
  return. `metadata` is mapped to a `field`, possibly normalized or converted or
  maybe ignored. There is a file to configure the mapping between `fields` and
  `metadata`.

Todo:
  - Allow using a standalone Tika, not the server mode.
  - Tell Tika somehow which parser must use for a file. Specially useful to
    improve the time to parse plain text files, since Tika test all possible parsers on them by default.

"""

import os
import os.path
import json
import configparser
import requests

import mimeparse

from base.utils import generate_id
import base.job
import base.config
import base.utils

__maintainer__ = 'Juanvi Vera'

# metadata fields mapped to this string are not indexed, even if include_unknown is True
IGNORE_FIELD = 'IGNORE'

# dictionary of hooks content_type -> function(filepath, metadata)
hooks = dict()


class TikaParser(base.job.BaseModule):
    """ A module to parse files using Tika.

    A Tika server must be running before creating this module.
    If the configured Tika server is not available, an exception will be raised.

    Documents are parsed and their metadata and content are returned as a dictionary.
    By default, only some metadata (*fields*) are returned.

    Beware of the character limit on files parsed by Tika: 100k characters.

    Configuration:
        - **tika_server**: a URL to a preexisting TIKA server. Example: ``http://localhost:9998``. The port is mandatory.
        - **mapping**: path to the mapping configuration file.
          By default, not all metadata is yielded.
          Metadata must be mapped to a field name, and only fields mapped are returned.
          This prevents the "field explosion problem" and metadata with the same semantics but different names for different file types.

          The mapping file is a standard cfg file. See the default example:

          - Sections are content types.
          - Values map ``metadata=field``. If field name is empty or IGNORED and ``include_unknown`` is set to ``False``,
            this metadata will be ignored. In field names, try to use Python standard named: change - to _, no spaces...
        - **save_mapping**: if True, save in the mapping configuration file any new metadata you found.
        - **include_unknown**: if True, add metadata without a mapping to the results.
        - **error_status** (int): Error status code to report in case Tika is not available while parsing a specific file.
        - **file_max_size** (int): The max size in bytes of a file to be parsed. If the file is larger than this, it is not parsed and tika_status set to 413 (payload too large)
        - **content_max_size** (int): The max size in bytes of a content to be parsed. If the content is larger than this, it is removed and tika_status set to (payload too large)
        - **tika_encoding** (str): The encoding of the answers from tika
    """
    def __init__(self, *attrs, **kwattrs):
        super().__init__(*attrs, **kwattrs)

        # check if the tika server is available, or raise an error
        tika_server = self.myconfig('tika_server')
        if not base.config.check_server(tika_server):
            self.logger().error('Tika server is not reacheable: %s', tika_server)
            raise base.job.RVTError('Tika server is not reacheable: {}'.format(tika_server))

    def read_config(self):
        super().read_config()
        self.set_default_config('tika_server', 'http://localhost:9998')
        self.set_default_config('mapping', os.path.join(self.config.get('indexer', 'plugindir', './'), 'tika-mapping.cfg'))
        self.set_default_config('save_mapping', 'False')
        self.set_default_config('include_unknown', 'False')
        self.set_default_config('error_status', 400)
        self.set_default_config('file_max_size', 104857600)  # default: 100MB
        self.set_default_config('content_max_size', 52423800)  # default: 50MB
        self.set_default_config('tika_encoding', 'UTF8')  # default: 100MB

        # finally, read the mapping configuration
        self._mapping = configparser.ConfigParser()
        self._mapping.read(self.myconfig('mapping'))

    def shutdown(self):
        """ Function to call at the end of a parsing session.

        If option ``save_mapping`` is True, write the cuurent mapping configuration into the mapping configuration file.
        This is useful to discover new metadata fields not yet mapped."""
        base.job.BaseModule.shutdown(self)
        if self.myflag('save_mapping'):
            self.logger().info('Shutdown: writing mapping in file %s', self.myconfig('mapping'))
            with open(self.myconfig('mapping'), 'w') as fmapping:
                self._mapping.write(fmapping)

    def _map_field(self, content_type, metadata):
        """ Maps a metadata to a field name.

        The mapping depends on the content_type of the document.

        Returns:
            None if *metadata* is not included in the configuration file.
            The field name for this metadata if *metadata* is mapped.
            IGNORE_FIELD if the field is unknown even for Tika.
        """
        # ignore field starting with "unknown" (they are unknown to TIKA)
        if metadata.startswith('unknown'):
            return IGNORE_FIELD
        # replace some characters in the metadata name
        safe_metadata = metadata.replace(':', '-').replace('=', '-')
        # check if a section named content_type exists. If not, create it.
        if not self._mapping.has_section(content_type):
            self.logger().debug('Content-Type not configured: %s', content_type)
            self._mapping.add_section(content_type)
        # get the mapping, if exists
        field = self._mapping[content_type].get(safe_metadata, None)
        if field is None:
            self.logger().debug('Metadata not mapped: %s: %s', content_type, safe_metadata)
            self._mapping[content_type][safe_metadata] = ''
        elif field == '':
            field = None
        return field

    def run(self, path):
        """ Parses a file using Tika.

        A file could be:

        - single, if it has not any embedded files.
        - composite, it is includes several single files (compressed files, PDF, emails...)

        Trying to parse directories is an error. If you want to parse a directory, configure a `DirectoryFilter`
        module before a `TikaParser`.

        Parameters:
            path (str): The absolute path to the file to parse

        Yields:
            A dictionary with the fiels of the parsed file. Keep in mind files can be composite. In this case,
            a dictionary will be yielded for every individual single files.
        """
        tika_server = self.myconfig('tika_server')
        self.logger().debug('Parsing: %s at %s', path, tika_server)
        self.check_params(path, check_path=True, check_path_exists=True)

        if os.path.isfile(path):
            # We cannot parse directories, symbolic links, FIFO files...
            try:
                parsed = self.tika_parse_file(path, tika_server)
                parsed['filepath'] = path
                # NOTE: empty file returns status == 422 and no metadata
                filemetadata = parsed.get('metadata', None)
                status = parsed.get('status', None)

                # NOTE: some corrupt file may break totally Tika<1.19 (status == 500). It seems it is a bug fixed in Tika>=1.20
                if status >= 500:
                    raise base.job.RVTError('Tika returned status {} parsing: "{}". Check you are using Tika >= 1.20'.format(status, path))

                if isinstance(filemetadata, list):
                    return self._post_parse_file_composite(path, filemetadata, status)
                return self._post_parse_file_single(path, filemetadata, status)
            except PermissionError:
                # we allow these errors: thay may occur in special NTFS files such as $Secure
                self.logger().warning('PermissionError while reading "%s"', path)
            except Exception as exc:
                if self.myflag('stop_on_error'):
                    raise
                self.logger().warning('Generic exception parsing "%s": %s', path, exc)
        # default response
        item = self._common_fields(path)
        item.update(dict(
            tika_status=int(self.myconfig('error_status')),
            content='',
            containerid='0'
        ))
        return [item]

    def _post_parse_file_single(self, filepath, filemetadata, status=200):
        """ Gets the output from TIKA, maps fields and remove content if it is too large.

        Args:
            filepath (str): the path to the file
            filemetatada (dict): a dictionary of metadata, as returned by tika
            status (int): the status returned by tika server (200=OK)

        Returns:
            A list with a single item, which contains the file metadata. """
        item = self._common_fields(filepath)
        item.update(dict(
            tika_status=status,
            content='',
            containerid='0'
        ))
        # filemetadata may be None for empty files or after an error in Tika
        if filemetadata is not None:
            # guess content-type
            content_type = self._guess_content_type(filemetadata)
            filemetadata['Content-Type'] = content_type

            # map known fields
            for metadata in filemetadata:
                field = self._map_field(content_type, metadata)
                if field is None:
                    if self.myflag('include_unknown'):
                        item[metadata] = filemetadata[metadata]
                elif field != IGNORE_FIELD:
                    item[field] = filemetadata[metadata]
        # if the content is too large, remove it and set status to 413
        if len(item.get('content', '')) > int(self.myconfig('content_max_size')):
            item['content'] = ''
            item['tika_status'] = 413
        # final checks
        for key in item:
            if isinstance(item[key], list):
                # metadata cannot be list
                item[key] = ','.join(item[key])
        # identifier
        item['_id'] = str(generate_id(item))
        return [item]

    def _post_parse_file_composite(self, filepath, filemetadata, status=200):
        """ Gets the output from TIKA and maps fields.

        Args:
            filepath (str): the path to the composite file
            filemetatada (dict): a list of dictionaries of metadata, as returned by tika
            status (int): the status returned by tika server for the complete composite file (200=OK)

        Returns:
            A list with a any number of item, which contains the metadata of all included files. """
        files = []
        containerid = None
        for metadata in filemetadata:
            doc = self._post_parse_file_single(filepath, metadata, status)

            if containerid is None:
                doc[0]['containerid'] = '0'
                containerid = str(doc[0]['_id'])
            else:
                doc[0]['containerid'] = containerid

            files.extend(doc)
        return files

    def _common_fields(self, path):
        """ Return common fields for a document in a path: path, filename, dirname and extension.
        These values must be utf-8 and relative to the casename  """
        safe_path = path.encode('utf-8', errors='backslashreplace').decode()
        if os.path.isabs(path) or safe_path.startswith('.'):
            relfilepath = base.utils.relative_path(safe_path, self.myconfig('casedir'))
        else:
            relfilepath = safe_path
        return dict(
            path=relfilepath,
            filename=os.path.basename(relfilepath),
            dirname=os.path.dirname(relfilepath),
            extension=os.path.splitext(relfilepath)[1]
        )

    def _guess_content_type(self, filemetadata):
        """ Guess the content type of a metadata """
        try:
            parsed_content_type = mimeparse.parse_mime_type(filemetadata.get('Content-Type', 'application/octet-stream'))
            return '{}/{}'.format(parsed_content_type[0], parsed_content_type[1])
        except Exception:
            return 'application/octet-stream'

    def tika_parse_file(self, filepath, tika_server):
        """ Call a tika server to parse a file.

        Args:
            filepath (str): the path to the composite file
            tike_server (str): the URL to the tika server

        Returns:
            A dictionary ``{status, metadata}.`` If the file cannot be parsed, metadata is not provided.
            If the file is larger than ``file_max_size``, set ``status = 413`` and no metadata is returned.
        """

        if os.path.getsize(filepath) > int(self.myconfig('file_max_size')):
            return dict(status=413)

        headers = {'Accept': 'application/json'}
        with open(filepath, 'rb') as fp:
            resp = requests.put(tika_server + '/rmeta/text', fp, verify=True, headers=headers)
            if not resp:
                # sometimes, tike returns no response with a broken file
                return dict(status=int(self.myconfig('error_status')))
            if resp.status_code != 200:
                self.logger().warning('%s: status=%s', filepath, resp.status_code)

            parsed = dict(status=resp.status_code)
            if resp.content:
                parsed['metadata'] = json.loads(resp.content.decode(self.myconfig('tika_encoding')))
            return parsed


# def dkim_verify(filepath, metadata):
#     """ A hook to verify DKIM signatures for message/rfc822 documents.

#     Parameters:
#         filepath (str): Absolute path to the email message file.
#         metadata (dict): Metadata of the parsed document.

#     Returns:
#         Adds a new field to metadata: *hook_dkim_verify*
#     """
#     import dkim
#     message = None
#     with open(filepath, 'rb') as email_file:
#         message = email_file.read()
#     try:
#         validator = dkim.DKIM(message, logger=None)
#         metadata['hook_dkim_verify'] = validator.verify()
#     except Exception:
#         metadata['hook_dkim_verify'] = False
