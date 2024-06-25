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


import os
import ast
import datetime
import dateutil.parser
from collections import defaultdict

import base.job
from base.utils import save_md_table, date_to_iso
from plugins.windows.RVT_os_info import CharacterizeWindows

class Filter_Events(base.job.BaseModule):
    """ Filters events for generating a csv file """

    def run(self, path=None):
        events = ast.literal_eval(self.config.config[self.config.job_name]['events_dict'])

        for event in self.from_module.run(path):
            if event['event.code'] in events.keys() and event['event.provider'] == events[event['event.code']]:
                yield event


class LogonRDP(base.job.BaseModule):
    """ Extracts logon and rdp artifacts """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        logID = {}
        actID = {}

        for event in self.from_module.run(path):
            ev = dict()
            ev['TimeCreated'] = event.get('event.created', '')
            ev['EventID'] = event.get('event.code', '')
            ev['Description'] = event.get('message', '')
            ev['ActivityID'] = event.get('data.ActivityID', )
            ev['SessionID'] = event.get('data.SessionID', '')
            ev['ConnType'] = event.get('data.ConnType', '')
            ev['LogonType'] = event.get('data.LogonType', '')
            ev['LogonTypeStr'] = event.get('data.LogonTypeStr', '')
            ev['source.port'] = event.get('source.port', '')
            ev['ProcessName'] = event.get('process.name', '')
            ev['Logon.ProcessName'] = event.get('data.LogonProcessName', '')
            ev['AuthenticationPackageName'] = event.get('data.AuthenticationPackageName', '')
            ev['client.hostname'] = event.get('client.hostname', '')   # Only events 4778 and 4779

            for ip_name in ['client.ip', 'client.address', 'source.ip', 'source.address']:
                if ip_name in event.keys():
                    ev['source.ip'] = event[ip_name]

            if "data.ConnectionName" in event.keys():
                ev['ConnectionName'] = event['data.ConnectionName']
            else:
                ev['ConnectionName'] = event.get('data.SessionName')
            if 'data.ReasonStr' in event.keys():
                ev['ReasonStr'] = event['data.ReasonStr']
            elif 'data.DisconnectReason' in event.keys():
                ev['ReasonStr'] = event['data.DisconnectReason']
            else:
                ev['ReasonStr'] = event.get('data.Reason', '')
            if 'source.user.name' in event.keys():
                if event['source.user.name'] != '-':
                    ev['User'] = "{}\\{}".format(event['source.domain'], event['source.user.name'])
                else:
                    ev['User'] = '-'
            elif 'client.source.name' in event.keys():
                ev['User'] = event['client.source.name']
            else:
                ev['User'] = event.get('User', '')
            if 'destination.user.name' in event.keys():
                if event['destination.user.name'] != '-':
                    if 'destination.domain' in event.keys():
                        ev['TargetUser'] = "{}\\{}".format(event['destination.domain'], event['destination.user.name'])
                    else:
                        ev['TargetUser'] = event['destination.user.name']
                else:
                    ev['TargetUser'] = '-'
            else:
                ev['TargetUser'] = ''
            if 'data.TargetLogonId' in event.keys():
                ev['LogonID'] = event['data.TargetLogonId']
            else:
                ev['LogonID'] = event.get('data.LogonID', '')

            if ev['EventID'] in ("4624", "4634", "4647", "4648"):
                if ev['LogonID'] not in logID.keys():
                    logID[ev['LogonID']] = []
                logID[ev['LogonID']].append(ev)
            elif ev['EventID'] in ("21", "23", "24", "25", "39", "40", "65", "66", "102", "131", "140", "1149"):
                if ev['ActivityID'] not in actID.keys():
                    actID[ev['ActivityID']] = []
                actID[ev['ActivityID']].append(ev)
            elif ev['EventID'] in ("4778", "4779"):
                activity = self.relateIDs(ev, actID)
                if activity != '':
                    actID[activity].append(ev)
                    logID[ev['LogonID']].append(ev)

            yield ev
        self.extractRDP(actID)
        self.extractLogon(logID)
        self.extractLogonNetwork(logID)

    def __difTimestamp__(self, d1, d0):
        """ get seconds between dates in ISO format
        Args;
            d0 (str): date 1
            d1 (str); date 2
        Returns:
            int: absolute value of d1 - d0
        """

        if d1 == '-' or d0 in ('', '-'):
            return 1.e5
        return abs((dateutil.parser.parse(d1) - dateutil.parser.parse(d0)).total_seconds())

    def relateIDs(self, ev, actID):
        """ relates events 4778 and 4779 with RDP events
        Args:
            ev (dict): event 4778 or 4779 to relate
            actID (dict): dict with list of RDP events with key ActivityID and values a list of events
        Returns:
            str: activityID closer to ev
        """
        d0 = 100000
        actual_actID = ''
        t0 = dateutil.parser.parse(ev['TimeCreated'])
        for k, v in actID.items():
            for event in v:
                if "data.ConnectionName" in event.keys() and ev['ConnectionName'] == event['data.ConnectionName']:
                    d1 = abs((dateutil.parser.parse(event['TimeCreated']) - t0).total_seconds())
                    if d1 < d0:
                        actual_actID = event['ActivityID']
                        d0 = d1
        return actual_actID

    def extractLogon(self, logID):

        results = []
        for eventlist in logID.values():
            logon = '-'
            ip = '-'
            # ln = len(eventlist)
            for e, v in enumerate(eventlist):
                if v['LogonType'] in ("3", "4", "5"):
                    continue
                if v['EventID'] == '4634':
                    results.append({'Login': logon, 'IP': ip, 'Logoff': v['TimeCreated'], 'User': v['TargetUser']})
                    logon = ''
                    ip = ''
                    continue
                if v['EventID'] == '4624':
                    logon = v['TimeCreated']
                    ip = v.get('source.ip')
                # if e == ln:
                    results.append({'Login': logon, 'IP': ip, 'Logoff': v['TimeCreated'], 'User': v['TargetUser']})

        save_md_table(results, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'logon_offs.md'),
                      fieldnames='Login IP Logoff User',
                      file_exists='OVERWRITE')

    def extractLogonNetwork(self, logID):
        """ Only events 4624 and 4634 with LogonType 3 (Network) """

        results = []
        event_types = {'4624': 'Login (UTC)', '4634': 'Logoff (UTC)'}
        logons = defaultdict(dict)
        for eventlist in logID.values():
            for e, v in enumerate(eventlist):
                if v['EventID'] not in ["4624", "4634"]:
                    continue
                if not v['LogonType'] == "3":
                    continue
                logon_id = v['LogonID']
                event_type = event_types[v['EventID']]
                logons[logon_id][event_type] = date_to_iso(v['TimeCreated'], sep=' ', timespec='seconds', hide_tz=True)
                logons[logon_id]['User'] = v['TargetUser']
                logons[logon_id]['LogonType'] = v['LogonTypeStr']
                # The following information is only available in 4624 events
                if v['EventID'] == "4624":
                    logons[logon_id]['SourceIP'] = v.get('source.ip')
                    logons[logon_id]['SourcePort'] = v.get('source.port')
                    logons[logon_id]['ProcessName'] = v['Logon.ProcessName']
                    logons[logon_id]['AuthenticationPackage'] = v['AuthenticationPackageName']

        results = [logon for logon in logons.values()]

        save_md_table(results, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'logons_network.md'),
                      fieldnames="['Login (UTC)', 'Logoff (UTC)', 'User', 'SourceIP', 'SourcePort', 'LogonType', 'ProcessName', 'AuthenticationPackage']",
                      backticks_fields='User',
                      date_fields="['Login (UTC)', 'Logoff (UTC)']",
                      file_exists='OVERWRITE')

    def extractRDP(self, actID):

        results = []
        suser = ''
        auxtime = ''
        auxtime2 = ''
        for eventlist in actID.values():
            act = dict()
            insession = False
            for e, v in enumerate(eventlist):
                if v['EventID'] in ('23', '24'):
                    if not insession and self.__difTimestamp__(v["TimeCreated"], auxtime2) < 1:
                        continue  # two logoff events consecutives
                    if v['EventID'] == '23' and ('reason' not in act.keys() or act['reason'] == ''):
                        act['reason'] = 'logoff succeeded'
                    insession = False
                    act['TargetUser'] = v['TargetUser']
                    results.append({'Login': act.get('t0', '-'), 'SubjectUser': act.get('subjectUser', ''), 'IP': act.get('ip', ''), 'Logoff': v['TimeCreated'], 'User': act.get('TargetUser', ''), 'Reason': act.get('reason', '')})
                    act = dict()
                    auxtime2 = v['TimeCreated']
                elif v['EventID'] in ('39', '40'):
                    act['reason'] = v['ReasonStr']
                elif v['EventID'] in ('21', '25'):
                    if 't0' in act.keys() and act['t0'] not in ('', '-'):
                        if self.__difTimestamp__(v["TimeCreated"], act['t0']) < 1:  # login event repeated
                            continue
                        else:  # unfinished event
                            results.append({'Login': act.get('t0', '-'), 'SubjectUser': act.get('subjectUser', ''), 'IP': act.get('ip', ''), 'Logoff': act.get('t1', ''), 'User': act.get('TargetUser', ''), 'Reason': act.get('reason', '')})
                    insession = True
                    act['t1'] = '-'
                    act['reason'] = ''
                    if 'subjectUser' not in act.keys():
                        act['subjectUser'] = ''
                    act['t0'] = v['TimeCreated']
                    act['ip'] = v.get('source.ip')
                    act['targetUser'] = v['User']
                    if self.__difTimestamp__(v['TimeCreated'], auxtime) < 2:
                        act['subjectUser'] = suser
                elif v['EventID'] == '1149':
                    act['TargetUser'] = v['TargetUser']
                    auxtime = v['TimeCreated']

            if ('t0' in act.keys() and act['t0'] not in ('', '-')) or ('t1' in act.keys() and act['t1'] not in ('', '-')):  # for writing unclosed event
                results.append({'Login': act.get('t0', '-'), 'SubjectUser': act.get('subjectUser', ''), 'IP': act.get('ip', ''), 'Logoff': act.get('t1', '-'), 'User': act.get('TargetUser', ''), 'Reason': act.get('reason', '')})
        save_md_table(results, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'rdp.md'),
                      fieldnames='Login SubjectUser IP Logoff User Reason',
                      file_exists='OVERWRITE')


