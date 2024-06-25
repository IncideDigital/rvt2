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


"""
Modules to mutate data yielded by other modules: converte using specific convertes, remove fields, set fields to default values...
"""

import base.job
import base.utils
import datetime
import os
import ast
import base64
import re
from textwrap import wrap
from plugins.windows.RVT_os_info import CharacterizeWindows
from base.utils import sanitize_ip


# TODO: Do not use dependencies from Windows plugin

# ----------------------------
# MANIPULATE INPUT DATA
# ----------------------------

class SetFields(base.job.BaseModule):
    """ Get data from from_module, set or update some of its fields and yield again.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: mandatory. Data is updated.
        - **yields**: The updated data.

    Configuration:
        - **presets**: A dictionary of fields to be set, unless already set by data yielded by from_module.
        - **fields**: A dictionary of fields to be set. `fields` will be managed as a string template, passing the data yielded by from_module as parameter.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('presets', '')
        self.set_default_config('fields', '')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        presetsStr = self.myconfig('presets')
        fieldsStr = self.myconfig('fields')
        presets = ast.literal_eval(presetsStr) if presetsStr else {}

        for data in self.from_module.run(path):
            newdata = dict(presets) if presets else {}
            newdata.update(data)
            if fieldsStr:
                try:
                    newdata.update(ast.literal_eval(fieldsStr.format(**data)))
                except KeyError as exc:
                    if self.myflag('stop_on_error'):
                        raise base.job.RVTError(exc)
                    self.logger().warning('Key not found: %s', exc)
            yield newdata


class CommonFields(base.job.BaseModule):
    """
        Adds common fields for a document: *path*, *filename*, *dirname*, *extension*, *content_type* and *_id* if they don't exist yet.

        Module description:
            - **path**: not used, passed to *from_module*.
            - **from_module**: mandatory. Copy the information sent by from_module and add fields if they don't exist yet.
            - **yields**: the modified data.

        Configuration:
            - **calculate_id**: if True, calls base.utils.generate_id to generate an identifier in the *_id* field.
            - **filename_stem**: if True, output also the filename without last extension.
            - **disabled**: if True, do not add anything and just yield the result. Useful in configurable module chains
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('generate_id', 'False')
        self.set_default_config('disabled', 'False')
        self.set_default_config('filename_stem', 'False')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        if self.myflag('disabled'):
            for data in self.from_module.run(path):
                yield data
            return []
        for data in self.from_module.run(path):
            newdata = self._common_fields(data.get('path', path))
            # fields already in data take precedence
            newdata.update(data)
            # generate the identifier
            if self.myflag('generate_id'):
                newdata['_id'] = base.utils.generate_id(newdata)
            yield newdata

    def _common_fields(self, path):
        """ Return common fields for a document in a path: path, filename, dirname and extension.
        These values must be utf-8 and relative to the casename  """
        safe_path = path.encode('utf-8', errors='backslashreplace').decode()
        if os.path.isabs(path) or safe_path.startswith('.'):
            relfilepath = base.utils.relative_path(safe_path, self.myconfig('casedir'))
        else:
            relfilepath = safe_path
        cfields = dict(
            path=relfilepath,
            filename=os.path.basename(relfilepath),
            dirname=os.path.dirname(relfilepath),
            extension=os.path.splitext(relfilepath)[1]
        )
        if self.myflag('filename_stem'):
            cfields['filename_stem'] = os.path.basename(relfilepath).split('.')[0]

        content_type = self.myconfig('content_type')
        if content_type:
            cfields['content_type'] = content_type

        return cfields


