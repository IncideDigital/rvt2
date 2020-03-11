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


""" Modules to export, parse and index PST and OST files using the external utility pffexport. """

import os.path
import re
import subprocess

from base.utils import generate_id
from plugins.common.RVT_files import GetFiles
from base.commands import run_command
import base.utils
import dateutil.parser
import base.job
import email
from tqdm import tqdm

__maintainer__ = 'Juanvi Vera'


# ##################### Utility functions

def decodeEmailHeader(header, errors='replace'):
    """ Decodes an international header (as returned by the standard email library) into unicode.

    Parameters:
        :header (str): The value of the header, as returned by the standard email library. It may content different parts with different encodings
        :errors (str): After an encoding error, you can be 'strict', or 'replace' or 'ignore'

    >>> decodeEmailHeader('=?utf-8?b?WW91J3JlIFNpbXBseSB0aGUgQmVzdCEgc3V6w6BubmUg77uH77uH77uH77uH77uH?=')
    "You're Simply the Best! suzànne ﻇﻇﻇﻇﻇ"
    >>> decodeEmailHeader('=?utf-8?b?SMOpY3RvciBGZXJuw6FuZGV6?= <hector@fernandez>')
    'Héctor Fernández <hector@fernandez>'
    >>> decodeEmailHeader(None)
    >>> decodeEmailHeader('')
    """
    # if no header is provided, returns None
    if not header:
        return None
    values = []
    for h in email.header.decode_header(header):
        if not h[1]:
            # this part of the header has no encoding: assume utf and continue
            if type(h[0]) == str:
                # the header has a single part
                values.append(h[0])
            else:
                # the header have several parts
                values.append(h[0].decode(errors=errors))
        else:
            # this part of the header has encoding: convert to unicode managing errors
            try:
                values.append(h[0].decode(h[1], errors=errors))
            except LookupError:
                # the encoding was not found: revert to unicode
                values.append(h[0].decode(errors=errors))
    # finally, remove end of lines
    return (''.join(values)).replace('\n', '').strip()


def decodeEmailDateHeader(header, ignore_errors=True):
    """ Decodes a header (as returned by the standard email library) assuming it is a date.

    Parameters:
        :ignore_errors: If True, returns None if the date cannot be parsed. Else, raise ValueError.

    >>> decodeEmailDateHeader('Mon, 23 Aug 2004 11:40:10 -0400')
    '2004-08-23T11:40:10-04:00'
    >>> decodeEmailDateHeader('nanana')
    >>> decodeEmailDateHeader('nanana', ignore_errors=False)
    Traceback (most recent call last):
        ...
    ValueError: ('Unknown string format:', 'nanana')
    >>> decodeEmailDateHeader(None)
    >>> decodeEmailDateHeader('')

    """
    if not header:
        return None
    header = decodeEmailHeader(header)
    try:
        return dateutil.parser.parse(header).isoformat()
    except ValueError:
        if ignore_errors:
            return None
        raise


def readMessageFile(filename, stop_on_empty_line=True, encoding='utf-8', errors='replace'):
    """ Reads an email header file.

    This funcion is a simplified version of `email.message_from_file()`, but headers can also include spaces.
    Body, if present is ignored. If `filename` does not exists, returns an empty dictionary.
    Header names will be saved in lower case.

    Parameters:
        :filename (str): The name of the file to open
        :stop_on_empty_line (boolean): If True, stop processing headers after an empty line.
        :encoding (str): The encoding of filename.
        :errors (str): After an encoding error, you can be 'strict', or 'replace' or 'ignore'
    """
    data = {}
    if not os.path.isfile(filename):
        return data
    with open(filename, encoding=encoding, errors=errors) as f:
        last_key = None
        for line in f:
            line = line.strip()
            if not line and stop_on_empty_line:
                break
            if ':' in line:
                key, value = line.split(':', 1)
                last_key = key.strip().lower()
                data[last_key] = value.strip()
            else:
                if last_key is not None:
                    data[last_key] = '{}\n{}'.format(data[last_key], line.strip())
    return data


# ################ Main modules