class RDPIncoming(base.job.BaseModule):
    """ Extracts events related to incoming RDP connections """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        # Events will be categorized by their associated ActivityID. Each key contains a list of events
        aID = {}
        # Get poweron and poweroff events to manage unfinished sessions
        # eID 12: The operating system started
        # eID 13: The operating system is shutting down
        power_ev = []

        for event in self.from_module.run(path):
            ev = dict()
            ev['EventID'] = event.get('event.code', '')
            ev['TimeCreated'] = event.get('event.created', '')
            ev['Description'] = event.get('message', '')

            if ev['EventID'] in ("12", "13"):
                power_ev.append(ev)
                continue

            ev['User'] = event.get('destination.user.name', '')
            ev['SessionID'] = event.get('data.SessionID', '')
            ev['SourceAddress'] = event.get('source.address', '')
            ev['ActivityID'] = event.get('data.ActivityID', ev['SessionID'])
            if ev['ActivityID'] not in aID.keys():
                aID[ev['ActivityID']] = []
            aID[ev['ActivityID']].append(ev)

        for result in self.extractRDP(aID, sorted(power_ev, key=lambda k: k['TimeCreated'])):
            yield result

    def extractRDP(self, aID, power_ev):

        for eventlist in aID.values():
            act = dict()
            written = True
            act['LoginDate'] = '-'
            act['LogoffDate'] = '-'
            act['User'] = ''
            act['SourceAddress'] = ''
            act['Comments'] = ''
            length = len(eventlist) - 1

            for e, v in enumerate(sorted(eventlist, key=lambda k: k['TimeCreated'])):
                # self.logger().debug("%s %s" % (v['TimeCreated'], v['EventID']))

                if written:  # New login
                    if v['EventID'] in ('21', '22', '25'):
                        if act['SourceAddress'] == '':
                            act['SourceAddress'] = v.get('SourceAddress', '')
                        act['User'] = v.get('User', '')
                        act['LoginDate'] = v['TimeCreated']
                        written = False
                        if v['EventID'] == '25':
                            act['Comments'] += "Reconnection."

                else:
                    if v['EventID'] in '21':  # opened session without close before
                        dt, reason = self.find_poweroff(act['LoginDate'], v['TimeCreated'], power_ev)
                        act['LogoffDate'] = dt
                        if reason == 'poweroff':
                            act['Comments'] += "Poweroff or restart."
                        elif reason == 'poweron':
                            act['Comments'] += "Start event, possibly caused by an unexpected poweroff"
                        else:
                            act['Comments'] += "Unknown date"
                        written = True
                        yield {
                            'LoginDate': act.get('LoginDate', '-'),
                            'LogoffDate': act.get('LogoffDate', '-'),
                            'User': act.get('User', ''),
                            'SourceAddress': act.get('SourceAddress', ''),
                            'Comments': act.get('Comments', '')
                        }
                        act['LoginDate'] = '-'
                        act['LogoffDate'] = '-'
                        act['User'] = ''
                        act['SourceAddress'] = ''
                        act['Comments'] = ''
                    elif v['EventID'] in ('23', '24'):
                        act['LogoffDate'] = v['TimeCreated']
                        yield {
                            'LoginDate': act.get('LoginDate', '-'),
                            'LogoffDate': act.get('LogoffDate', '-'),
                            'User': act.get('User', ''),
                            'SourceAddress': act.get('SourceAddress', ''),
                            'Comments': act.get('Comments', '')
                        }
                        # self.logger().debug("%s %s" % (act['LoginDate'], act['LogoffDate']))
                        act['LoginDate'] = '-'
                        act['LogoffDate'] = '-'
                        act['User'] = ''
                        act['SourceAddress'] = ''
                        act['Comments'] = ''
                        written = True
                if length == e and not written:
                    yield {
                            'LoginDate': act.get('LoginDate', '-'),
                            'LogoffDate': act.get('LogoffDate', '-'),
                            'User': act.get('User', ''),
                            'SourceAddress': act.get('SourceAddress', ''),
                            'Comments': act.get('Comments', '')
                        }

    def find_poweroff(self, previous_time, actual_time, power_ev):
        """ Finds date of poweroff or poweron as logout date """

        for ev in power_ev:
            if actual_time > ev['TimeCreated'] > previous_time:
                if ev['EventID'] == "13":
                    return (ev['TimeCreated'], 'poweroff')
                else:
                    return (ev['TimeCreated'], 'poweron')
        return (actual_time, 'unknown')


