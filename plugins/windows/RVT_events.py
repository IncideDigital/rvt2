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


import json
import os
import re
import ast
import logging
from evtx import PyEvtxParser
import pyevt

import base.job
from base.utils import check_folder, save_csv


def load_fields(filename):
    """ Loads fields from file as a dict """

    items = {}

    with open(filename, 'r') as fin:
        regex = re.compile("(.*):(.*)\n")
        for line in fin:
            aux = regex.search(line)
            items[aux.group(1)] = aux.group(2).lstrip()
    return items


class GetEvents(object):
    """ Extracts relevant event logs

        Args:
            eventfile: absolute path to the .evtx file to parse
            config_file: JSON configuration file setting transformations for specific events
    """

    def __init__(self, eventfile, config_file, logger=logging):
        self.logger = logger

        try:
            with open(config_file) as logcfg:
                logtext = logcfg.read()
            self.data_json = json.loads(logtext)
        except Exception as exc:
            self.logger.warning('Configuration file {} has not been properly loaded: {}'.format(config_file, exc))
            self.data_json = {}
        self.eventfile = eventfile

    def parse(self):
        parser = PyEvtxParser(self.eventfile)

        self.count = 0
        self.first_date = ''
        self.last_date = ''
        try:
            for record in parser.records_json():
                rec = json.loads(record['data'])['Event']
                data = {}
                # Date management
                data['event.created'] = record.get('timestamp', rec['System']['TimeCreated']['#attributes']['SystemTime'])
                if self.count == 0:
                    self.first_date = self.last_date = data['event.created']
                self.first_date = data['event.created'] if data['event.created'] < self.first_date else self.first_date
                self.last_date = data['event.created'] if data['event.created'] > self.last_date else self.last_date
                # Common fields
                if isinstance(rec['System']['EventID'], dict):
                    data['event.code'] = str(rec['System']['EventID']['#text'])
                else:
                    data['event.code'] = str(rec['System']['EventID'])
                data['event.provider'] = rec['System']['Provider']['#attributes']['Name']
                data['event.dataset'] = rec['System']['Channel']
                if 'Security' in rec['System']:
                    try:
                        data['user.id'] = rec['System']['Security']['#attributes']['UserID']
                    except Exception:
                        pass
                try:
                    data['process.pid'] = rec['System']['Execution']['#attributes']['ProcessID']
                    data['process.thread.id'] = rec['System']['Execution']['#attributes']['ThreadID']
                except Exception:
                    pass

                # Events not defined in data_json
                if not data['event.code'] in self.data_json.keys() or not re.search(self.data_json[data['event.code']]['provider'], data['event.provider']):
                    # EventData, UserData are just reproduced as dictionaries
                    if 'EventData' in rec:
                        data['EventData'] = rec['EventData']
                    if 'UserData' in rec:
                        data['UserData'] = rec['UserData']
                    yield data
                    continue

                # Selected events
                try:
                    description = self.data_json[data['event.code']]["description"].format(**rec)
                except Exception:
                    description = re.sub(r'{.*?}', '<>', self.data_json[data['event.code']]["description"])

                data['message'] = description
                for field in ['category', 'type', 'action']:
                    if field in self.data_json[data['event.code']]:
                        data['event.{}'.format(field)] = self.data_json[data['event.code']][field]
                if 'path' not in self.data_json[data['event.code']].keys():
                    yield data
                    continue

                # Extra fields
                for x, item in self.data_json[data['event.code']]['path'].items():
                    self.get_xpath_data(x, item, rec, data)

                yield data
                self.count += 1
        except Exception as exc:
            self.logger.warning('Error with pyevtx when reading the {} event from {}: {}'.format(count, self.eventfile, exc))

    def get_xpath_data(self, path, item, event, data):
        split_path = path.split('/')
        length = len(split_path) - 1
        act = item
        ev = event
        for e, p in enumerate(split_path):
            try:
                ev = ev[p]
            except Exception:
                continue
            if e == length:
                if len(act) == 0:
                    return

                if 'Name' in act.keys() and isinstance(act['Name'], list):
                    for item in act['Name']:
                        if 'transform' in act.keys() and item in act['transform'].keys():
                            name = str(act['transform'][item])
                        else:
                            name = 'data.{}'.format(str(item))
                        try:
                            if 'keep_format_type' in act.keys():
                                data[name] = ev[item]
                            else:
                                data[name] = str(ev[item])
                        except Exception:
                            pass
                else:
                    if 'transform' in act.keys() and p in act['transform'].keys():
                        name = str(act['transform'][p])
                    else:
                        name = 'data.{}'.format(str(p))
                    try:
                        if 'keep_format_type' in act.keys():
                            data[name] = ev[item]
                        else:
                            data[name] = str(ev[item])
                    except Exception:
                        pass
                    break

    def evtx_stats(self):
        # Gives general characerization of events in .evtx file
        return {'oldest': self.first_date,
                'newest': self.last_date,
                'source': os.path.basename(self.eventfile),
                'events': self.count}