class AddFields(base.job.BaseModule):
    """ Get data from from_module, add some new fields loaded from configuration and yield again.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: Data is updated.
        - **yields**: The updated data.

    Configuration:
        - **section**: Section from configuration where new values are to be retrieved
        - **fields**: A dictionary of fields to be set. `fields` will be managed as a string template, passing the options from the configuration section as parameter.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('section', 'DEFAULT')
        self.set_default_config('fields', '')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        fieldsStr = self.myconfig('fields')
        conf_section = self.myconfig('section')

        for data in self.from_module.run(path):
            newdata = data
            new_conf_section = conf_section
            # Try to substitute values from incoming data. Usual jobs do not contain '{}'
            if '{' in conf_section:
                try:
                    new_conf_section = conf_section.format(**newdata)
                except Exception as exc:
                    if self.myflag('stop_on_error'):
                        raise base.job.RVTError(exc)
                    self.logger().warning(f'Configuration section not valid: {exc}')
                    yield newdata
                    continue
            # Try to substitute values from fields
            if fieldsStr:
                try:
                    newdata.update(ast.literal_eval(fieldsStr.format(**self.config.config[new_conf_section])))
                except KeyError as exc:
                    if self.myflag('stop_on_error'):
                        raise base.job.RVTError(exc)
                    self.logger().warning(f'Key not found: {exc}')
            yield newdata


class GetFields(base.job.BaseModule):
    """ Get data from from_module, yield only the specified fields.
        It may be also used to set the fields order of appearence.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: Data dict.
        - **yields**: The updated dict data.

    Configuration:
        - **section**: Section from configuration where new values are to be retrieved
        - **fields**: A list of fields to be yielded.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('section', 'DEFAULT')
        self.set_default_config('fields', '')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        fields = self.myarray('fields')
        self.logger().debug(f'Getting fields: {fields}')

        results = self.from_module.run(path)
        if results is not None:
            for data in results:
                yield {k: data.get(k, '') for k in fields}
        else:
            return []