class RDPGateway(base.job.BaseModule):
    """ Extracts events related to incoming RDP connections """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        ev = dict()
        users_date = dict()
        user = ''
        for v in sorted(self.from_module.run(path), key=lambda k: k['event.created']):
            ev['EventID'] = v.get('event.code', '')

            if ev['EventID'] not in ('302', '303'):
                continue

            ev['TimeCreated'] = v.get('event.created', '')
            ev['User'] = v.get('UserData', {}).get('EventInfo', {}).get('Username', '')
            ev['Protocol'] = v.get('UserData', {}).get('EventInfo', {}).get('ConnectionProtocol', '')
            ev['SourceAddress'] = v.get('UserData', {}).get('EventInfo', {}).get('IpAddress', '')
            ev['SessionDuration'] = v.get('UserData', {}).get('EventInfo', {}).get('SessionDuration', '')
            ev['DestinationAddress'] = v.get('UserData', {}).get('EventInfo', {}).get('Resource', '')
            user = ev['User']

            if ev['EventID'] in ('302'):
                users_date[user] = ev['TimeCreated']

            elif ev['EventID'] in ('303') and users_date.get(user, '-') != '-':
                ev['LogoffDate'] = ev['TimeCreated']
                if str(ev['SessionDuration']) == '0':
                    continue
                yield {
                   'LoginDate': users_date.get(user, '-'),
                   'LogoffDate': ev.get('LogoffDate', '-'),
                   'User': ev.get('User', ''),
                   'SourceAddress': ev.get('SourceAddress', ''),
                   'SessionDuration': ev.get('SessionDuration', ''),
                   'Protocol': ev.get('Protocol', ''),
                   'DestinationAddress': ev.get('DestinationAddress', '')
                }
                # self.logger().debug("%s %s" % (ev['LoginDate'], ev['LogoffDate']))
                users_date[user] = '-'
                ev['LogoffDate'] = '-'
                ev['User'] = ''
                ev['SourceAddress'] = ''