class EventJob(base.job.BaseModule):
    """ Base class to parse event log sources """

    def read_config(self):
        super().read_config()
        self.set_default_config('events_summary', os.path.join(self.myconfig('analysisdir'), 'events', 'events_summary.csv'))

    def get_evtx(self, path, regex_search):
        """ Retrieve the evtx file to parse, looking for specific filenames inside a directory.

        Attrs:
            path: path to directory containing evtx files
            regex_search: regex expression to search for the precise evtx file log
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        rgx = re.compile(regex_search, re.I)
        for evtx_file in os.listdir(path):
            if rgx.search('/' + evtx_file):  # some regex patterns assume '/' to determine start
                return os.path.join(path, evtx_file)

        self.logger().debug('No evtx file found in {} with name expression {}'.format(path, regex_search))
        return

    def save_stats(self, data):
        # Keep track of every evtx stats
        summary_outfile = self.myconfig('events_summary')
        check_folder(os.path.dirname(summary_outfile))
        save_csv([data], outfile=summary_outfile, file_exists='APPEND')


class ParseEvents(EventJob):
    """ Extracts events of default evtx logs """

    def run(self, path=None):
        """
        Attrs:
            path (str): path to directory containing evtx files
        """

        json_file = self.config.config[self.config.job_name]['json_conf']

        evtx_file = self.get_evtx(path, os.path.basename(json_file).replace('json', 'evtx'))
        self.logger().debug('Parsing event log {}'.format(evtx_file))
        if not evtx_file:
            return []

        events_parser = GetEvents(evtx_file, json_file, logger=self.logger())
        for ev in events_parser.parse():
            yield ev
        self.save_stats(events_parser.evtx_stats())


class ParseExtraLogs(EventJob):
    """ Extracts events from evtx logs not considered individually in other jobs """

    def run(self, path=None):
        """
        Attrs:
            path (str): path to directory containing evtx files
        """

        json_file = self.config.config[self.config.job_name]['json_conf']

        # Get evtx parsed individually:
        special_evtx = [jf.replace('json', 'evtx')
                        for jf in os.listdir(os.path.dirname(json_file))
                        if jf != os.path.basename(json_file)]
        # Parse the extra evtx log files
        for evtx_filename in os.listdir(path):
            if evtx_filename in special_evtx:
                continue
            evtx_file = os.path.join(path, evtx_filename)
            if not evtx_file.lower().endswith('.evtx'):
                continue
            self.logger().debug('Parsing event log {}'.format(evtx_file))
            try:
                events_parser = GetEvents(evtx_file, json_file, logger=self.logger())
                for ev in events_parser.parse():
                    yield ev
                self.save_stats(events_parser.evtx_stats())
            except Exception:
                self.logger().warning('Problems parsing file %s' % evtx_file)

        return []


class Security(EventJob):
    """ Extracts events of Security.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Path to Security.evtx
        """
        path = self.get_evtx(path, r"/Security.evtx$")
        if not path:
            return []

        # category_id, subcategory_guid and audit_changes for event 4719
        category_id = load_fields(os.path.join(self.config.config['windows']['plugindir'], "sec_category_id.json"))

        subcategory_guid = load_fields(os.path.join(self.config.config['windows']['plugindir'], "sec_subcategory_guid.json"))

        audit_policy_changes = {"%%8448": "Success Removed",
                                "%%8449": "Success Added",
                                "%%8450": "Failure Removed",
                                "%%8451": "Failure Added"}

        # errordict for event 4625
        errordict = load_fields(os.path.join(self.config.config['windows']['plugindir'], "sec_error.json"))

        LogonTypeStr = load_fields(os.path.join(self.config.config['windows']['plugindir'], "logontype.json"))

        tgt_error_dict = load_fields(os.path.join(self.config.config['windows']['plugindir'], "tgt_error.json"))

        attributes = {}
        attributes[0] = "Reserved"
        attributes[1] = "Forwardable"
        attributes[2] = "Forwarded"
        attributes[3] = "Proxiable"
        attributes[4] = "Proxy"
        attributes[5] = "Allow-postdate"
        attributes[6] = "Postdated"
        attributes[7] = "Invalid"
        attributes[8] = "Renewable"
        attributes[9] = "Initial"
        attributes[10] = "Pre-authent"
        attributes[11] = "Opt-hardware-auth"
        attributes[12] = "Transited-policy-checked"
        attributes[13] = "Ok-as-delegate"
        attributes[14] = "Request-anonymous"
        attributes[15] = "Name-canonicalize"
        attributes[16] = "Unused"
        attributes[17] = "Unused"
        attributes[18] = "Unused"
        attributes[19] = "Unused"
        attributes[20] = "Unused"
        attributes[21] = "Unused"
        attributes[22] = "Unused"
        attributes[23] = "Unused"
        attributes[24] = "Unused"
        attributes[25] = "Unused"
        attributes[26] = "Disable-transited-check"
        attributes[27] = "Renewable-ok"
        attributes[28] = "Enc-tkt-in-skey"
        attributes[29] = "Unused"
        attributes[30] = "Renew"
        attributes[31] = "Validate"

        encr = load_fields(os.path.join(self.config.config['windows']['plugindir'], "encryption_id.json"))

        tgt = ('4768', '4769', '4770', '4771', '4772')

        protocol = load_fields(os.path.join(self.config.config['windows']['plugindir'], "protocol.json"))

        json_file = self.config.config[self.config.job_name]['json_conf']

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if "data.LogonType" in ev.keys():
                ev["data.LogonTypeStr"] = LogonTypeStr.get(ev["data.LogonType"], "Unknown")
            if "data.SubStatus" in ev.keys() and ev["data.SubStatus"] != "0x00000000":
                ev["data.Error"] = errordict.get(ev["data.SubStatus"], '')
            elif "data.Status" in ev.keys():
                if ev['data.Status'] in tgt_error_dict.keys():
                    ev['data.Error'] = tgt_error_dict[ev['data.Status']]
                else:
                    ev["data.Error"] = errordict.get(ev["data.Status"], '')
            if "data.CategoryId" in ev.keys():
                ev["data.Category"] = category_id.get(ev["data.CategoryId"], "")
            if "data.SubcategoryGuid" in ev.keys():
                ev["data.Subcategory"] = subcategory_guid.get(ev["data.SubcategoryGuid"], "")
            if "data.AuditPolicyChanges" in ev.keys():
                temp_aud = []
                for i in ev["data.AuditPolicyChanges"].split(","):
                    temp_aud.append(audit_policy_changes.get(i.lstrip(), ""))
                ev["data.AuditPolicyChangesStr"] = ", ".join(temp_aud)
            if ev['event.code'] in ('5152', '5153', '5154', '5156', '5157') and ev['event.provider'] == "Microsoft-Windows-Security-Auditing":
                if 'Direction' not in ev.keys():
                    ev['Direction'] = '-'
                elif ev['Direction'] == "%%14593":
                    ev['Direction'] = 'Outbound'
                else:
                    ev['Direction'] = 'Inbound'
                if 'Protocol' not in ev.keys():
                    ev['Protocol'] = '-'
                ev['Protocol'] = protocol.get(str(ev['Protocol']), ev['Protocol'])
            if ev['event.code'] in tgt:
                if 'data.TicketOptions' in ev.keys() and ev['data.TicketOptions']:
                    attr = int(ev['data.TicketOptions'], 16)
                    ticket_opt = []
                    for i in range(32):
                        if attr & (1 << i):
                            ticket_opt.append(attributes[31 - i])
                    ev['data.TicketOptions.str'] = ','.join(ticket_opt)
                if 'data.TicketEncryptionType' in ev.keys():
                    if ev['data.TicketEncryptionType'] in encr.keys():
                        ev['data.TicketEncryptionType'] = encr[ev['data.TicketEncryptionType']]
            yield ev
        self.save_stats(events_parser.evtx_stats())


class System(EventJob):
    """ Extracts events of System.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Path to System.evtx
        """

        path = self.get_evtx(path, r"/System.evtx$")
        if not path:
            return []

        reason_sleep = {"0": "Button or Lid",
                        "2": "Battery",
                        "4": "Low Battery",
                        "7": "System Idle"}

        boot_type = {"0": "After full shutdown",
                     "1": "After hybrid shutdown",
                     "2": "Resumed from hibernation"}

        json_file = self.config.config[self.config.job_name]['json_conf']

        fields = {'20250': {'provider': 'RemoteAccess', 'fields': ['data.RoutingDomainID', 'data.coID', 'destination.user', 'Port']},
                  '20253': {'provider': 'RemoteAccess', 'fields': ['data.RoutingDomainID', 'data.coID', 'destination.user', 'Port']},
                  '20255': {'provider': 'RemoteAccess', 'fields': ['data.coID', 'Port', 'destination.user', 'desc']},
                  '20271': {'provider': 'RemoteAccess', 'fields': ['data.coID', 'destination.user', 'source.ip', 'reasonStr', 'reason']},
                  '20272': {'provider': 'RemoteAccess', 'fields': ['data.coID', 'destination.user', 'Port', 'startDate', 'startHour', 'enddate', 'endHour', 'minutes', 'seconds', 'bytes.send', 'bytes.received', 'reasonStr']},
                  '20274': {'provider': 'RemoteAccess', 'fields': ['data.RoutingDomainID', 'data.coID', 'destination.user', 'Port', 'destination.ip', 'EventReceivedTime', 'SourceModuleName', 'SourceModuleType']},
                  '20275': {'provider': 'RemoteAccess', 'fields': ['data.coID', 'destination.user', 'connection.name', 'reason']},
                  }

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if "data.BootType" in ev.keys():
                ev["data.BootTypeStr"] = boot_type.get(ev["data.BootType"], "Unknown")
            if "data.Reason" in ev.keys():
                ev["data.ReasonStr"] = reason_sleep.get(ev.get('data.Reason'), 'Unknown')
            # Binary data in event logs is stored in hexadecimal format. Convert to text
            if "data.Binary" in ev.keys() and len(ev['data.Binary']) > 0 and ev['data.Binary'] != 'None':
                try:
                    ev['data.Text'] = bytearray.fromhex(ev['data.Binary']).decode()
                    ev.pop('data.Binary')
                except Exception:
                    pass
            if ev['event.code'] == '45058':
                aux_var = ev.get('user_date', '').split(',')
                ev['destination.user.name'] = aux_var[0][2:-1]
                ev['data.LastLoginLocalTime'] = aux_var[1][:-1]
                ev['message'] = 'A logon cache entry for user {} was the oldest entry and was removed. The timestamp of this entry was {}'.format(ev['destination.user.name'], ev['data.LastLoginLocalTime'])
                ev.pop('user_date')

            elif ev['event.code'] in fields.keys() and ev['event.provider'] == fields[ev['event.code']]['provider']:
                data = ast.literal_eval(ev["data.#text"])
                ev.pop('data.#text')
                for e, field in enumerate(fields[ev['event.code']]['fields']):
                    if data[e] == '(NULL)' or data[e] == '':
                        continue
                    if field == 'others':
                        for item in data[e][1:].split('\n'):
                            aux_fields = re.search("(.*) = (.*)", item)
                            ev[aux_fields.group(1)] = aux_fields.group(2)
                            ev['message'] = ev['message'].replace('<%s>' % aux_fields.group(1), aux_fields.group(2))
                        continue
                    ev[field] = data[e]
                    ev['message'] = ev['message'].replace('<%s>' % field, data[e])
            yield ev
        self.save_stats(events_parser.evtx_stats())


class SMBServer(EventJob):
    """ """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to Microsoft-Windows-SMBServer%4Security.evtx
        """

        path = self.get_evtx(path, r"Microsoft-Windows-SMBServer%4Security.evtx$")

        errordict = load_fields(os.path.join(self.config.config['windows']['plugindir'], "smb_error.json"))

        json_file = self.config.config[self.config.job_name]['json_conf']
        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if "data.Status" in ev.keys():
                ev["data.Error"] = errordict.get(ev["data.Status"], ev["data.Status"])
            yield ev
        self.save_stats(events_parser.evtx_stats())


