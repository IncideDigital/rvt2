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
import base.job
import dateutil.parser


def writemd(outfile, fields, eventlist, sorted=True):
    """ writes md table sorting by first item and removing repeated rows
    Args:
        outfile (str): output filename
        fields (list): list of fields
        eventlist(list of lists): list of rows of table
    """
    fields_len = len(fields) - 1

    act = [''] * fields_len  # init variable
    with open(outfile, 'w') as fout:
        fout.write("|".join(fields))
        fout.write("\n")
        fout.write("|".join(["-"] * fields_len))
        fout.write("\n")
        for e in eventlist:
            repeated = True
            for i in range(fields_len):
                if e[i] != act[i]:
                    repeated = False
                act[i] = e[i]
            if repeated:
                continue
            fout.write("|".join(e))
            fout.write("\n")


class Filter_Events(base.job.BaseModule):
    """ Filters events for generating a csv file """

    def run(self, path=None):
        events = ast.literal_eval(self.config.config[self.config.job_name]['events_dict'])

        for event in self.from_module.run(path):
            if event['event.code'] in events.keys() and event['event.provider'] == events[event['event.code']]:
                yield event


class Logon_rdp(base.job.BaseModule):
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
            ev['Description'] = event.get('event.action', '')
            ev['ActivityID'] = event.get('data.ActivityID', )
            ev['SessionID'] = event.get('data.SessionID', '')
            ev['ConnType'] = event.get('data.ConnType', '')
            ev['LogonType'] = event.get('data.LogonType', '')
            ev['ProcessName'] = event.get('process.name', '')

            if "client.ip" in event.keys():
                ev['source.ip'] = event['client.ip']
            elif "source.ip" in event.keys():
                ev['source.ip'] = event['source.ip']
            elif "source.address" in event.keys():
                ev['source.ip'] = event['source.address']

            if "ConnectionName" in event.keys():
                ev['ConnectionName'] = event['data.ConnectionName']
            else:
                ev['ConnectionName'] = event.get('data.SessionName')
            if 'data.reasonStr' in event.keys():
                ev['reasonStr'] = event['data.reasonStr']
            elif 'data.Error' in event.keys():
                ev['reasonStr'] = event['data.Error']
            else:
                ev['reasonStr'] = event.get('data.Reason', '')
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
            if 'TargetLogonId' in event.keys():
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

    def __difTimestamp__(self, d1, d0):
        """ get seconds between dates in ISO format
        Args;
            d0 (str): date 1
            d1 (str); date 2
        Returs:
            int: absolute values of d1 -d0
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
                if "ConnectionName" in event.keys() and ev['ConnectionName'] == event['ConnectionName']:
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
            ln = len(eventlist)
            for e, v in enumerate(eventlist):
                if v['LogonType'] in ("3", "4", "5"):
                    continue
                if v['EventID'] == '4634':
                    results.append([logon, ip, v['TimeCreated'], v['TargetUser']])
                    logon = ''
                    ip = ''
                    continue
                if v['EventID'] == '4624':
                    logon = v['TimeCreated']
                    ip = v['source.ip']
                if e == ln:
                    results.append([logon, ip, v['TimeCreated'], v['TargetUser']])

        writemd(os.path.join(self.config.config[self.config.job_name]['outdir'], 'logon_offs.md'), ['Login', 'IP', 'Logoff', 'User', 'Reason'], results)

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
                    results.append([act.get('t0', '-'), act.get('subjectUser', ''), act.get('ip', ''), v['TimeCreated'], act.get('TargetUser', ''), act.get('reason', '')])
                    act = dict()
                    auxtime2 = v['TimeCreated']
                elif v['EventID'] in ('39', '40'):
                    act['reason'] = v['reasonStr']
                elif v['EventID'] in ('21', '25'):
                    if 't0' in act.keys() and act['t0'] not in ('', '-'):
                        if self.__difTimestamp__(v["TimeCreated"], act['t0']) < 1:  # login event repeated
                            continue
                        else:  # unfinished event
                            results.append([act.get('t0', '-'), act.get('subjectUser', ''), act.get('ip', ''), act.get('t1', ''), act.get('TargetUser', ''), act.get('reason', '')])
                    insession = True
                    act['t1'] = '-'
                    act['reason'] = ''
                    if 'subjectUser' not in act.keys():
                        act['subjectUser'] = ''
                    act['t0'] = v['TimeCreated']
                    act['ip'] = v['source.ip']
                    act['targetUser'] = v['User']
                    if self.__difTimestamp__(v['TimeCreated'], auxtime) < 2:
                        act['subjectUser'] = suser
                elif v['EventID'] == '1149':
                    act['TargetUser'] = v['TargetUser']
                    auxtime = v['TimeCreated']

            if ('t0' in act.keys() and act['t0'] not in ('', '-')) or ('t1' in act.keys() and act['t1'] not in ('', '-')):  # for writing unclosed event
                results.append([act.get('t0', '-'), act.get('subjectUser', ''), act.get('ip', ''), act.get('t1', '-'), act.get('TargetUser', ''), act.get('reason', '')])
        writemd(os.path.join(self.config.config[self.config.job_name]['outdir'], 'rdp.md'), ['Login', 'SubjecUser', 'IP', 'Logoff', 'User', 'Reason'], results)


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

        for event in self.from_module.run(path):
            ev = dict()
            ev['TimeCreated'] = event.get('event.created', '')
            ev['EventID'] = event.get('event.code', '')
            ev['Description'] = event.get('event.action', '')
            ev['reason'] = event.get('reasonStr', '')
            eventlist.append(ev)

            yield ev
        self.extractPower(eventlist)

    def extractPower(self, events):
        """
        """
        results = []
        act = dict()
        inpower = False
        for ev in events:
            if ev['EventID'] == '1':
                if not inpower:
                    results.append([act.get('t0', '-'), 'Resume from sleep', act['t1']])
                inpower = True
                act['t0'] = ev['TimeCreated']
                act['d0'] = 'Sleep'
            elif ev['EventID'] == '12':
                inpower = True
                act['t0'] = ev['TimeCreated']
                act['d0'] = 'StartBoot'
            elif ev['EventID'] == '13':
                inpower = False
                act['t1'] = ev['TimeCreated']
                act['d1'] = 'Shutdown'
                results.append([act.get('t0', '-'), 'Shut down', act['t1']])
            elif ev['EventID'] == '41':
                if not inpower:
                    results.append([act.get('t0', '-'), 'Unexpected shutdown', '-'])
                inpower = True
                act['t0'] = ev['TimeCreated']
                act['d0'] = 'Unexpected reboot'
            elif ev['EventID'] == '42':
                results.append([act.get('t0', '-'), 'Sleeping', act['t1']])
                inpower = False
                act['t1'] = ev['TimeCreated']
                act['d1'] = 'Sleeping'


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

        for event in self.from_module.run(path):
            yield event

            if event["event.code"] == "8003":
                net_down.append(event)
            elif event["event.code"] == "8001":
                net_up.append(event)

        results = []

        for e in net_up:
            flag = True
            for ev in net_down:
                if ev['ConnectionId'] == e['ConnectionId'] and ev['event.created'] > e['event.created']:
                    results.append([e['event.created'], ev['event.created'], e['SSID'], e['BSSID'], ev['Reason']])
                    flag = False
                    break
            if flag:
                results.append([e['event.created'], e['SSID'], e['BSSID']])
        writemd(os.path.join(self.config.config[self.config.job_name]['outdir'], 'network.md'), ['Wireless Up', 'Wireless Down', 'SSID', 'MAC', 'Reason'], results)


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
                if ev['lifetime'] == e['lifetime'] and ev['instance'] == e['instance'] and ev['event.created'] > e['event.created']:
                    results.append([e['event.created'], ev['event.created'], e['instance']])
                    flag = False
                    break
            if flag:
                results.append([e['event.created'], '', e['instance']])
        writemd(os.path.join(self.config.config[self.config.job_name]['outdir'], 'usb_plug.md'), ['Plugin', 'Plugoff', 'Device'], results)

    def check(self, e, flag, plugins, plugoffs):
        """
        usb_main auxiliary function
        """
        if flag == 0:
            for event in plugins:
                if event['event.created'] == e['event.created'] and event["instance"] == e["instance"] and event["lifetime"] == e["lifetime"]:
                    return False  # already used
        else:
            for event in plugoffs:
                if event['event.created'] == e['event.created'] and event["instance"] == e["instance"] and event["lifetime"] == e["lifetime"]:
                    return False  # already used
            for evento in plugins:
                if event['event.created'] == e['event.created'] and event["instance"] == e["instance"] and event["lifetime"] == e["lifetime"]:
                    return False  # same time, does not used
        return True