class RDPOutgoing(base.job.BaseModule):
    """ Extracts events related to outgoing RDP connections """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml
        """

        self.check_params(path, check_path=True, check_path_exists=True)
        # RDP Outgoing events display only user SID. Get user name
        # TODO: events.json should have a way to identify partition
        partition = None
        os_info = CharacterizeWindows(config=self.config)
        users_sid = os_info.get_users_names(partition=partition)
        actID = {}

        for event in self.from_module.run(path):
            ev = dict()
            ev['TimeCreated'] = event.get('event.created', '')
            ev['EventID'] = event.get('event.code', '')
            ev['Description'] = event.get('message', '')
            ev['ActivityID'] = event.get('data.ActivityID', '')
            ev['Address'] = event.get('destination.address', '')
            ev['user.id'] = event.get('user.id', '')
            ev['User'] = users_sid.get(ev['user.id'], ev['user.id'])
            ev['B64Hash'] = event.get('data.Base64Hash', '')

            if ev['ActivityID'] not in actID.keys():
                actID[ev['ActivityID']] = []
            actID[ev['ActivityID']].append(ev)

        for result in self.extractRDP(actID):
            yield result

    def extractRDP(self, actID):

        for eventlist in actID.values():
            act = dict()
            writted = True
            act['LoginDate'] = '-'
            act['LogoffDate'] = '-'

            for v in sorted(eventlist, key=lambda k: k['TimeCreated']):
                # self.logger().debug("%s %s %s" % (v['TimeCreated'], v['EventID'], v['ActivityID']))
                if 'SID' not in act.keys() and 'user.id' in v.keys():
                    act['SID'] = v['user.id']
                    act['User'] = v['User']
                if v['EventID'] in ('1024', '1102'):
                    act['Address'] = v['Address']
                elif v['EventID'] == '1025':
                    act['LoginDate'] = v['TimeCreated']
                    writted = False
                elif v['EventID'] == '1026' and act['LoginDate'] != '-':
                    act['LogoffDate'] = v['TimeCreated']
                    yield {
                        'LoginDate': act.get('LoginDate', '-'),
                        'LogoffDate': act.get('LogoffDate', '-'),
                        'Address': act.get('Address', ''),
                        'SID': act.get('SID', '-'),
                        'User': act.get('User', '-'),
                        'B64Hash': act.get('B64Hash', '')
                    }
                    # self.logger().debug("%s %s" % (act['LoginDate'], act['LogoffDate']))
                    act['LoginDate'] = '-'
                    act['LogoffDate'] = '-'
                    writted = True
                elif v['EventID'] == '1029' and 'B64Hash' not in act.keys():
                    act['B64Hash'] = v.get('B64Hash', '')
            if not writted:
                yield {
                    'LoginDate': act.get('LoginDate', '-'),
                    'LogoffDate': act.get('LogoffDate', '-'),
                    'Address': act.get('Address', ''),
                    'SID': act.get('SID', '-'),
                    'User': act.get('User', '-'),
                    'B64Hash': act.get('B64Hash', '')
                }


class Poweron(base.job.BaseModule):
    """ Extracts events of parsed Security.evtx

    Events should be sorted"""

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        eventlist = []
        unexpected = []
        self.path = path

        for event in self.from_module.run(path):
            ev = dict()
            ev['TimeCreated'] = event.get('event.created', '')
            ev['EventID'] = event.get('event.code', '')
            ev['message'] = event.get('message', '')
            ev['Reason'] = event.get('ReasonStr', '')
            eventlist.append(ev)
            if ev['EventID'] == '41':
                temp = datetime.datetime.strptime(ev['TimeCreated'][:19], '%Y-%m-%d %H:%M:%S')
                temp -= datetime.timedelta(minutes=1)
                unexpected.append(temp.strftime('%Y-%m-%d %H:%M:%S'))
            yield ev
        if len(unexpected) > 0:
            for g in self.guess_poweroff(sorted(unexpected)):
                ev = {'TimeCreated': g,
                      'EventID': '',
                      'message': 'Possible unexpected poweroff',
                      'Reason': ''}
                eventlist.append(ev)
                yield ev
        # self.extractPower(sorted(eventlist, key=lambda d: d['TimeCreated']))

    def extractPower(self, events):
        """
        """
        results = []
        act = dict()
        inpower = False
        for ev in events:
            if ev['EventID'] == '1':
                if not inpower:
                    results.append([act.get('t0', '-'), 'Resume from sleep', act.get('t1', '-')])
                    act = {}
                inpower = True
                act['t0'] = ev['TimeCreated']
                act['d0'] = 'Sleep'
            elif ev['EventID'] == '12':
                if not inpower:
                    results.append([act.get('t0', '-'), 'Boot', act.get('t1', '-')])
                    act = {}
                inpower = True
                act['t0'] = ev['TimeCreated']
                act['d0'] = 'StartBoot'
            elif ev['EventID'] == '13':
                inpower = False
                act['t1'] = ev['TimeCreated']
                act['d1'] = 'Shutdown'
                results.append([act.get('t0', '-'), 'Shut down', act.get('t1', '-')])
                act = {}
            elif ev['EventID'] == '':
                if not inpower:
                    results.append([act.get('t0', '-'), 'Unexpected shutdown', '-'])
                    act = {}
                inpower = True
                act['t0'] = ev['TimeCreated']
                act['d0'] = 'Unexpected reboot'
            elif ev['EventID'] == '42':
                results.append([act.get('t0', '-'), 'Sleeping', act.get('t1', '-')])
                inpower = False
                act['t1'] = ev['TimeCreated']
                act['d1'] = 'Sleeping'
                act = {}

    def guess_poweroff(self, unexpected):
        guess = [""]
        m = len(unexpected)
        i = 0
        import subprocess

        cmd = "grep -o '\"event.created\": \"20..-..-.....:..:..' %s|sort -u|cut -b 19-" % self.path
        output = subprocess.check_output(cmd, shell=True).decode()
        for line in output.split('\n'):
            if unexpected[i] > line:
                guess[i] = line
            else:
                i += 1
                if i == m:
                    return guess
                guess.append(line)


class Hash(base.job.BaseModule):
    """ Extracts events containing file hashes """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed events.json
        """

        #self.check_params(path, check_path=True, check_path_exists=True)

        for event in self.from_module.run(path):
            if event['event.code'] == '2050' and event['event.provider'] == 'Microsoft-Windows-Windows Defender':
                event_name = self.get_event_name(event['event.code'], event['event.provider'])
                yield {
                    '@timestamp': event['event.created'],
                    'artifact': event_name,
                    'path': event['EventData']['Filename'],
                    'file_birth': '',
                    'file_modified': '',
                    'hash': event['EventData']['Sha256']                
                    }
                
            if event['event.provider'] == 'Microsoft-Windows-AppLocker':
                if event['event.code'] in ['8002','8004','8005']:
                    event_name = self.get_event_name(event['event.code'], event['event.provider'])
                    yield {
                        '@timestamp': event['event.created'],
                        'artifact': event_name,
                        'path': event['UserData']['RuleAndFileData']["FullFilePath"],
                        'file_birth': '',
                        'file_modified': '',
                        'hash': event['UserData']['RuleAndFileData']['FileHash']                
                        }
            
            if event['event.provider'] == 'Microsoft-Windows-Sysmon':
                event_name = self.get_event_name(event['event.code'], event['event.provider'])
                if event['event.code'] in ['1']:
                    string_hashes = event['EventData']['Hashes']
                    hash_value = self.get_dict_hashes(string_hashes)

                    yield {
                        '@timestamp': event['event.created'],
                        'artifact': event_name,
                        'path': event['EventData']['Image'],
                        'file_birth': '',
                        'file_modified': '',
                        'hash': hash_value                
                        }
                    
                if event['event.code'] in ['6']:
                    string_hashes = event['EventData']['Hashes']
                    hash_value = self.get_dict_hashes(string_hashes)

                    yield {
                        '@timestamp': event['event.created'],
                        'artifact': event_name,
                        'path': event['EventData']['ImageLoaded'],
                        'file_birth': '',
                        'file_modified': '',
                        'hash': hash_value                
                        }

                if event['event.code'] in ['15']:
                    string_hashes = event['EventData']['Hash']
                    hash_value = self.get_dict_hashes(string_hashes)

                    yield {
                        '@timestamp': event['event.created'],
                        'artifact': event_name,
                        'path': event['EventData']['TargetFilename'],
                        'file_birth': event['event.created'],
                        'file_modified': '',
                        'hash': hash_value                
                        }
    
    def get_dict_hashes(self, string_hashes):
        hash_pairs = string_hashes.split(",")
        hash_dict = {}
        for hash_pair in hash_pairs:
            algorithm, hash_value = hash_pair.split('=')
            hash_dict[algorithm] = hash_value

        if "SHA256" in hash_dict.keys():
            hash_value = hash_dict["SHA256"]
        elif "MD5" in hash_dict.keys():
            hash_value = hash_dict["MD5"]
        else:
            hash_value = string_hashes

        return hash_value
    
    def get_event_name(self, event_code, event_provider):
        
        return "event-" + str(event_code) + "-" + str(event_provider.split("-")[2])