class RDPLocal(EventJob):
    """ Extracts events of parsed Microsoft-Windows-TerminalServices-LocalSessionManager%4Operational.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to Microsoft-Windows-TerminalServices-LocalSessionManager%4Operational.evtx
        """

        path = self.get_evtx(path, r"/Microsoft-Windows-TerminalServices-LocalSessionManager%4Operational.evtx$")
        if not path:
            return []

        error_reason = load_fields(os.path.join(self.config.config['windows']['plugindir'], "rdp_local_error.json"))

        json_file = self.config.config[self.config.job_name]['json_conf']

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if "data.Reason" in ev.keys():
                ev["data.ReasonStr"] = error_reason.get(ev.get('data.Reason'), '')
            yield ev
        self.save_stats(events_parser.evtx_stats())


class RDPClient(EventJob):
    """ Extracts events of Microsoft-Windows-TerminalServices-RDPClient%4Operational.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to Microsoft-Windows-TerminalServices-RDPClient%4Operational.evtx
        """
        path = self.get_evtx(path, r"/Microsoft-Windows-TerminalServices-RDPClient%4Operational.evtx$")
        if not path:
            return []

        error_reason = load_fields(os.path.join(self.config.config['windows']['plugindir'], "rdp_client_error.json"))

        json_file = self.config.config[self.config.job_name]['json_conf']

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if "data.Reason" in ev.keys() and ev["event.code"] == "39":
                ev['data.ReasonStr'] = "SessionID {} disconnected by session {}".format(ev["data.SessionID"], ev["data.Source"])
            elif "data.Reason" in ev.keys() and ev["event.code"] == "1026":
                ev["data.ReasonStr"] = error_reason.get(ev.get('data.Reason'), '')
            yield ev
        self.save_stats(events_parser.evtx_stats())