class ExportPst(base.job.BaseModule):
    """ Export all pst and ost files from a mounted image using pffexport. This modules depends on the common plugin.

    Configuration:
        - **pffexport**: route to the pffexport binary
        - **outdir**: outputs to this directory
        - **delete_exists**: if True, delete the outout directory if it already exists

    Returns: a list of {filename, outdir, index}
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('outdir', self.config.get('plugins.common', 'mailsdir'))
        self.set_default_config('pffexport', 'pffexport')
        self.set_default_config('delete_exists', 'True')

    def run(self, path=None):
        """ Export all pst and ost files in a mounted image. Path is ignored. """
        pffexport = self.myconfig('pffexport')

        outdir = self.myconfig('outdir')
        base.utils.check_directory(outdir, create=True)

        pst_files = GetFiles(self.config, vss=self.myflag("vss")).search(r"\.(pst|ost|nst)$")
        index = 0

        for pst_file in tqdm(pst_files, desc=self.section, disable=self.myflag('progress.disable')):
            index += 1
            # save metadata
            yield dict(filename=pst_file, outdir="pff-{}".format(index), index=index)
            try:
                if not os.path.exists(os.path.join(self.myconfig('casedir'), pst_file)):
                    self.logger().warning('File %s does not exist', pst_file)
                    continue
                out_path = os.path.join(outdir, "pff-{}".format(index))
                self.logger().debug("Exporting %s to %s", pst_file, out_path)
                # check if the output directory exist
                for directory in ['{}.export'.format(out_path), '{}.recovered'.format(out_path)]:
                    if base.utils.check_directory(directory):
                        if self.myflag('delete_exists'):
                            base.utils.check_directory(directory, delete_exists=True)
                        else:
                            continue
                run_command([pffexport, '-f', 'text', '-m', 'all', '-q', '-t', out_path, pst_file], stderr=subprocess.DEVNULL,
                            from_dir=self.myconfig('casedir'))
            except Exception as exc:
                if self.myflag('stop_on_error'):
                    self.logger().error('Exception %s: %s', type(exc).__name__, exc)
                    raise base.job.RVTError(exc)
                else:
                    self.logger().warning('Exception %s: %s', type(exc).__name__, exc)


class MailParser(base.job.BaseModule):
    """
    Parses the exported pst files returned by from_module. Use the output from ExportPST as from_module.

    Parameters:
        path (str): the path to pass to from_module, which must yield, for each PST or OST file, a dictionary:
            `{outdir:"path to the output directory of the export", filename:"filaname of the PST or OST file"}`.

    Configuration:
        - **exportdir**: the export main directory.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('exportdir', os.path.join(self.myconfig('outputdir'), 'mail'))

    def run(self, path=''):
        self.check_params(path, check_from_module=True)

        pstfiles = list(self.from_module.run(path))
        for pstfile in tqdm(pstfiles, desc=self.section, disable=self.myflag('progress.disable')):
            outputpstfile = os.path.join(self.myconfig('exportdir'), '{}.export'.format(pstfile['outdir']))
            if not os.path.isdir(outputpstfile):
                continue
            parsePffObject = PffExportParseObject(self.config)
            outputpstfile = os.path.join(self.myconfig('exportdir'), '{}.export'.format(pstfile['outdir']))
            with tqdm(total=int(sum([len(folder) for r, folder, file in os.walk(outputpstfile)])), desc='indexing {}'.format(pstfile['outdir'])) as pbar:
                for root, dirs, files in os.walk(outputpstfile):
                    for dirpath in dirs:
                        pbar.update(1)
                        for m in parsePffObject.run(os.path.join(root, dirpath)):
                            m['pst_filename'] = pstfile['filename']
                            yield m


class MailboxCSV(base.job.BaseModule):
    """
    Generates a dictionary with information about messages in a chain. Use a (probably forked) MailParser as from_module.
    """

    def run(self, path):
        for fileinfo in self.from_module.run(path):
            if fileinfo.get('content_type', '') == 'pst/Message':
                res = dict()
                res["message"] = fileinfo['dirname']
                res['client_submit_time'] = fileinfo.get('email_submit_time', '')
                res['delivery_time'] = fileinfo.get('email_delivery_time', '')
                res['creation_time'] = fileinfo.get('creation_time', '')
                res['modification_time'] = fileinfo.get('modification_time', '')
                res['subject'] = fileinfo.get('email_subject', '')
                res['flags'] = fileinfo.get('email_flags', '')
                res['guid'] = fileinfo.get('email_guid', '')
                res['send_or_received'] = fileinfo.get('email_send_or_received', '')
                res['from'] = fileinfo.get('email_from', '')
                res['to'] = ''
                res['cc'] = ''
                res['bcc'] = ''
                if 'email_recipients' in fileinfo.keys():
                    recipients = fileinfo['email_recipients']
                    for k in recipients:
                        recipient_type = k['recipient_type']
                        if recipient_type in ('to', 'cc', 'bcc'):
                            res[recipient_type] = "{};{} <{}>".format(res.get(recipient_type, ''), k['display_name'], k['email_address'])
                        else:
                            self.logger().warning('Message {} has recipient_type {} with email address {}'.format(res['message'], recipient_type, k['email_address']))
                res['messageid'] = fileinfo.get('email_messageid', '')
                res['x_originating_ip'] = fileinfo.get('email_x_originating_ip', '')
                res['email_references'] = fileinfo.get('email_references', '')
                res['conversation_topic'] = fileinfo.get('email_conversation_topic', '')
                yield res