class Network(base.job.BaseModule):
    """ Extracts events related with wireless networking

    Events should be sorted"""

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        net_up = []
        net_down = []

        selected_fields = {"event.created": "Created",
                           "event.code": "Code",
                           "data.SSID": "SSID",
                           "data.BSSID": "BSSID",
                           "data.ConnectionId": "ConnectionId",
                           "data.ProfileName": "ProfileName",
                           "data.PHYType": "PHYType",
                           "data.AuthenticationAlgorithm": "AuthenticationAlgorithm",
                           "data.Reason": "Reason"}
        for event in self.from_module.run(path):
            yield {field2: event.get(field, '-') for field, field2 in selected_fields.items()}

            if event["event.code"] == "8003":
                net_down.append(event)
            elif event["event.code"] == "8001":
                net_up.append(event)

        results = []

        for e in net_up:
            flag = True
            for ev in net_down:
                if ev['data.ConnectionId'] == e['data.ConnectionId'] and ev['event.created'] > e['event.created']:
                    results.append({'WirelessUp': e['event.created'], 'WirelessDown': ev['event.created'], 'SSID': e.get('data.SSID', '-'), 'MAC': e.get('data.BSSID', '-'), 'Reason': ev.get('data.Reason', '-')})
                    flag = False
                    break
            if flag:
                results.append({'WirelessUp': e['event.created'], 'WirelessDown': '', 'SSID': e.get('data.SSID', '-'), 'MAC': e.get('data.BSSID', '-'), 'Reason': ''})
        save_md_table(results, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'network.md'),
                      fieldnames='WirelessUp WirelessDown SSID MAC Reason',
                      file_exists='OVERWRITE')