class RenameFields(base.job.BaseModule):
    """ Rename the specified field names with the provided new names.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: Data dict.
        - **yields**: The updated dict data.

    Configuration:
        - **fields**: List of key names to be renamed
        - **new_fields**: List of new key names
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('section', 'DEFAULT')
        self.set_default_config('fields', '')
        self.set_default_config('new_fields', '')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        fields = self.myarray('fields')
        new_fields = self.myarray('new_fields')

        if not fields:
            yield from self.from_module.run(path)
            return []

        if len(fields) != len(new_fields):
            raise base.job.RVTError('`fields` and `new_fields` must have the same number of items. Fields: {}; New fields: {}'.format(fields, new_fields))

        repl = dict(zip(fields, new_fields))
        for data in self.from_module.run(path):
            yield {repl.get(k, k): data[k] for k in data}


class DateFields(base.job.BaseModule):
    """ Converts or creates some fields into ISO date strings.

    Fields might be:

    - An integer, or a string representing an integer: it is a UNIX timestamp.
    - A string: the module will use the *datetutil* package to parse it

    If the field cannot be converted and stop_on_error is not set, the field is popped out from the data.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: mandatory. Get data and udpate fields.
        - **yields**: The modified data.

    Configuration:
        - **fields**: A space separated list of fields to check to convert
        - **new_fields**: A space separated list of new fields to create. If not set, original fields will be converted. If `fields` is set, must have the same number of items as `new_fields`
        - **sep**: Parameter used by datetime.isoformat. One-character separator, placed between the date and time portions of the result
        - **timespec**: Parameter used by datetime.isoformat. Specifies the number of additional components of the time to include
        - **input_timezone**: tzdata/Olsen timezone name of the input dates. Default: `UTC`. Examples: `Europe/Berlin`, `America/New_York`. If `local` is set, timezone will be searched on the Windows registry of the same source and default to UTC if not found. If original input data includes a TZ, it won't be overwritten
        - **output_timezone**: tzdata/Olsen timezone name to set for the output dates. Default: `UTC`. Examples: `Europe/Berlin`, `America/New_York`. If `local` is set, timezone will be searched on the Windows registry of the same source and default to UTC if not found.
        - **hide_tz**: If True, do not output a timezone offset with the result
        - **missing_action**: What to do when date field is not present. One of (IGNORE, SKIP_ANY, SKIP_ALL, REPLACE). Default: IGNORE
                IGNORE: do not transform the date field not found but yield the rest of data
                SKIP_ANY: if one of the date `fields` is not present, skip the data
                SKIP_ALL: if none of the date `fields` are present, skip the data
                REPLACE: Add a new date field with the `on_fail` value
        - **on_fail**: What to do when date field is in a wrong format. One of (EPOCH, NOW, NULL, DELETE). Default: NULL
                EPOCH: substitute the date by the epoch (1970-01-01)
                NOW: substitute the date by the present time of execution
                NULL: return an empty string as the date value
                DELETE: remove the field from the output
        - **dayfirst**: Force this option to interpret 03/07/2022 as July 3rd instead of March 7th. Be careful, since this overrides common ISO notation, and 2022-01-06 will be parsed as 1st of June, not 6th of January.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('fields', 'date_creation')
        self.set_default_config('new_fields', '')
        self.set_default_config('sep', 'T')
        self.set_default_config('timespec', 'auto')
        self.set_default_config('input_timezone', 'UTC')
        self.set_default_config('output_timezone', 'UTC')
        self.set_default_config('hide_tz', False)
        self.set_default_config('missing_action', 'IGNORE')
        self.set_default_config('on_fail', 'NULL')
        self.set_default_config('dayfirst', False)

    def run(self, path=None):
        """ The path will be passed to the mandatory from_module """
        self.check_params(path, check_from_module=True)
        sep = self.myconfig('sep')
        timespec = self.myconfig('timespec')
        hide_tz = self.myflag('hide_tz')
        fields = self.myarray('fields')
        new_fields = self.myarray('new_fields')
        input_timezone = self.myconfig('input_timezone')
        output_timezone = self.myconfig('output_timezone')
        missing_action = self.myconfig('missing_action').upper()
        dayfirst = self.myflag('dayfirst')
        on_fail = self.myconfig('on_fail').upper()
        on_fail_delete = False
        if on_fail == 'DELETE':
            on_fail == 'NULL'
            on_fail_delete = True

        if missing_action not in ['IGNORE', 'SKIP_ANY', 'SKIP_ALL', 'REPLACE']:
            raise base.job.RVTError('`missing_action` must be one of (IGNORE, SKIP_ANY, SKIP_ALL, REPLACE')

        if new_fields and len(new_fields) != len(fields):
            raise base.job.RVTError('`fields` and `new_fields` must have the same number of items. Fields: {}; New fields: {}'.format(fields, new_fields))

        # Get local time from analyzed machine OS settings
        if input_timezone.lower() == 'local' or output_timezone.lower() == 'local':
            # TODO: Consider multiple partitions
            # TODO: consider OS different than Windows
            # TODO: Check what plugins are loaded (Windows, Linux, etc...) and get only those
            local_timezone, offset = CharacterizeWindows(config=self.config).get_timezone()
        if input_timezone.lower() == 'local':
            input_timezone = local_timezone
        if output_timezone.lower() == 'local':
            output_timezone = local_timezone

        for data in self.from_module.run(path):
            found = False
            skip = False
            for i, field in enumerate(fields):
                if skip:
                    continue
                if field not in data:
                    if missing_action in ('IGNORE', 'SKIP_ALL'):
                        continue
                    if missing_action == 'SKIP_ANY':
                        skip = True
                        continue
                if field in data:
                    found = True
                    converted_date = base.utils.date_to_iso(data[field], input_timezone=input_timezone, output_timezone=output_timezone, on_fail=on_fail, dayfirst=dayfirst, sep=sep, timespec=timespec, hide_tz=hide_tz)
                else:  # case missing_action == REPLACE
                    converted_date = base.utils.convert_to_iso(None, sep=sep, timespec=timespec, tz_name=output_timezone, hide_tz=hide_tz, on_fail=on_fail)
                if converted_date and not new_fields:
                    data[field] = converted_date
                elif converted_date and new_fields:
                    data[new_fields[i]] = converted_date
                elif not converted_date and on_fail_delete:
                    data.pop(field)

            if not found and missing_action == 'SKIP_ALL':
                skip = True

            if not skip:
                yield data