class OAlerts(EventJob):
    """ Extracts events of parsed OAlerts.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to Microsoft-Windows-TerminalServices-LocalSessionManager%4Operational.evtx
        """
        path = self.get_evtx(path, r"/OAlerts.evtx$")
        if not path:
            return []

        json_file = self.config.config[self.config.job_name]['json_conf']

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if "#text" in ev.keys():
                content = ast.literal_eval(ev['#text'])
                ev['data.office_software'] = content[0].rstrip()
                ev['data.message_alert'] = content[1].strip()
                ev.pop('#text')
            yield ev
        self.save_stats(events_parser.evtx_stats())


class PartitionDiagnostic(EventJob):
    """ Extracts events of parsed Microsoft-Windows-Partition%4Diagnostic.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to Microsoft-Windows-Partition%4Diagnostic.evtx
        """
        path = self.get_evtx(path, r"/Microsoft-Windows-Partition%4Diagnostic.evtx$")
        if not path:
            return []

        json_file = self.config.config[self.config.job_name]['json_conf']

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            try:
                # if ev['data.device_id'].startswith('USB'):
                #     _, ev['data.vid_pid'], ev['data.device_sn'] = ev.pop('data.ParentId').split('\\')
                # else:
                #     ev['data.device_id'] = ev.pop('data.ParentId')
                if int(ev['data.Capacity']) != 0 and int(ev['data.PartitionTableBytes']) != 0:
                    ev['event.action'] = "device-connected"
                elif int(ev['data.PartitionTableBytes']) == 0:
                    ev['event.action'] = "device-disconnected"
                else:
                    ev['event.action'] = "device-unknown-action"
                ev.pop('data.PartitionTableBytes')
                capacity = ev.pop('data.Capacity')
                if capacity != 0:
                    ev['data.capacity'] = capacity
                # if ev['data.Manufacturer']:
                #     ev['data.device_model'] = ' '.join([ev.pop('data.Manufacturer'), ev.pop('data.Model')])
                # else:
                #     ev['data.device_model'] = ev.pop('data.Model')
                ev['data.device_registry_id'] = ev.pop('data.RegistryId')
                yield ev
            except Exception:
                self.logger().warning("Skipping {} event due to error".format(self.config.job_name))
                continue
        self.save_stats(events_parser.evtx_stats())


class StorageClassPnp(EventJob):
    """ Extracts events of parsed Microsoft-Windows-Storage-ClassPnP%4Operational.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to Microsoft-Windows-Storage-ClassPnP%4Operational.evtx
        """
        path = self.get_evtx(path, r"/Microsoft-Windows-Storage-ClassPnP%4Operational.evtx$")
        if not path:
            return []

        json_file = self.config.config[self.config.job_name]['json_conf']

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            try:
                if ev['event.code'] == "507":
                    if int(ev['data.ScsiStatus']) != 0:
                        ev['event.action'] = "device-connected"
                    else:
                        ev['event.action'] = "device-disconnected"
                    ev.pop('data.ScsiStatus')
                    yield ev
            except Exception:
                self.logger().warning("Skipping {} event due to error".format(self.config.job_name))
                continue
        self.save_stats(events_parser.evtx_stats())