# ##################################### Utility modules. You can use these modules to parse a single object instead of the whole PST file.

class PffExportParseObject(base.job.BaseModule):
    """
    Parses an object (Message, Meeting, Contact, Task or Appointment) in a directory exported by pffexport.

    Parameters:
        path (str): the path to directory of the object. It must be a directory.

    Yields:
        Information about the object and its attachments.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tika_parser = base.job.load_module(self.config, 'indexer.tikaparser.TikaParser')

    def run(self, path, containerid=None):
        self.check_params(path, check_path_exists=True)
        if not os.path.isdir(path):
            raise base.job.RVTError('The path must be a directory: {}'.format(path))
        filetype_modules = {
            'Message': PffExportParseMessage(self.config),
            'Contact': PffExportParseContact(self.config),
            'Appointment': PffExportParseAppointment(self.config),
            'Meeting': PffExportParseMeeting(self.config),
            'Task': PffExportParseTask(self.config)
        }
        ft = re.match(r"(\D+)\d+", os.path.basename(path))
        if ft and ft.group(1) in filetype_modules.keys():
            # parse the main object
            rootid = None
            for m in filetype_modules[ft.group(1)].run(path, containerid):
                if not containerid and not rootid:
                    rootid = m.get('_id')
                yield m
            # parse attachments inside the object
            if "Attachments" in os.listdir(path):
                for attachment in self._parse_attachments(path, rootid):
                    yield attachment

    def _parse_attachments(self, message_path, containerid=None):
        attachpath = os.path.join(message_path, "Attachments")
        for f in os.listdir(attachpath):
            if os.path.isfile(os.path.join(attachpath, f)):
                # the path in f is a file and not a directory: parse the file
                container_name = os.path.basename(message_path)
                filemetadata = self.tika_parser.run(os.path.join(attachpath, f))[0]
                # change the embedded path of these files, to point to the mail container and not the attachment
                filemetadata['embedded_path'] = os.path.join("Attachments", filemetadata['filename'])
                filemetadata['dirname'] = base.utils.relative_path(message_path, self.myconfig('casedir'))
                filemetadata['path'] = os.path.join(filemetadata['dirname'], 'index.html')
                # if the attachment is an image, create a preview
                if filemetadata.get('category', '') == 'image':
                    filemetadata['preview'] = base.utils.relative_path(os.path.join(attachpath, f), self.myconfig('casedir'))
                filemetadata['filename'] = container_name
                filemetadata['containerid'] = containerid
                yield filemetadata
            # the path in the attachment is a directory: parse it (it might be an embedded Message, Meeting or Task)
            else:
                for attachment in self.run(os.path.join(attachpath, f), containerid):
                    yield attachment

    def _setContainerID(self, d, containerid=None):
        if not containerid:
            d['_id'] = str(generate_id(d))
            d['containerid'] = 0
        else:
            d['_id'] = str(generate_id(d))
            d['containerid'] = containerid
        return d['_id']

    def _getInternetHeaders(self, filename):
        """ Read internet headers from a filename """
        msg = readMessageFile(filename)
        return {
            'email_subject': decodeEmailHeader(msg.get('subject', None)),
            'email_from': decodeEmailHeader(msg.get('from', None)),
            'email_to': decodeEmailHeader(msg.get('to', None)),
            'email_cc': decodeEmailHeader(msg.get('cc', None)),
            'email_bcc': decodeEmailHeader(msg.get('bcc', None)),
            'creation_time': decodeEmailHeader(msg.get('date', None)),
            'email_x_originating_ip': decodeEmailHeader(msg.get('x-originating-ip', None)),
            'email_messageid': decodeEmailHeader(msg.get('message-id', None)),
            'email_references': decodeEmailHeader(msg.get('references', None))
        }

    def _getOutHeaders(self, filename):
        """ Read outlook headers from a filename """
        msg = readMessageFile(filename, stop_on_empty_line=False)
        data = {
            'email_submit_time': decodeEmailDateHeader(msg.get('client submit time', None)),
            'email_delivery_time': decodeEmailDateHeader(msg.get('delivery time', None)),
            'creation_time': decodeEmailDateHeader(msg.get('creation time', None)),
            'modification_time': decodeEmailDateHeader(msg.get('modification time', None)),
            'email_flags': decodeEmailHeader(msg.get('flags', None)),
            'size': decodeEmailHeader(msg.get('size', None)),
            'email_conversation_topic': decodeEmailHeader(msg.get('conversation topic', None))
        }
        sn = decodeEmailHeader(msg.get('sender name', None))
        sea = decodeEmailHeader(msg.get('sender email address', None))
        if sn:
            if sea:
                data['email_from'] = "{} ({})".format(sn, sea)
            else:
                data['email_from'] = sn

        subject = decodeEmailHeader(msg.get('subject', None))
        if subject:
            # if a subject is present in the properties, include it. It MIGHT overwrite the subject from other files, such as InternetHeaders
            data['email_subject'] = subject
        return data

    def _getRecipients(self, filename, length=5):
        """ Read recipients from a filename """
        # TODO: check if this funcion can use readMessageFile()
        recipientsinfo = {}
        if os.path.isfile(filename):
            with open(filename, 'r') as f:
                recipientsinfo['email_recipients'] = []
                rec = {}
                for content in f:
                    if content == '\n':
                        recipientsinfo['email_recipients'].append(rec)
                        rec = {}
                        continue
                    try:
                        field, value = content.split(":")
                    except Exception:
                        aux = content.split(":")
                        field = aux[0]
                        value = ":".join(aux[1:])
                    rec[self._sanitize(field)] = value.lstrip().rstrip().lower()
        return recipientsinfo

    def _getConversationIndex(self, filename):
        """ Read GUID from a filename """
        conversationinfo = {}
        msg = readMessageFile(filename, stop_on_empty_line=False)
        conversationinfo['email_guid'] = msg.get('guid', '').replace('\n', '')
        return conversationinfo

    def _sanitize(self, item):
        return item.lower().replace(' ', '_').replace('-', '_')


class PffExportParseMessage(PffExportParseObject):
    """
    Parses a Message in a directory exported by pffexport.

    Parameters:
        path (str): the path to directory of the Message. It must be a directory.

    Yields:
        Information about the Message but not its attachments.
    """
    def run(self, path, containerid=None):
        info = {}
        # parse the Message.html or Message.rtf file in the directory: this is the content
        for f in os.listdir(path):
            if f.startswith("Message"):
                info = self.tika_parser.run(os.path.join(path, f))[0]
                break
        info['content_type'] = "pst/Message"
        info["category"] = "email"
        intHeaders = os.path.join(path, "InternetHeaders.txt")
        if os.path.isfile(intHeaders):
            info.update(self._getInternetHeaders(intHeaders))
            info["email_send_or_received"] = "R"
        else:
            info["email_send_or_received"] = "S"
        info.update(self._getOutHeaders(os.path.join(path, "OutlookHeaders.txt")))
        if 'Unsent' in info.get('email_flags', ''):
            info["email_send_or_received"] = "U"
        info.update(self._getRecipients(os.path.join(path, "Recipients.txt")))
        try:
            info.update(self._getConversationIndex(os.path.join(path, "ConversationIndex.txt")))
        except Exception:
            info['email_guid'] = ""
        info['dirname'] = base.utils.relative_path(path, self.myconfig('casedir'))
        info['path'] = os.path.join(info['dirname'], 'index.html')
        info['filename'] = os.path.basename(path)
        containerid = self._setContainerID(info, containerid)
        yield info


class PffExportParseContact(PffExportParseObject):
    """
    Parses a Contact in a directory exported by pffexport.

    Parameters:
        path (str): the path to directory of the Message. It must be a directory.

    Yields:
        Information about the Contact but not its attachments.
    """
    def run(self, path, containerid=None):
        info = {}
        info["content_type"] = "pst/Contact"
        info["category"] = "email"
        info["extension"] = None
        contactinfo = readMessageFile(os.path.join(path, 'Contact.txt'), stop_on_empty_line=False)
        info['content'] = contactinfo.get('file under', None)
        info['contact_company'] = contactinfo.get('company name', None)
        info['contact_address'] = contactinfo.get('email address 1', None)
        info['contact_address_2'] = contactinfo.get('email address 2', None)
        info['contact_phone'] = contactinfo.get('mobile phone number', None)
        info['contact_phone_2'] = contactinfo.get('home phone number', None)
        info['creation_time'] = decodeEmailDateHeader(contactinfo.get('creation time', None))
        info['modification_time'] = decodeEmailDateHeader(contactinfo.get('modification time', None))
        info['dirname'] = base.utils.relative_path(path, self.myconfig('casedir'))
        info['path'] = os.path.join(info['dirname'], 'index.html')
        info['filename'] = os.path.basename(path)
        containerid = self._setContainerID(info, containerid)
        yield info


class PffExportParseAppointment(PffExportParseObject):
    """
    Parses an Appointment in a directory exported by pffexport.

    Parameters:
        path (str): the path to directory of the Appointment. It must be a directory.

    Yields:
        Information about the Appointment but not its attachments.
    """
    def run(self, path, containerid=None):
        info = {}
        info["content_type"] = "pst/Appointment"
        info["category"] = "email"
        info["extension"] = None
        appointment = readMessageFile(os.path.join(path, 'Appointment.txt'), stop_on_empty_line=False)
        info['content'] = appointment.get('subject', None)
        info['email_conversation_topic'] = appointment.get('conversation topic', None)
        info['creation_time'] = decodeEmailDateHeader(appointment.get('creation time', None))
        info['modification_time'] = decodeEmailDateHeader(appointment.get('modification time', None))
        info['event_time'] = decodeEmailDateHeader(appointment.get('start time', None))
        info['event_location'] = appointment.get('location', None)
        info.update(self._getRecipients(os.path.join(path, "Recipients.txt")))
        info['dirname'] = base.utils.relative_path(path, self.myconfig('casedir'))
        info['path'] = os.path.join(info['dirname'], 'index.html')
        info['filename'] = os.path.basename(path)
        containerid = self._setContainerID(info, containerid)
        yield info


class PffExportParseMeeting(PffExportParseObject):
    """
    Parses a Meeting in a directory exported by pffexport.

    Parameters:
        path (str): the path to directory of the Meeting. It must be a directory.

    Yields:
        Information about the Meeting but not its attachments.
    """
    def run(self, path, containerid=None):
        info = {}
        # parse the Message.html or rtf file in the directory: this is the content
        for f in os.listdir(path):
            if f.startswith("Message"):
                info = self.tika_parser.run(os.path.join(path, f))[0]
                break
        info["content_type"] = "pst/Meeting"
        info["category"] = "email"
        meeting = readMessageFile(os.path.join(path, 'Meeting.txt'), stop_on_empty_line=False)
        info['email_subject'] = meeting.get('subject', None)
        info['email_conversation_topic'] = meeting.get('conversation topic', None)
        info['creation_time'] = decodeEmailDateHeader(meeting.get('creation time', None))
        info['modification_time'] = decodeEmailDateHeader(meeting.get('modification time', None))
        info.update(self._getRecipients(os.path.join(path, "Recipients.txt")))
        info['dirname'] = base.utils.relative_path(path, self.myconfig('casedir'))
        info['path'] = os.path.join(info['dirname'], 'index.html')
        info['filename'] = os.path.basename(path)
        containerid = self._setContainerID(info, containerid)
        yield info


class PffExportParseTask(PffExportParseObject):
    """
    Parses a Task in a directory exported by pffexport.

    Parameters:
        path (str): the path to directory of the Task. It must be a directory.

    Yields:
        Information about the Task but not its attachments.

    Todo:
        We couldn't test this module
    """
    def run(self, path, containerid=None):
        info = {}
        # parse the Message.html file in the directory: this is the content
        for f in os.listdir(path):
            if f.startswith("Message"):
                info = self.tika_parser.run(os.path.join(path, f))[0]
                break
        info["content_type"] = "pst/Task"
        info["category"] = "email"
        info["extension"] = None
        info.update(self._getOutHeaders(os.path.join(path, "Task.txt")))
        info.update(self._getRecipients(os.path.join(path, "Recipients.txt")))
        containerid = self._setContainerID(info, containerid)
        info['dirname'] = base.utils.relative_path(path, self.myconfig('casedir'))
        info['path'] = os.path.join(info['dirname'], 'index.html')
        info['filename'] = os.path.basename(path)
        yield info


# Next classes are not complete yet


class MacMailParser(base.job.BaseModule):
    """
    Parses the macosx mailbox client files in the directory specified by path.

    # Parameters:
    #     path (str): the path to pass to from_module, which must yield, for each PST or OST file, a dictionary:
    #         `{outdir:"path to the output directory of the export", filename:"filaname of the PST or OST file"}`.

    Configuration:
        - **exportdir**: the export main directory.
    """

    def read_config(self):
        super().read_config()
        self.set_default_config('exportdir', os.path.join(self.myconfig('outputdir'), 'mail'))

    def run(self, path=''):
        # self.check_params(path, check_from_module=True)

        mailbox_directory = os.path.abspath(path)
        if not os.path.isdir(mailbox_directory):
            raise base.job.RVTError('Specified path {} is not a directory'.format(path))

        parseMacMailbox = ParseMacMailbox(self.config)
        with tqdm(total=int(sum([len(folder) for r, folder, file in os.walk(mailbox_directory)])), desc='indexing {}'.format(path)) as pbar:
            for root, dirs, files in os.walk(mailbox_directory):
                for dirpath in dirs:
                    pbar.update(1)
                    for m in parseMacMailbox.run(os.path.join(root, dirpath)):
                        yield m


class ParseMacMailbox(PffExportParseObject):
    """
    Parses an object (Message, Meeting, Contact, Task or Appointment) in a directory exported by pffexport.

    Parameters:
        path (str): the path to directory of the object. It must be a directory.

    Yields:
        Information about the object and its attachments.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tika_parser = base.job.load_module(self.config, 'indexer.tikaparser.TikaParser')

    def run(self, path, containerid=None):
        self.check_params(path, check_path_exists=True)
        if not os.path.isdir(path):
            raise base.job.RVTError('The path must be a directory: {}'.format(path))
        filetype_modules = {
            'Messages': EmlxParseMessage(self.config)
        }
        # print('path', path)
        if os.path.basename(path) in filetype_modules:
            # parse the main object
            rootid = None
            print('thepath:', path)
            for file in os.listdir(path):
                for m in filetype_modules[os.path.basename(path)].run(os.path.join(path, file), containerid):
                    if not containerid and not rootid:
                        rootid = m.get('_id')
                    yield m
            # parse attachments inside the object
            # if "Attachments" in os.listdir(path):
            #     for root, dirs, files in os.walk(mailbox_directory):
            #     for name in files:
            #         print(os.path.join(root, name))
            #     for attachment in self._parse_attachments(path, rootid):
            #         yield attachment

        return []