class RemoveFields(base.job.BaseModule):
    """ Drops some fields from data.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: mandatory. Get data and remove fields.
        - **yields**: The modified data.

    Configuration:
        - **fields**: List of fields to drop.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('fields', '')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        fields = self.myarray('fields')
        for data in self.from_module.run(path):
            for field in fields:
                # remove the field only if it already exists
                if field in data:
                    data.pop(field)
            yield data


class SplitField(base.job.BaseModule):
    """ Create new fields splitting a provided input field data.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: Data dict.
        - **yields**: The updated dict data.

    Configuration:
        - **field**: List of key names to be renamed
        - **separator**: string separator to split
        - **new_fields**: List of new key names
        - **new_fields_index**: Index of the split to asssign new fields. Starting at 0
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('section', 'DEFAULT')
        self.set_default_config('field', '')
        self.set_default_config('separator', '')
        self.set_default_config('new_fields', '')
        self.set_default_config('new_fields_index', '')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        field = self.myconfig('field')
        separator = self.myconfig('separator')
        new_fields = self.myarray('new_fields')
        new_fields_index = self.myarray('new_fields_index')

        if not field:
            yield from self.from_module.run(path)
            return []

        if not new_fields:
            raise base.job.RVTError('`new_fields` and `new_fields_index` must be provided')

        if len(new_fields) != len(new_fields_index):
            raise base.job.RVTError('`new_fields` and `new_fields_index` must have the same number of items. Fields: {}; Indexes: {}'.format(new_fields, new_fields_index))

        for data in self.from_module.run(path):
            try:
                splitted = data[field].split(separator)
                for i,new_field in zip(new_fields_index,new_fields):
                    data[new_field] = splitted[int(i)]
                yield data
            except:
                yield data


class CoalesceFields(base.job.BaseModule):
    """ Get the first non empty value of a list of fields and create a new single field.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: Data dict.
        - **yields**: The updated dict data.

    Configuration:
        - **fields**: List of key names to be coalesced
        - **new_field**: Name of the new field to create. Can be one of the previous, but it will be overwritten
        - **default_fill**: Value to fill with if all `fields` values are empty
        - **remove**: Do not yield original fields to coalesce, only the new one
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('section', 'DEFAULT')
        self.set_default_config('fields', '')
        self.set_default_config('new_field', 'CoalesceField')
        self.set_default_config('default_fill', "")
        self.set_default_config('remove', False)

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        fields = self.myarray('fields')
        new_field = self.myconfig('new_field')
        default = self.myconfig('default_fill')
        remove = self.myflag('remove')

        if not fields:
            yield from self.from_module.run(path)
            return []

        fields_to_remove = set(fields) - set([new_field])
        for data in self.from_module.run(path):
            non_empty_values = [data.get(k, default) for k in fields if data.get(k, None)]
            data[new_field] = default if not non_empty_values else non_empty_values[0]
            if remove:
                [data.pop(i, None) for i in fields_to_remove]
            yield data


class SpaceText(base.job.BaseModule):
    """ Add spaces to text field every `steps` characters, so it is easy to read

    Configuration:
        - **fields**: Space separated keys to clean the hash
        - **steps**: Number of caharacters per chunck. If there is only one, it will be used for all fields. Otherwise, the number of items must be the same as fields to convert
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('fields', '')
        self.set_default_config('steps', '20')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        fields = self.myarray('fields')

        if not fields:
            yield from self.from_module.run(path)
            return []

        steps = self.myarray('steps')
        try:
            steps = [int(step) for step in steps]
        except ValueError:
            raise base.job.RVTError('`steps` must contain integers. Steps: {}'.format(steps))
        if len(steps) == 1:
            steps = [steps[0]] * len(fields)
        if len(fields) != len(steps):
            raise base.job.RVTError('`fields` and `steps` must have the same number of items. Fields: {}; Steps: {}'.format(fields, steps))

        for data in self.from_module.run(path):
            for i, field in enumerate(fields):
                if field in data:
                    data[field] = ' '.join(wrap(data[field], steps[i]))
            yield data