class Application(EventJob):
    """ """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to Application.evtx
        """

        path = self.get_evtx(path, r"Application.evtx$")

        fields = {'1000': {'provider': 'Application Error', 'fields': ['product.name', 'product.version', 'timestamp1', 'module.name', 'module.version', 'module.timestamp2', 'error.code', 'offset', 'process.id', 'application.starttime', 'application.path', 'module.path', 'report.id', 'package.full_name', 'package-relative_application.id']},
                  '1001': {'provider': 'Windows Error Reporting', 'fields': ['Fault_bucket', 'type', 'event.name', 'response', 'cab.id', 'p6', 'p7', 'p8', 'p9', 'p10', 'p11', 'p12', 'p13', 'p14', 'p15', 'Attached_files', 'Attached_path', 'Analysis_symbol', 'rechecking_for_solution', 'report.id', 'report.status']},
                  '1002': {'provider': 'Application Hang', 'fields': ['product name', 'product.version', 'process.id', 'application.starttime', 'application.terminationtime', 'application.path', 'report.id']},
                  '1013': {'provider': 'MsiInstaller', 'fields': ['error.message']},
                  '1025': {'provider': 'MsiInstaller', 'fields': ['product.name', 'path', 'process.name', 'process.pid']},
                  '1029': {'provider': 'MsiInstaller', 'fields': ['product.name']},
                  '1033': {'provider': 'MsiInstaller', 'fields': ['product.name', 'product.version', 'product.language', 'status', 'manufacturer']},
                  '1034': {'provider': 'MsiInstaller', 'fields': ['product.name', 'product.version', 'product.language', 'status', 'manufacturer']},
                  '1035': {'provider': 'MsiInstaller', 'fields': ['product.name', 'product.version', 'product.language', 'status', 'manufacturer']},
                  '1038': {'provider': 'MsiInstaller', 'fields': ['product.name', 'product.version', 'product.language', 'reboot.type', 'reason', 'manufacturer']},
                  '10005': {'provider': 'MsiInstaller', 'fields': ['error', 'arg1', 'arg2', 'arg3', 'arg4', 'arg5']},
                  '11707': {'provider': 'MsiInstaller', 'fields': ['status']},
                  '11708': {'provider': 'MsiInstaller', 'fields': ['status']},
                  '17806': {'provider': 'MSSQLSERVER', 'fields': ['error.code', 'state', 'reason', 'reason2', 'source.address']},
                  '18456': {'provider': 'MSSQLSERVER', 'fields': ['destination.user.name', 'reason', 'source.address']},
                  '20220': {'provider': 'RasClient', 'fields': []},
                  '20221': {'provider': 'RasClient', 'fields': ['data.coID', 'source.user', 'connection', 'connection.type', 'connection.name', 'others']},
                  '20222': {'provider': 'RasClient', 'fields': ['data.coID', 'source.user', 'connection.name', 'others']},
                  '20223': {'provider': 'RasClient', 'fields': ['data.coID', 'source.user', 'others']},
                  '20224': {'provider': 'RasClient', 'fields': ['data.coID', 'source.user']},
                  '20225': {'provider': 'RasClient', 'fields': ['data.coID', 'source.user', 'connection.name', 'others']},
                  '20226': {'provider': 'RasClient', 'fields': ['data.coID', 'source.user', 'connection.name', 'reason']},
                  '20227': {'provider': 'RasClient', 'fields': ['data.coID', 'source.user', 'connection.name', 'reason']},
                  }

        json_file = self.config.config[self.config.job_name]['json_conf']

        error_str = load_fields(os.path.join(self.config.config['windows']['plugindir'], "raserror.json"))
        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if "data.Binary" in ev.keys() and len(ev['data.Binary']) > 0 and ev['data.Binary'] != 'None':
                ev['data'] = bytearray.fromhex(ev['data.Binary']).decode()
                ev.pop('data.Binary')
            if ev['event.code'] in fields.keys() and ev['event.provider'] == fields[ev['event.code']]['provider']:
                data = ast.literal_eval(ev["data.#text"])
                ev.pop('data.#text')
                for e, field in enumerate(fields[ev['event.code']]['fields']):
                    if data[e] == '(NULL)' or data[e] == '':
                        continue
                    if field == 'reason' and ev['event.provider'] == 'RasClient':
                        ev['reasonStr'] = error_str.get(data[e], '')
                    if field == 'others':
                        for item in data[e][1:].split('\n'):
                            aux_fields = re.search("(.*) = (.*)", item)
                            ev[aux_fields.group(1)] = aux_fields.group(2)
                            ev['message'] = ev['message'].replace('<%s>' % aux_fields.group(1), aux_fields.group(2))
                        continue
                    ev[field] = data[e]
                    ev['message'] = ev['message'].replace('<%s>' % field, data[e])
            yield ev
        self.save_stats(events_parser.evtx_stats())


class PowerShell(EventJob):
    """ Extracts events of Windows PowerShell.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Path to "Windows PowerShell.evtx"
        """
        path = self.get_evtx(path, r"/Windows PowerShell.evtx$")
        if not path:
            return []

        json_file = self.config.config[self.config.job_name]['json_conf']

        # Regex used to extract details
        user_rgx = re.compile('UserId=([^\r]*)\\r\\n')
        host_rgx = re.compile('HostName=([^\r]*)\\r\\n')
        version_rgx = re.compile('HostVersion=([^\r]*)\\r\\n')
        version2_rgx = re.compile('EngineVersion=([^\r]*)\\r\\n')
        app_rgx = re.compile('HostApplication=([^\r]*)\\r\\n')
        script_rgx = re.compile('ScriptName=([^\r]*)\\r\\n')
        cli_rgx = re.compile('CommandLine=(.*)$')

        events_parser = GetEvents(path, json_file, logger=self.logger())
        for ev in events_parser.parse():
            if ev['event.code'] not in ["400", "600", "800"]:
                continue
            data = ev.pop('data.PSData')
            if ev['event.code'] == "800":
                details = data[1]
            else:
                details = data[2]
            # details example:
            """ "\tNewEngineState=Available\r\n\tPreviousEngineState=None\r\n\r\n\tSequenceNumber=318419\
r\n\r\n\tHostName=Default Host\r\n\tHostVersion=4.0\r\n\tHostId=30ba2936-467d-4ded-b94f-889baa517
0c0\r\n\tHostApplication=C:\\Windows\\system32\\ServerManager.exe\r\n\tEngineVersion=4.0\r\n\tRun
spaceId=7659aa03-a84d-47e2-91bc-d1671de4cd63\r\n\tPipelineId=\r\n\tCommandName=\r\n\tCommandType=
\r\n\tScriptName=\r\n\tCommandPath=\r\n\tCommandLine=" """
            for rgx, name in zip([user_rgx, host_rgx, version_rgx, version2_rgx, app_rgx, script_rgx, cli_rgx],
                                 ['user.name', 'data.HostName', 'data.HostVersion', 'data.EngineVersion', 'data.Command', 'file.path', 'data.CommandLine']):
                match = re.search(rgx, details)
                ev[name] = match.groups()[0] if match else ''
            if ev['event.code'] == "400":
                ev['data.NewEngineState'] = data[0]
                ev['data.PreviousEngineState'] = data[1]
                ev['message'] = f'Engine state is changed from {data[0]} to {data[1]}'
            elif ev['event.code'] == "600":
                ev['data.ProviderName'] = data[0]
                ev['data.NewProviderState'] = data[1]
                ev['message'] = f'Provider {data[0]} is {data[1]}'
            elif ev['event.code'] == '800':
                ev['message'] = f"Pipeline execution details for command line: {ev['data.CommandLine']}"

            yield ev
        self.save_stats(events_parser.evtx_stats())