class USB(base.job.BaseModule):
    """ Extracts events related with usb plugs

    Events should be sorted"""

    def run(self, path=None):
        """ Extracts USB sticks' plugins and plugoffs data """

        PluginsIds = ('2003', '2010')
        PlugoffsIds = ('2100', '2101')
        plugins = []
        plugoffs = []

        results = []

        for event in self.from_module.run(path):
            yield event

            if event['event.code'] in PluginsIds and self.check(event, 0, plugins, plugoffs):
                plugins.append(event)
            elif event['event.code'] in PlugoffsIds and self.check(event, 1, plugins, plugoffs):
                plugoffs.append(event)

        for e in plugins:
            flag = True
            for ev in plugoffs:
                if ev['data.Lifetime'] == e['data.Lifetime'] and ev['data.Instance'] == e['data.Instance'] and ev['event.created'] > e['event.created']:
                    results.append({'Plugin': e['event.created'], 'Plugoff': ev['event.created'], 'Device': e['data.Instance']})
                    flag = False
                    break
            if flag:
                results.append({'Plugin': e['event.created'], 'Plugoff': '', 'Device': e['data.Instance']})
        save_md_table(results, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'usb_plugs.md'),
                      fieldnames='Plugin Plugoff Device',
                      file_exists='OVERWRITE')

    def check(self, e, flag, plugins, plugoffs):
        """
        usb_main auxiliary function
        """
        if flag == 0:
            for event in plugins:
                if event['event.created'] == e['event.created'] and event["data.Instance"] == e["data.Instance"] and event["data.Lifetime"] == e["data.Lifetime"]:
                    return False  # already used
        else:
            for event in plugoffs:
                if event['event.created'] == e['event.created'] and event["data.Instance"] == e["data.Instance"] and event["data.Lifetime"] == e["data.Lifetime"]:
                    return False  # already used
            for evento in plugins:
                if event['event.created'] == e['event.created'] and event["data.Instance"] == e["data.Instance"] and event["data.Lifetime"] == e["data.Lifetime"]:
                    return False  # same time, does not used
        return True