class DecodeFields(base.job.BaseModule):
    """ Decode input fields binary data.

    Configuration:
        - **fields**: Space separated keys to decode
        - **new_fields**: A space separated list of new fields to create. If not set, original fields will be converted. If `fields` is set, must have the same number of items as `new_fields`
        - **input_encoding**: Original encoding to decode. Options: [hexadecimal, binary, base64]. Assumeing all 'fields' provided have the same encoding. Run this module as many times as necessary if different encodings are present
        - **output_encoding**: Desired output encoding
    """
    # TODO: more encodings

    def read_config(self):
        super().read_config()
        self.set_default_config('fields', '')
        self.set_default_config('new_fields', '')
        self.set_default_config('encoding', 'hexadecimal')
        self.set_default_config('decoding', 'UTF-8')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        fields = self.myarray('fields')
        new_fields = self.myarray('new_fields')
        if new_fields and len(new_fields) != len(fields):
            raise base.job.RVTError('`fields` and `new_fields` must have the same number of items. Fields: {}; New fields: {}'.format(fields, new_fields))

        if not fields:
            yield from self.from_module.run(path)
            return []

        decoding_functions = {'hexadecimal': self._hex,
                              'binary': self._binary,
                              'base64': self._base64}
        input_encoding = self.myconfig('encoding')
        output_encoding = self.myconfig('decoding')
        if input_encoding.lower() not in decoding_functions:
            self.logger().warning(f'Provided encoding {input_encoding} not supported. Valid options: {decoding_functions.keys()}')
            yield from self.from_module.run(path)
            return []

        for data in self.from_module.run(path):
            for i, field in enumerate(fields):
                if field in data:
                    new_value = ''
                    try:
                        new_value = decoding_functions[input_encoding](data[field], output_encoding)
                    except Exception as exc:
                        self.logger().debug(exc)
                    # Create a new field and remove the previous one even if no substitution has been made
                    if new_fields:
                        data[new_fields[i]] = new_value if new_value else data[field]
                        data.pop(field)
                    else:
                        data[field] = new_value if new_value else data[field]
            yield data

    def _hex(self, data, output_encoding):
        return bytearray.fromhex(data).decode(encoding=output_encoding)

    def _binary(self, data, output_encoding):
        n = int(data, 2)
        return n.to_bytes((n.bit_length() + 7) // 8, 'big').decode(encoding=output_encoding) or '\0'

    def _base64(self, data, output_encoding):
        return base64.b64decode(data).decode(encoding=output_encoding)


class AdaptIpFormat(base.job.BaseModule):
    """ Adapt IP fields to Elastic IPv4 or IPv6 addresses format (see https://www.elastic.co/guide/en/elasticsearch/reference/current/ip.html)

    Configuration:
        - **fields**: Space separated keys to adapt to IP format
        - **port_fields**: Space separated names for the new port field if IP field contains a port. Must have the same number of items as `fields`. By default, substitute "ip" or "address" by "port" on each of the `fields`
        - **ignore_port**: If True, ignore the treatment of ports when processing an IP
        - **null_value**: Output value in case no match found. Common options: (NONE, EMPTY, DASH). Default=None
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('fields', '')
        self.set_default_config('port_fields', '')
        self.set_default_config('ignore_port', False)
        self.set_default_config('null_value', 'NONE')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        fields = self.myarray('fields')
        port_fields = self.myarray('port_fields')
        ignore_port = self.myconfig('ignore_port')
        null_value = self.myconfig('null_value')
        null_values = {"NONE": None, "EMPTY": "", "DASH": "-"}

        if not fields:
            yield from self.from_module.run(path)
            return []

        if port_fields and (len(fields) != len(port_fields)):
            raise base.job.RVTError('`fields` and `port_fields` must have the same number of items. Fields: {}; Port fields: {}'.format(fields, port_fields))
        if not port_fields:
            port_fields = fields.copy()
            if not ignore_port:
                for name, replacement in zip(['IP', 'Ip', 'ip', 'Address', 'address'],['Port', 'Port', 'port', 'Port', 'port']):
                    port_fields = [f.replace(name,replacement) for f in port_fields]

        relation = list(zip(fields, port_fields))
        for data in self.from_module.run(path):
            for ip_field, port_field in relation:
                if ip_field not in data:
                    continue
                ip, port = sanitize_ip(data[ip_field])
                data[ip_field] = ip if ip else null_values.get(null_value.upper(), null_value)
                if port and not ignore_port:
                    data[port_field] = port
            yield data


class CalculateHash(base.job.BaseModule):
    """ Add a new field 'hash_field' to the input data by calculating the hash of a file provided in a selected input 'path_field'.

    Module description:
        - **from_module**: Data dict.
        - **yields**: The updated dict data.

    Configuration:
        - **path_field**: Name of the field containing the file path to calculate the hash from.
        - **hash_field**: Name of the new calculated field.
        - **algorithm**: Hash algorithm to use. Default: sha256.
        - **from_dir**: Base directory to use if provided path is relative.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('algorithm', 'sha256')
        self.set_default_config('path_field', 'path')
        self.set_default_config('hash_field', 'hash')
        self.set_default_config('from_dir', '')

    def run(self, path=None):
        algorithm = self.myconfig('algorithm').lower()
        path_field = self.myconfig('path_field')
        hash_field = self.myconfig('hash_field')
        from_dir = self.myconfig('from_dir')

        for data in self.from_module.run(path):
            path = os.path.join(from_dir, data.get(path_field, ''))
            if os.path.isfile(path):
                data[hash_field] = base.utils.get_filehash(path, algorithm=algorithm)
            else:
                data[hash_field] = ''
            yield data


# ----------------------------
# FILTER INPUT DATA
# ----------------------------

class SkipResults(base.job.BaseModule):
    """ Skip data if specified fields are empty. Empty definition includes `-` strings.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: mandatory. Get data and remove fields.
        - **yields**: The original data if criteria is not met, or nothing.

    Configuration:
        - **fields**: List of fields to check for emptyness.
        - **condition**: **all** (all provided fields must be empty to skip data) or **any** (if any provided field is empty, skip data)
        - **fields_not_present: what to do if any of the provided fields are not present in data. Availabale options are **skip** (default) or **keep**
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('fields', '')
        self.set_default_config('condition', 'all')
        self.set_default_config('fields_not_present', 'skip')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        fields = self.myarray('fields')
        condition = self.myconfig('condition').lower()
        not_present = self.myconfig('fields_not_present').lower()

        for data in self.from_module.run(path):
            if not fields:
                semicolon_copy = None
            else:
                semicolon_copy = [v if v!="-" else None for k,v in data.items() if k in fields]
            if not semicolon_copy:
                if not_present != "keep":  # Skip data if fields not present
                    continue
                else:
                    yield data
                    continue
            if condition == 'any' and all(semicolon_copy):
                yield data
            elif condition != 'any' and any(semicolon_copy):  # when condition not in ['all', 'any'], assume it is 'all'
                yield data


class FilterData(base.job.BaseModule):
    """ Keep only input data where fields meet certain 'conditions'.
        All conditions are joined using either 'or' or 'and' operators.
        If complex conditions are required, run this job mutliple times.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: mandatory. Get data from here.
        - **yields**: The original data if criteria is met, or nothing.

    Configuration:
        - **conditions**: list of tuples where the first element is the field name and the second element is the data to compare against. Ex: [("field1","v1"),("field2","v2")]
        - **is_regex**: if True, compare using regex. Otherwise, use and exact match. Default: False
        - **operator**: operator to apply to every item in 'conditions'. Options: 'and' or 'or'.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('conditions', 'None')
        self.set_default_config('operator', 'or')
        self.set_default_config('is_regex', False)

    def run(self, path=None):
        self.check_params(path, check_from_module=True)

        # If no conditions are set, this module is transparent
        if not self.myconfig('conditions'):
            yield from self.from_module.run(path)
            return
        try:
            events = ast.literal_eval(self.myconfig('conditions'))
        except Exception as exc:
            self.logger().warning(f"Problems on parsing input parameter 'conditions': {exc}")
            yield from self.from_module.run(path)
            return

        op = self.myconfig('operator').lower()
        if op not in ['or', 'and']:
            self.logger().warning(f"Accepted values for parameter 'operator' are ('or', 'and'). Provided value {op} not accepted.")
            yield from self.from_module.run(path)
            return

        is_regex = self.myflag('is_regex')
        if is_regex and events:
            events = [(k, re.compile(v, re.I)) for k,v in events]

        for data in self.from_module.run(path):
            if not events:
                yield data
                continue
            if op == 'or':
                for field, reference in events:
                    if field not in data.keys():
                        continue
                    if (not is_regex and data[field] == reference) or (is_regex and reference.search(data[field])):
                        yield data
                        break
            if op == 'and':
                discard = False
                for field, reference in events:
                    if (field not in data.keys()) or (not is_regex and data[field] != reference) or (is_regex and not reference.search(data[field])):
                        discard = True
                        break
                if not discard:
                    yield data


class DateRange(base.job.BaseModule):
    """ Keep only input data within the date range between 'start' and 'end'.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: mandatory. Get data from here.
        - **yields**: The original data if criteria is met, or nothing.

    Configuration:
        - **field**: Name of the field containing the dates to filter.
        - **start**: Starting date. Although it accepts many date formats, try to conform to the following notation: 'YYYY-mm-ddTHH:MM:SS'. Set 'dayfirst' paramenter if using notation such as 24/03/2024.
        - **end**: Ending date. If only 'start' is set, 'end' will default to the current execution time.
        - **action_if_missing**: What to do with data when date field is not present. One of (KEEP, SKIP). Default: SKIP.
        - **on_fail**: What to do when date field is in a wrong format and 'action_if_missing' is KEEP. One of (EPOCH, NOW, NULL). Default: NULL.
                EPOCH: substitute the date by the epoch (1970-01-01)
                NOW: substitute the date by the present time of execution
                NULL: return an empty string as the date value
        - **dayfirst**: Force this option to interpret 03/07/2022 as July 3rd instead of March 7th. Be careful, since this overrides common ISO notation, and 2022-01-06 will be parsed as 1st of June, not 6th of January.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('field', '')
        self.set_default_config('start', None)
        self.set_default_config('end', None)
        self.set_default_config('action_if_missing', 'SKIP')
        self.set_default_config('on_fail', 'NULL')
        self.set_default_config('dayfirst', False)

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        field = self.myconfig('field')
        start = self.myconfig('start')
        end = self.myconfig('end')
        missing_action = self.myconfig('action_if_missing').upper()
        dayfirst = self.myflag('dayfirst')
        on_fail = self.myconfig('on_fail').upper()

        if missing_action not in ['KEEP', 'SKIP']:
            raise base.job.RVTError(f'Wrong `action_if_missing` parameter provided ({missing_action}). It must be one of (KEEP, SKIP)')

        if not start and not end:   # No filter is applied. Module is transparent
            yield from self.from_module.run(path)
            return []

        if not start:
            start = datetime.datetime.fromtimestamp(0)
        else:
            start = base.utils.to_localized_date(start, on_fail=on_fail, dayfirst=dayfirst)
        if not end:
            end = datetime.datetime.now(datetime.timezone.utc)
        else:
            end = base.utils.to_localized_date(end, on_fail=on_fail, dayfirst=dayfirst)

        if not start and not end:   # Check again in case date parsing was incorrect
            yield from self.from_module.run(path)
            return []

        self.logger().debug(f'Filtering data by field "{field}" between {start} and {end}')
        for data in self.from_module.run(path):
            if field not in data:
                if missing_action == 'KEEP':
                    yield data
                continue
            timestamp = base.utils.to_localized_date(data.get(field, None), on_fail=on_fail, dayfirst=dayfirst)
            if not timestamp:
                continue
            if timestamp > start and timestamp < end:
                yield data


# ----------------------------
# GLOBAL MUTATIONS
# ----------------------------

class ForEach(base.job.BaseModule):
    """ Runs a job for each data yielded by from_module. The data is passed as params of the job.

    Module description:
        - **path**: not used, passed to *from_module*.
        - **from_module**: mandatory. The data is passed to ``run_job`` as its extra_config parameter.
        - **yields**: None

    Configuration:
        - **run_job**: The name of he job to run
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('run_job', '')

    def run(self, path=None):
        self.check_params(self, check_from_module=True)

        run_job = self.myconfig('run_job')
        if not run_job:
            raise base.job.RVTError('run_job cannot be empty')

        for data in self.from_module.run(path):
            new_path = data.get('path', None)
            list(base.job.run_job(self.config, run_job, path=new_path, extra_config=data))
        return []


class MirrorOptions(base.job.BaseModule):
    """ Return the value of the local options.

        Configuration:
        - **include_section**: If true, include also the configuration in the section.
        - **relative_path**: If true, return the path relative to casedir.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('include_section', 'False')
        self.set_default_config('relative_path', 'True')

    def run(self, path=None):
        if self.myflag('relative_path'):
            params = dict(path=base.utils.relative_path(path, self.myconfig('casedir')))
        else:
            params = dict(path=path)
        if self.local_config:
            params.update(self.local_config)
        if self.myflag('include_section') and hasattr(self, 'section') and hasattr(self, 'config'):
            if self.config.has_section(self.section):
                for option in self.config.options(self.section):
                    params[option] = self.config.get(self.section, option)
        # Remove useless parameters
        params.pop('logger_name')
        params.pop('include_section')
        return [params]


class FeedJobsParameters(base.job.BaseModule):
    """ The module gets a list of sections/jobs names, and runs to *from_module* all value options for every section/job.

        Configuration:
        - **sections**: List of sections/jobs to load options from.
        - **include_section**: If true, include also the configuration in the section.
        - **relative_path**: If true, return the path relative to casedir.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('sections', None)
        self.set_default_config('include_section', 'False')
        self.set_default_config('relative_path', 'True')

    def run(self, path=None):
        if path:
            if self.myflag('relative_path'):
                params = dict(path=base.utils.relative_path(path, self.myconfig('casedir')))
            else:
                params = dict(path=path)
        else:
            params=dict()

        if self.local_config:
            params.update(self.local_config)
        if self.myflag('include_section') and hasattr(self, 'section') and hasattr(self, 'config'):
            if self.config.has_section(self.section):
                for option in self.config.options(self.section):
                    params[option] = self.config.get(self.section, option)

        # Remove useless parameters
        params.pop('logger_name', None)
        params.pop('include_section', None)
        params.pop('sections', None)

        sections = self.myarray('sections')
        for module_section in sections:
            self.logger().debug(f'Yielding parameters for module {module_section}')
            if self.config.has_section(module_section):
                final_params = params.copy()
                for option in self.config.options(module_section):
                    final_params[option] = self.config.get(module_section, option)
                yield final_params

        return []


class Collapse(base.job.BaseModule):
    """ Collapse different documents sent by from_module with a common field into just one document.

    Warning: the collapse may take many time and memory

    Configuration section:
        - **field**: collapse documents using this field name as the common field.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('field', '_id')

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        field = self.myconfig('field')
        collapsed_data = {}
        for data in self.from_module.run(path):
            # data without the common field is yielded immediately
            data_field = data.get(field, None)
            # data with the common field is saved in memory. New data updates old data
            if not data_field:
                yield data
            if data_field in collapsed_data:
                collapsed_data[data_field].update(data)
            else:
                collapsed_data[data_field] = data
        # yield all data in memory
        for data in collapsed_data.keys():
            yield collapsed_data[data]


class SortResults(base.job.BaseModule):
    """ Sort the data from from_module, and yields results again.
    Take note that this operation loses some benefits of using generators,
    since sort operation must know all the items and the generator is consumed

    Warning: Sorting is not safe when sorting keys values are not strings

    Configuration:
        - **fields**: Space separated keys to sort by
        - **reverse**: Sort order
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('fields', '')
        self.set_default_config('reverse', False)

    def run(self, path=None):
        self.check_params(path, check_from_module=True)
        fields = self.myarray('fields')
        reverse = self.myflag('reverse')

        if not fields:
            yield from self.from_module.run(path)
        else:
            self.logger().debug(f'Sorting by fields "{fields}" results from path "{path}"')
            yield from sorted(self.from_module.run(path), key=safe_string_itemgetter(*fields), reverse=reverse)


def safe_string_itemgetter(*items):
    """ Variation from operator itemgetter that helps to sort missing keys at first place"""
    if len(items) == 1:
        item = items[0]

        def g(obj):
            return obj.get(item, '')
    else:
        def g(obj):
            return tuple(obj.get(item, '') for item in items)
    return g