class ParseEvt(object):
    """ Extracts events from evt logs """

    def __init__(self, eventfile, logger=logging):
        self.logger = logger
        self.eventfile = eventfile
        self.description = {
            # "512": {"": "Windows is starting up."},
            "513": {"security": "Windows is shutting down."},
            # "514": {"": "An authentication package has been loaded by the Local Security Authority."},
            # "515": {"": "A trusted logon process has been registered with the Local Security Authority."},
            # "516": {"": "Internal resources allocated for the queuing of audit messages have been exhausted, leading to the loss of some audits."},
            "517": {"security": "The audit log was cleared"},
            # "518": {"": "A notification package has been loaded by the Security Account Manager."},
            # "520": {"": "The system time was changed."},
            "528": {"security": "An account was successfully logged on."},
            "529": {"security": "Logon Failure : Unknown username or bad password"},
            "530": {"security": "Logon Failure : Account logon time restriction violation"},
            "531": {"security": "Logon Failure : Account currently disabled"},
            "532": {"security": "Logon Failure : The specified user account has expired"},
            "533": {"security": "Logon Failure : User not allowed to logon at this computer"},
            "534": {"security": "Logon Failure : The user has note been granted the requested logon type at this machine"},
            "535": {"security": "Logon Failure : The specified account's password has expired"},
            "536": {"security": "Logon Failure : The NetLogon component is not active"},
            "537": {"security": "The logon attempt failed for other reasons"},
            "538": {"security": "An account was logged off."},
            "539": {"security": "Logon Failure : Account locked out"},
            "540": {"security": "An account was successfully logged on."},
            "551": {"security": "User initiated logoff."},
            "552": {"security": "A logon was attempted using explicit credentials."},
            "564": {"security": "An object was deleted."},
            "565": {"security": "A handle to an object was requested."},
            "576": {"security": "Special privileges assigned to new logon."},
            # "577": {"": "A privileged service was called."},
            # "578": {"": "An operation was attempted on a privileged object."},
            # "592": {"": "A new process has been created."},
            # "593": {"": "A process has exited."},
            # "594": {"": "An attempt was made to duplicate a handle to an object."},
            # "595": {"": "Indirect access to an object was requested."},
            # "601": {"": "Attempt to install a service"},
            # "602": {"": "A scheduled task was created, deleted, enabled, disabled or updated."},
            # "608": {"": "A user right was assigned."},
            # "609": {"": "A user right was removed."},
            # "612": {"": "System audit policy was changed."},
            # "617": {"": "Kerberos policy was changed."},
            # "618": {"": "Encrypted data recovery policy was changed."},
            # "628": {"": "An attempt was made to reset an account's password."},
            # "631": {"": "A security-enabled global group was created."},
            # "639": {"": "A security-enabled local group was changed."},
            # "641": {"": "A security-enabled global group was changed."},
            # "643": {"": "Domain Policy was changed."},
            # "658": {"": "A security-enabled universal group was created."},
            # "659": {"": "A security-enabled universal group was changed."},
            # "667": {"": "A security-disabled group was deleted"},
            # "668": {"": "A group's type was changed."},
            # "621": {"": "System security access was granted to an account."},
            # "622": {"": "System security access was removed from an account."},
            # "624": {"": "A user account was created."},
            # "626": {"": "A user account was enabled."},
            # "627": {"": "An attempt was made to change an account's password."},
            # "629": {"": "A user account was disabled."},
            # "630": {"": "A user account was deleted."},
            # "632": {"": "A member was added to a security-enabled global group."},
            # "633": {"": "A member was removed from a security-enabled global group."},
            # "634": {"": "A security-enabled global group was deleted."},
            # "635": {"": "A security-enabled local group was created."},
            # "636": {"": "A member was added to a security-enabled local group."},
            # "637": {"": "A member was removed from a security-enabled local group."},
            # "638": {"": "A security-enabled local group was deleted."},
            # "642": {"": "A user account was changed."},
            # "644": {"": "A user account was locked out."},
            # "648": {"": "A security-disabled local group was created."},
            # "649": {"": "A security-disabled local group was changed."},
            # "650": {"": "A member was added to a security-disabled local group."},
            # "651": {"": "A member was removed from a security-disabled local group."},
            # "652": {"": "A security-disabled local group was deleted."},
            # "653": {"": "A security-disabled global group was created."},
            # "654": {"": "A security-disabled global group was changed."},
            # "655": {"": "A member was added to a security-disabled global group."},
            # "656": {"": "A member was removed from a security-disabled global group."},
            # "657": {"": "A security-disabled global group was deleted."},
            # "660": {"": "A member was added to a security-enabled universal group."},
            # "661": {"": "A member was removed from a security-enabled universal group."},
            # "662": {"": "A security-enabled universal group was deleted."},
            # "663": {"": "A security-disabled universal group was created."},
            # "664": {"": "A security-disabled universal group was changed."},
            # "665": {"": "A member was added to a security-disabled universal group."},
            # "666": {"": "A member was removed from a security-disabled universal group."},
            # "671": {"": "A user account was unlocked."},
            # "672": {"": "A Kerberos authentication ticket (TGT) was requested."},
            # "672": {"": "A Kerberos authentication ticket request failed."},
            # "676": {"": "A Kerberos authentication ticket (TGT) was requested."},
            # "673": {"": "A Kerberos service ticket was requested."},
            # "674": {"": "A Kerberos service ticket was renewed."},
            # "675": {"": "Kerberos pre-authentication failed."},
            # "678": {"": "An account was mapped for logon."},
            # "679": {"": "An account could not be mapped for logon."},
            # "680": {"": "The domain controller attempted to validate the credentials for an account."},
            # "681": {"": "The domain controller attempted to validate the credentials for an account."},
            # "682": {"": "A session was reconnected to a Window Station."},
            # "683": {"": "A session was disconnected from a Window Station."},
            # "685": {"": "The name of an account was changed:"},
            # "774": {"": "Certificate Services revoked a certificate."},
            "1000": {"application error": "Faulting application <product.name>, version <product.version>, faulting module <module.name>, version <module.version>, fault address <offset>"},
            "1001": {"application error": "Faulting application <product.name>, version <product.version>, faulting module <module.name>, version <module.version>, fault address <offset>"},
            "1003": {"system error": "Crashing application <product.name>, version <product.version>, crashing module <module.name>, version <module.version>, fault address <offset>"},
            "1033": {"msiinstaller": "Product: <product.name>. Version: <product.version>. Language: <product.language>. Installation completed with status: <status>. Manufacturer: <manufacturer>."},
            "1034": {"msiinstaller": "Product: <product.name>. Version: <product.version>. Language: <product.language>. Removal completed with status: <status>. Manufacturer: <manufacturer>."},
            "1035": {"msiinstaller": "Product: <product.name>. Version: <product.version>. Language: <product.language>. Configuration change completed with status: <status>. Manufacturer: <manufacturer>."},
            "1038": {"msiinstaller": "Product: <product.name>. Version: <product.version>. Language: <product.language>. Reboot required. Reboot Type: <reboot.type>. Reboot Reason: <reason>. Manufacturer: <manufacturer>."},
            "1074": {"user32": "An application causes the system to restart, or user initiates a restart or shutdown"},
            "6005": {"eventlog": "Event log service was started"},
            "6006": {"eventlog": "Event log service was stopped"},
            "6008": {"eventlog": "Previous system shutdown unexpected"},
            "7031": {"service control manager": "The {EventData[param1]} service terminated unexpectedly. It has done this {EventData[param2]} time(s). The following corrective action will be taken in {EventData[param3]} milliseconds. {EventData[param5]}"},
            "7034": {"service control manager": "{EventData[param1]} service terminated unexpectedly. It has done this {EventData[param2]} time(s)."},
            "7036": {"service control manager": "The {EventData[param1]} service entered the state {EventData[param2]}"},
            "7040": {"service control manager": "The start type of the {EventData[param1]} service was changed from {EventData[param2]} to {EventData[param3]}"},
            "7045": {"service control manager": "A new service was installed in the system"},
            "11707": {"msiinstaller": "<status>"},
            "11708": {"msiinstaller": "<status>"}
        }

    def parse(self):
        evt_file = pyevt.file()
        ev_type = {"16": "Audit Failure",
                   "8": "Audit Success",
                   "1": "Error",
                   "4": "information",
                   "2": "warning"}

        self.count = 0
        self.first_date = ''
        self.last_date = ''

        evt_file.open(self.eventfile)
        for ev in range(evt_file.number_of_records):
            rec = evt_file.get_record(ev)
            record = {}

            # Date management
            record["event.created"] = str(rec.creation_time)
            self.count = ev
            if self.count == 0:
                self.first_date = self.last_date = record['event.created']
            self.first_date = record['event.created'] if record['event.created'] < self.first_date else self.first_date
            self.last_date = record['event.created'] if record['event.created'] > self.last_date else self.last_date

            # Rest of fields
            record["event.type"] = ev_type[str(rec.event_type)]
            record["event.code"] = str(rec.event_identifier % 65536)
            record["event.provider"] = rec.source_name.lower()
            record["computer.name"] = rec.computer_name
            record["event.category"] = rec.event_category
            record["user.id"] = rec.user_security_identifier

            if record["event.code"] in self.description.keys() and record["event.provider"] in self.description[record["event.code"]].keys():
                record["message"] = self.description[record["event.code"]][record["event.provider"]]

            tmp_string = []

            for st in rec.strings:
                tmp_string.append(st)
            if record["event.provider"] == "service control manager":
                if record["event.code"] == "7031":
                    record['service.name'] = tmp_string[0]
                    record['service.state'] = tmp_string[1]
                elif record["event.code"] == "7036":
                    record['service.name'] = tmp_string[0]
                    record['service.state'] = tmp_string[1]
                elif record["event.code"] == "7040":
                    record['service.name'] = tmp_string[0]
                    record['service.state'] = tmp_string[1]
                    record['service.previous_state'] = tmp_string[2]
                elif record["event.code"] == "7045":
                    record['service.name'] = tmp_string[0]
                    record['file.path'] = tmp_string[1]
            elif record["event.provider"] == "security":
                if record["event.code"] in ("528", "540"):
                    record['destination.user.name'] = tmp_string[0]  # User Name
                    record['destination.domain'] = tmp_string[1]  # Domain
                    record['TargetLogonId'] = tmp_string[2]  # Logon ID
                    record['LogonType'] = tmp_string[3]
                    record['process.name'] = tmp_string[4]  # Logon Process
                    record['AuthenticationPackageName'] = tmp_string[5]  # Authentication Package
                    record['Workstation_Name'] = tmp_string[6]
                    record['Logon_GUID'] = tmp_string[7]
                    if len(tmp_string) > 8:
                        record['source.user.name'] = tmp_string[8]  # Caller User Name
                    if len(tmp_string) > 9:
                        record['source.domain'] = tmp_string[9]  # Caller Domain
                    if len(tmp_string) > 10:
                        record['source.logonID'] = tmp_string[10]  # Caller Logon ID
                    if len(tmp_string) > 11:
                        record['source.process.id'] = tmp_string[11]  # Caller Process ID
                    if len(tmp_string) > 12:
                        record['transited.services'] = tmp_string[12]  # Transited Services
                    if len(tmp_string) > 13:
                        record['source.ip'] = tmp_string[13]
                    if len(tmp_string) > 14:
                        record['source.port'] = tmp_string[14]
                    if len(tmp_string) > 15:
                        record['caller.process.name'] = tmp_string[15]  # Caller Process Name
                if record["event.code"] == "538":
                    record['destination.user.name'] = tmp_string[0]  # User Name
                    record['destination.domain'] = tmp_string[1]  # Domain
                    record['TargetLogonId'] = tmp_string[2]
                    record['LogonType'] = tmp_string[3]  # Logon Process
                if record["event.code"] == "552":
                    record['source.user'] = tmp_string[0]  # User Name
                    record['source.domain'] = tmp_string[1]  # Domain
                    record['TargetLogonId'] = tmp_string[2]  # Logon ID
                    record['Logon_GUID'] = tmp_string[3]
                    if len(tmp_string) > 4:
                        record['destination.user.name'] = tmp_string[4]  # Target User Name
                    if len(tmp_string) > 5:
                        record['destination.domain'] = tmp_string[5]  # Target Domain
                    if len(tmp_string) > 6:
                        record['destination.Logon_GUID'] = tmp_string[6]  # Target Logon GUID
                    if len(tmp_string) > 7:
                        record['destination.server.name'] = tmp_string[7]  # Target Server Name
                    if len(tmp_string) > 8:
                        record['destination.server.info'] = tmp_string[8]  # Target Server Info
                    if len(tmp_string) > 9:
                        record['source.process.id'] = tmp_string[9]  # Caller Process ID
                    if len(tmp_string) > 10:
                        record['source.ip'] = tmp_string[10]
                    if len(tmp_string) > 11:
                        record['source.port'] = tmp_string[11]
                    if len(tmp_string) > 12:
                        record['source.process'] = tmp_string[12]  # Caller Process Name
            else:
                for e, data in enumerate(tmp_string, 1):
                    record["String_%s" % e] = data
            yield record

    def evt_stats(self):
        # Gives general characerization of events in .evt file
        return {'oldest': self.first_date,
                'newest': self.last_date,
                'source': os.path.basename(self.eventfile),
                'events': self.count}


class ParseEvts(base.job.BaseModule):
    """ Extracts events from evt logs """

    def read_config(self):
        super().read_config()
        self.set_default_config('events_summary', os.path.join(self.myconfig('analysisdir'), 'events', 'events_summary.csv'))

    def run(self, path=None):
        """
        Attrs:
            path (str): path to directory containing evt files
        """

        # Parse evt log files
        for evt_filename in os.listdir(path):
            evt_file = os.path.join(path, evt_filename)
            if not evt_file.lower().endswith('.evt'):
                continue
            self.logger().debug('Parsing event log {}'.format(evt_file))
            try:
                events_parser = ParseEvt(evt_file, logger=self.logger())
                for ev in events_parser.parse():
                    yield ev
                self.save_stats(events_parser.evt_stats())
            except Exception:
                self.logger().warning('Problems parsing file %s' % evt_file)

    def save_stats(self, data):
        # Keep track of every evt stats
        summary_outfile = self.myconfig('events_summary')
        check_folder(os.path.dirname(summary_outfile))
        save_csv([data], outfile=summary_outfile, file_exists='APPEND')