class USBConnections(base.job.BaseModule):
    """ Extracts events related with usb plugs

    Events should be sorted"""

    def run(self, path=None):
        """ Extracts USB sticks' plugins and plugoffs data """
        # TODO: filter only USB devices on event 507

        plugins = []
        plugoffs = []
        results = []

        for event in self.from_module.run(path):
            if event['event.code'] == '1006' and not event['data.DeviceID'].startswith('USB'):
                continue
            yield event

            if event['event.action'] == "device-connected":
                plugins.append(event)
            else:
                plugoffs.append(event)

        # Delete unnecessary close events
        for plug_list in [plugins, plugoffs]:
            plug_list.sort(key=lambda k: k['event.created'])
            self.del_close_events(plug_list)

        all_plugs = plugins + plugoffs
        all_plugs.sort(key=lambda k: k['event.created'])
        for e in all_plugs:
            if 'data.DeviceID' not in e:
                e['data.DeviceID'] = ''
            results.append(e)
        save_md_table(results, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'usb_connections.md'),
                      fieldnames='event.created event.code event.action data.DeviceID',
                      file_exists='OVERWRITE')

    def del_close_events(self, ev_list, threshold=1000):
        # Delete unnecessary close events (threshold in milliseconds)
        previous_datetime = datetime.datetime.fromtimestamp(3333333333)
        total_plugins = len(ev_list)
        for index, e in enumerate(reversed(ev_list)):  # List is reversed so deleting an item does not skip the next iteration
            if e['event.code'] == '1006':
                continue
            if previous_datetime - datetime.datetime.strptime(e['event.created'], "%Y-%m-%d %H:%M:%S.%f %Z") < datetime.timedelta(milliseconds=1000):
                del ev_list[total_plugins - index - 1]


class USBDevice(object):

    def __init__(self, vendor, model, deviceID, serialN, capacity, volume=''):
        self.Vendor = vendor
        self.Model = model
        self.DeviceID = deviceID
        self.SerialNumber = serialN
        self.Capacity = capacity
        self.VolumeName = volume

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return (self.DeviceID == other.DeviceID or self.Model == other.Model) and self.SerialNumber == other.SerialNumber
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return str(self.SerialNumber) + self.Model

    def __hash__(self):
        return hash(str(self))

    def to_dict(self):
        return {'Vendor': self.Vendor, 'Model': self.Model, 'DeviceID': self.DeviceID, 'SerialNumber': self.SerialNumber, 'Capacity': self.Capacity}