class EmlxParseMessage(PffExportParseObject):
    def run(self, path, containerid=None):
        info = {}
        # parse the Message.html or Message.rtf file in the directory: this is the content
        email_body = ''
        info = self.tika_parser.run(path)[0]
        info['content_type'] = "pst/Message"
        info["category"] = "email"
        intHeaders = os.path.join(path, "InternetHeaders.txt")
        # if os.path.isfile(intHeaders):
        if True:
            info.update(self._getInternetHeaders(path))
            info["email_send_or_received"] = "R"
        else:
            info["email_send_or_received"] = "S"
        info.update(self._getOutHeaders(os.path.join(path, "OutlookHeaders.txt")))
        if info.get('email_flags', '') and 'Unsent' in info['email_flags']:
            info["email_send_or_received"] = "U"
        info.update(self._getRecipients(os.path.join(path, "Recipients.txt")))
        try:
            info.update(self._getConversationIndex(os.path.join(path, "ConversationIndex.txt")))
        except Exception:
            info['email_guid'] = ""
        info['dirname'] = base.utils.relative_path(path, self.myconfig('casedir'))
        info['path'] = os.path.join(info['dirname'], email_body)
        info['filename'] = os.path.basename(path)
        containerid = self._setContainerID(info, containerid)
        # print(info)
        yield info