class USBPlugs2(base.job.BaseModule):
    """ Extracts logon and rdp artifacts """

    def run(self, path=None):
        """
        Extracts information about disk plugs
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        plugs = {}
        devices = []

        for event in self.from_module.run(path):
            ev = dict()
            ev['TimeCreated'] = event.get('event.created', '')
            device = USBDevice(event.get('data.DeviceVendor', ''), event.get('data.DeviceModel', '').rstrip().lstrip(), event.get('data.DeviceID', ''), event.get('data.DeviceSerialNumber', ''), event.get('data.capacity', ''), event.get('data.DeviceVolumeName', ''))
            ev['Description'] = event.get('message', '')
            ev['action'] = event.get('event.action', '')
            ev['VolumeName'] = event.get('data.DeviceVolumeName', '')
            if device not in devices:  # device to put in list
                devices.append(device)
                plugs[device] = []
            else:
                index = devices.index(device)  # sometimes, capacity value is 0
                if devices[index].Capacity == '' or str(devices[index].Capacity) == "0":
                    devices[index].Capacity = event.get('data.capacity', '')
            plugs[device].append({'TimeCreated': ev['TimeCreated'], 'action': ev['action'], 'VolumeName': ev['VolumeName']})

        results = self.get_plugs(plugs)
        devices2 = []
        for dev in devices:
            devices2.append(dev.to_dict())

        save_md_table(results, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'usb_plugs2.md'),
                      fieldnames='plugged_in plugged_off Vendor Model SerialNumber VolumeName',
                      file_exists='OVERWRITE')
        save_md_table(devices2, config=None,
                      outfile=os.path.join(os.path.dirname(self.myconfig('outfile')), 'usb_info.md'),
                      fieldnames='DeviceID Vendor Model SerialNumber Capacity',
                      backticks_fields='DeviceID',
                      file_exists='OVERWRITE')
        return results

    def get_plugs(self, usb_dict):

        for device in usb_dict.keys():
            usb_id = sorted(usb_dict[device], key=lambda d: d['TimeCreated'])
            flag = False
            plugged_in = '-'
            volume = ''
            for item in usb_id:
                if item['action'] == '':  # event with volume information
                    volume = item['VolumeName']
                elif item['action'] == 'device-connected':
                    if flag:
                        yield {'plugged_in': plugged_in, 'plugged_off': '-', 'Vendor': device.Vendor, 'Model': device.Model, 'SerialNumber': device.SerialNumber, 'VolumeName': volume}
                    flag = True
                    plugged_in = item['TimeCreated']
                else:
                    if not flag:
                        plugged_in = '-'
                    flag = False
                    yield {'plugged_in': plugged_in, 'plugged_off': item['TimeCreated'], 'Vendor': device.Vendor, 'Model': device.Model, 'SerialNumber': device.SerialNumber, 'VolumeName': volume}


class TGT_attack(base.job.BaseModule):
    """ Extracts possible TGT attacks """

    # TODO: convert prints to dict yields

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml
        """

        self.check_params(path, check_path=True, check_path_exists=True)

        ev = {'tgt': {}, 'tgs': {}, 'renew': {}}

        eventlist = {'4768': 'tgt', '4769': 'tgs', '4770': 'renew'}

        for event in list(self.from_module.run(path)):
            # ev = dict()
            # ev['EventID'] = event.get('event.code', '')
            # ev['TimeCreated'] = event.get('event.created', '')
            # ev['User'] = event.get('destination.user.name', '')
            # ev['Domain'] = event.get('destination.domain', '')
            # ev['Service'] = event.get('service.name', '')
            # ev['Encryption'] = event.get('data.TicketEncryptionType', '')
            # ev['SourceAddress'] = event.get('source.ip', '')
            if event['destination.user.name'] not in ev[eventlist[event['event.code']]].keys():
                ev[eventlist[event['event.code']]][event['destination.user.name']] = []
            ev[eventlist[event['event.code']]][event['destination.user.name']].append({'event.created': event['event.created'], 'service.name': event['service.name'], 'TicketEncryptionType': event['data.TicketEncryptionType'], 'ip': event['source.ip'], 'TicketOptions': event['data.TicketOptions'], 'status': event.get('data.Error', '')})

        tgt = {}
        tgs = {}
        renew = {}
        startdate = '2099-01-01'

        for k in ev['tgt']:
            tgt[k] = sorted(ev['tgt'][k], key=lambda l: l['event.created'])
            aux_date = tgt[k][0]['event.created']
            if aux_date < startdate:
                startdate = aux_date
        for k in ev['tgs']:
            tgs[k] = sorted(ev['tgs'][k], key=lambda l: l['event.created'])
            aux_date = tgs[k][0]['event.created']
            if aux_date < startdate:
                startdate = aux_date
        for k in ev['renew']:
            renew[k] = sorted(ev['renew'][k], key=lambda l: l['event.created'])
            aux_date = renew[k][0]['event.created']
            if aux_date < startdate:
                startdate = aux_date
        del ev

        print('First TGT or TGS event has date %s\n' % startdate)

        self.check_tgs_encryption(tgs)
        print('\n--------------------------------------\nTGS without previous TGT')
        self.check_tgt_before_ticket(tgt, tgs)
        print('\n--------------------------------------\nRenew of ticket without previous TGT')
        self.check_tgt_before_ticket(tgt, renew)

    def check_tgs_encryption(self, tgs):
        """
        Find TGS with RC4-HMAC encryption with Ticket Options 0x40810000, or TGS with DES encryption.

        Computer accounts are filtered to reduce the amount of 4769 events
        """

        for user in tgs.keys():
            for ticket in tgs[user]:
                if ticket['TicketEncryptionType'].startswith('DES-CBC'):
                    print('Possible kerberoast attack using deprecated encryption. Date: %s, user: %s, ip: %s, encryption %s, service name: %s, status: %s' % (ticket['event.created'], user, ticket['ip'], ticket['TicketEncryptionType'], ticket['service.name'], ticket['status']))
                elif ticket['TicketEncryptionType'] == 'RC4-HMAC' and ticket['TicketOptions'] == '0x40810000' and not user.split('@')[0].endswith('$'):
                    print('Possible kerberoast attack. Date: %s, user: %s, ip: %s, encryption RC4-HMAC, service name: %s, status: %s' % (ticket['event.created'], user, ticket['ip'], ticket['service.name'], ticket['status']))

    def check_tgt_before_ticket(self, tgt, tgs, hours=10):
        """
        Finds if there are a tgt ticket before tgs
        """

        for user in tgs.keys():
            for ticket in tgs[user]:
                valid = False
                tgt_user = user.split('@')[0]
                if tgt_user in tgt.keys():
                    for tgt_ticket in tgt[tgt_user]:
                        if tgt_ticket['ip'] == ticket['ip'] and tgt_ticket['event.created'] < ticket['event.created'] and (datetime.datetime.strptime(ticket['event.created'][:19], "%Y-%m-%d %H:%M:%S") - datetime.datetime.strptime(ticket['event.created'][:19], "%Y-%m-%d %H:%M:%S")).total_seconds() < 3600 * hours:
                            valid = True
                            break
                        if not valid:
                            print("There are no previous TGT for ticket created (or it has created more than %s hours before) on %s of user %s with service name %s, ip %s, status: %s" % (hours, ticket['event.created'], user, ticket['service.name'], ticket['ip'], ticket['status']))
                else:
                    print("There are no TGT ticket of user %s. This ticket is created on %s with service name %s, ip %s, status: %s" % (user, ticket['event.created'], ticket['service.name'], ticket['ip'], ticket['status']))

class MSSQL(base.job.BaseModule):
    """ Extracts events related with MSSQL """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to the parsed Application.evtx
        """

        import re

        self.check_params(path, check_path=True, check_path_exists=True)

        regex = re.compile("CLIENTE: (.*)\]")

        for event in self.from_module.run(path):

            if event['event.code'] == '18456':
                event['reason'] = event['reason'][1:]
                temp_address = regex.search(event['source.address'])
                event['source.address'] = temp_address.group(1)
            yield event
