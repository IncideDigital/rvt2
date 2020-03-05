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
from evtx import PyEvtxParser
import base.job
from plugins.common.RVT_files import GetFiles


class GetEvents(object):
    """ Extracts relevant event logs

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """

    def __init__(self, eventfile, config_file):
        """
        Attrs:
            path (str): Absolute path to the parsed Security.xml (from a Security hive)
        """

        with open(config_file) as logcfg:
            logtext = logcfg.read()
        self.data_json = json.loads(logtext)
        self.eventfile = eventfile

    def parse(self):
        parser = PyEvtxParser(self.eventfile)

        for record in parser.records_json():
            rec = json.loads(record['data'])['Event']
            data = {}
            # Common fields
            data['event.created'] = record.get('timestamp', rec['System']['TimeCreated']['#attributes']['SystemTime'])
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
            if not data['event.code'] in self.data_json.keys() or data['event.provider'] != self.data_json[data['event.code']]['provider']:
                # EventData, UserData are just reproduced as dictionaries
                if 'EventData' in rec:
                    data['EventData'] = rec['EventData']
                if 'UserData' in rec:
                    data['UserData'] = rec['UserData']
                yield data
                continue

            # Selected events
            data['description'] = self.data_json[data['event.code']]["description"]
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

                if 'Name' in act.keys() and type(act['Name']) == list:
                    for item in act['Name']:
                        if 'transform' in act.keys() and item in act['transform'].keys():
                            name = str(act['transform'][item])
                        else:
                            name = 'data.{}'.format(str(item))
                        try:
                            data[name] = str(ev[item])
                        except Exception:
                            pass
                else:
                    if 'transform' in act.keys() and p in act['transform'].keys():
                        name = str(act['transform'][p])
                    else:
                        name = 'data.{}'.format(str(p))
                    try:
                        data[name] = str(ev[p])
                    except Exception:
                        pass
                    break


class EventJob(base.job.BaseModule):
    """ Base class to parse event log sources """

    def get_evtx(self, path, regex_search):
        """ Retrieve the evtx file to parse.
        Take 'path' if is defined and exists.
        Otherwise take first coincidence of the corresponding evtx file in the filesystem

        Attrs:
            path: path to evtx as defined in job
            regex_search: regex expression to search in file system allocated files

        """
        if path:
            if os.path.exists(path):
                return path
            else:
                raise base.job.RVTError('path {} does not exist'.format(path))

        alloc_files = GetFiles(self.config, vss=self.myflag("vss"))

        evtx_files = alloc_files.search(regex_search)
        if len(evtx_files) < 1:
            self.logger().info("{} matches not found in filesystem".format(regex_search))
            return ''
        if len(evtx_files) > 1:
            self.logger().warning("More than one file matches {}. Only parsing the file {}".format(regex_search, evtx_files[0]))

        return os.path.join(self.myconfig('casedir'), evtx_files[0])


class ParseEvents(EventJob):
    """ Extracts events of default evtx logs """

    def run(self, path=None):
        """
        Attrs:
            path (str): Absolute path to evtx file
        """

        json_file = self.config.config[self.config.job_name]['json_conf']

        path = self.get_evtx(path, os.path.basename(json_file).replace('json', 'evtx'))
        if not path:
            return []

        for ev in GetEvents(path, json_file).parse():
            yield ev


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
        category_id = {"%%8272": "System",
                       "%%8273": "Logon/Logoff",
                       "%%8274": "Object_Access",
                       "%%8275": "Privilege_Use",
                       "%%8276": "Detailed_Tracking",
                       "%%8277": "Policy_Change",
                       "%%8278": "Account_Management",
                       "%%8279": "DS_Access",
                       "%%8280": "Account_Logon"}

        subcategory_guid = {"{0CCE9213-69AE-11D9-BED3-505054503030}": "IPsec Driver",
                            "{0CCE9212-69AE-11D9-BED3-505054503030}": "System Integrity",
                            "{0CCE9211-69AE-11D9-BED3-505054503030}": "Security System Extension",
                            "{0CCE9210-69AE-11D9-BED3-505054503030}": "Security State Change",
                            "{0CCE9214-69AE-11D9-BED3-505054503030}": "Other System Events",
                            "{0CCE9243-69AE-11D9-BED3-505054503030}": "Network Policy Server",
                            "{0CCE921C-69AE-11D9-BED3-505054503030}": "Other Logon/Logoff",
                            "{0CCE921B-69AE-11D9-BED3-505054503030}": "Special Logon",
                            "{0CCE921A-69AE-11D9-BED3-505054503030}": "IPsec Extended Mode",
                            "{0CCE9219-69AE-11D9-BED3-505054503030}": "IPsec Quick Mode",
                            "{0CCE9218-69AE-11D9-BED3-505054503030}": "IPsec Main Mode",
                            "{0CCE9217-69AE-11D9-BED3-505054503030}": "Account Lockout",
                            "{0CCE9216-69AE-11D9-BED3-505054503030}": "Logoff",
                            "{0CCE9215-69AE-11D9-BED3-505054503030}": "Logon",
                            "{0CCE9223-69AE-11D9-BED3-505054503030}": "Handle Manipulation",
                            "{0CCE9244-69AE-11D9-BED3-505054503030}": "Detailed File Share",
                            "{0CCE9227-69AE-11D9-BED3-505054503030}": "Other Object Access",
                            "{0CCE9226-69AE-11D9-BED3-505054503030}": "Filtering Platform Connection",
                            "{0CCE9225-69AE-11D9-BED3-505054503030}": "Filtering Platform Packet Drop",
                            "{0CCE9224-69AE-11D9-BED3-505054503030}": "File Share",
                            "{0CCE9222-69AE-11D9-BED3-505054503030}": "Application Generated",
                            "{0CCE9221-69AE-11D9-BED3-505054503030}": "Certification Services",
                            "{0CCE9220-69AE-11D9-BED3-505054503030}": "SAM",
                            "{0CCE921F-69AE-11D9-BED3-505054503030}": "Kernel Object",
                            "{0CCE921E-69AE-11D9-BED3-505054503030}": "Registry",
                            "{0CCE921D-69AE-11D9-BED3-505054503030}": "File System",
                            "{0CCE9229-69AE-11D9-BED3-505054503030}": "Non Sensitive Privilege Use",
                            "{0CCE922A-69AE-11D9-BED3-505054503030}": "Other Privilege Use",
                            "{0CCE9228-69AE-11D9-BED3-505054503030}": "Sensitive Privilege Use",
                            "{0CCE922D-69AE-11D9-BED3-505054503030}": "DPAPI Activity",
                            "{0CCE922C-69AE-11D9-BED3-505054503030}": "Process Termination",
                            "{0CCE922B-69AE-11D9-BED3-505054503030}": "Process Creation",
                            "{0CCE922E-69AE-11D9-BED3-505054503030}": "RPC Events",
                            "{0CCE9232-69AE-11D9-BED3-505054503030}": "MPSSVC Rule-Level Policy Change",
                            "{0CCE9234-69AE-11D9-BED3-505054503030}": "Other Policy Change Events",
                            "{0CCE9233-69AE-11D9-BED3-505054503030}": "Filtering Platform Policy Change",
                            "{0CCE922F-69AE-11D9-BED3-505054503030}": "Audit Policy Change",
                            "{0CCE9231-69AE-11D9-BED3-505054503030}": "Authorization Policy Change",
                            "{0CCE9230-69AE-11D9-BED3-505054503030}": "Authentication Policy Change",
                            "{0CCE923A-69AE-11D9-BED3-505054503030}": "Other Account Management Events",
                            "{0CCE9239-69AE-11D9-BED3-505054503030}": "Application Group Management",
                            "{0CCE9238-69AE-11D9-BED3-505054503030}": "Distribution Group Management",
                            "{0CCE9237-69AE-11D9-BED3-505054503030}": "Security Group Management",
                            "{0CCE9236-69AE-11D9-BED3-505054503030}": "Computer Account Management",
                            "{0CCE9235-69AE-11D9-BED3-505054503030}": "User Account Management",
                            "{0CCE923E-69AE-11D9-BED3-505054503030}": "Detailed Directory Service Replication",
                            "{0CCE923B-69AE-11D9-BED3-505054503030}": "Directory Service Access",
                            "{0CCE923D-69AE-11D9-BED3-505054503030}": "Directory Service Replication",
                            "{0CCE923C-69AE-11D9-BED3-505054503030}": "Directory Service Changes",
                            "{0CCE9241-69AE-11D9-BED3-505054503030}": "Other Account Logon Events",
                            "{0CCE9240-69AE-11D9-BED3-505054503030}": "Kerberos Service Ticket Operations",
                            "{0CCE923F-69AE-11D9-BED3-505054503030}": "Credential Validation",
                            "{0CCE9242-69AE-11D9-BED3-505054503030}": "Kerberos Authentication Service",
                            "{0CCE9245-69AE-11D9-BED3-505054503030}": "Removable Storage",
                            "{0CCE9246-69AE-11D9-BED3-505054503030}": "Central Access Policy Staging",
                            "{0CCE9247-69AE-11D9-BED3-505054503030}": "User/Device Claims",
                            "{0CCE9248-69AE-11D9-BED3-505054503030}": "PNP Activity",
                            "{0CCE9249-69AE-11D9-BED3-505054503030}": "Group Membership"}

        audit_policy_changes = {"%%8448": "Success Removed",
                                "%%8449": "Success Added",
                                "%%8450": "Failure Removed",
                                "%%8451": "Failure Added"}

        # errordict for event 4625
        errordict = {"0xc000005e": "There are currently no logon servers available to service the logon request.",
                     "0xc0000064": "user name does not exist",
                     "0xc000006a": "user name is correct but the password is wrong",
                     "0xc000006d": "This is either due to a bad username or authentication information",
                     "0xc000006e": "Unknown user name or bad password.",
                     "0xc000006f": "user tried to logon outside his day of week or time of day restrictions",
                     "0xc0000070": "workstation restriction, or Authentication Policy Silo violation (look for event ID 4820 on domain controller)",
                     "0xc0000071": "expired password",
                     "0xc0000072": "account is currently disabled",
                     "0xc00000dc": "Indicates the Sam Server was in the wrong state to perform the desired operation.",
                     "0xc0000133": "clocks between DC and other computer too far out of sync",
                     "0xc0000193": "account expiration", "0xc0000234": "user is currently locked out",
                     "0xc000015b": "The user has not been granted the requested logon type (aka logon right) at this machine",
                     "0xc0000192": "An attempt was made to logon, but the netlogon service was not started.",
                     "0xc0000224": "user is required to change password at next logon",
                     "0xc0000225": "evidently a bug in Windows and not a risk",
                     "0xc0000234": "user is currently locked out",
                     "0xc00002ee": "Failure Reason: An Error occurred during Logon",
                     "0xc0000413": "Logon Failure: The machine you are logging onto is protected by an authentication firewall. The specified account is not allowed to authenticate to the machine."}

        LogonTypeStr = {'0': 'Unknown (0)',
                        '1': 'Unknown (empty)',
                        '2': 'Local',
                        '3': 'SMB',
                        '5': 'Service',
                        '7': 'Unlock',
                        '8': 'NetworkCleartext',
                        '9': 'NewCredentials',
                        '10': 'Remote',
                        '11': 'CachedInteractive',
                        '12': 'Cached remote interactive',
                        '13': 'Cached unlock'}

        json_file = self.config.config[self.config.job_name]['json_conf']

        for ev in GetEvents(path, json_file).parse():
            if "LogonType" in ev.keys():
                ev["LogonTypeStr"] = LogonTypeStr.get(ev["LogonType"], "Unknown")
            if "SubStatus" in ev.keys() and ev["SubStatus"] != "0x00000000":
                ev["Error"] = errordict.get(ev["SubStatus"], '')
            elif "Status" in ev.keys():
                ev["Error"] = errordict.get(ev["Status"], '')
            if "CategoryId" in ev.keys():
                ev["Category"] = category_id.get(ev["CategoryId"], "")
            if "SubcategoryGuid" in ev.keys():
                ev["Subcategory"] = subcategory_guid.get(ev["SubcategoryGuid"], "")
            if "AuditPolicyChanges" in ev.keys():
                temp_aud = []
                for i in ev["AuditPolicyChanges"].split(","):
                    temp_aud.append(audit_policy_changes.get(i.lstrip(), ""))
                ev["AuditPolicyChangesStr"] = ", ".join(temp_aud)
            yield ev


class System(EventJob):
    """ Extracts events of System.evtx """

    def run(self, path=None):
        """
        Attrs:
            path (str): Path to System.evtx
        """

        path = self.get_evtx(path, r"System.evtx$")
        if not path:
            return []

        reason_sleep = {"0": "Button or Lid",
                        "2": "Battery",
                        "7": "System Idle"}

        boot_type = {"0": "After full shutdown",
                     "1": "After hybrid shutdown",
                     "2": "Resumed from hibernation"}

        json_file = self.config.config[self.config.job_name]['json_conf']

        for ev in GetEvents(path, json_file).parse():
            if "BootType" in ev.keys():
                ev["BootTypeStr"] = boot_type.get(ev["BootType"], "Unknown")
            if "Reason" in ev.keys():
                ev["reasonStr"] = reason_sleep.get(ev.get('Reason'), 'Unknown')
            yield ev


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

        error_reason = {
            "": "",
            "0": "No additional information is available.",
            "1": "The disconnection was initiated by an administrative tool on the server in another session.",
            "2": "The disconnection was due to a forced logoff initiated by an administrative tool on the server in another session.",
            "3": "The idle session limit timer on the server has elapsed.",
            "4": "The active session limit timer on the server has elapsed.",
            "5": "Another user connected to the server, forcing the disconnection of the current connection.",
            "6": "The server ran out of available memory resources.",
            "7": "The server denied the connection.",
            "9": "The user cannot connect to the server due to insufficient access privileges.",
            "10": "The server does not accept saved user credentials and requires that the user enter their credentials for each connection.",
            "11": "The disconnection was initiated by the user disconnecting his or her session on the server or by an administrative tool on the server.",
            "12": "The disconnection was initiated by the user logging off his or her session on the server."}

        json_file = self.config.config[self.config.job_name]['json_conf']

        for ev in GetEvents(path, json_file).parse():
            if "Reason" in ev.keys():
                ev["reasonStr"] = error_reason.get(ev.get('Reason'), '')
            yield ev


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

        error_reason = {"0": "No error",
                        "1": "User-initiated client disconnect.",
                        "2": "User-initiated client logoff.",
                        "3": "Your Remote Desktop Services session has ended, possibly for one of the following reasons:  The administrator has ended the session. An error occurred while the connection was being established. A network problem occurred.",
                        "4": "The remote session ended because the total login time limit was reached. This limit is set by the server administrator or by network policies.",
                        "260": "Remote Desktop can't find the computer X. This might mean that X does not belong to the specified network.",
                        "262": "This computer can't connect to the remote computer.  Your computer does not have enough virtual memory available.",
                        "263": "The remote session was disconnected because the client prematurely ended the licensing protocol.",
                        "264": "This computer can't connect to the remote computer.  The two computers couldn't connect in the amount of time allotted.",
                        "516": "Remote Desktop can't connect to the remote computer for one of these reasons:  1) Remote access to the server is not enabled 2) The remote computer is turned off 3) The remote computer is not available on the network  Make sure the remote computer is turned on and connected to the network, and that remote access is enabled.",
                        "772": "This computer can't connect to the remote computer.  The connection was lost due to a network error.",
                        "1030": "Because of a security error, the client could not connect to the remote computer. Verify that you are logged on to the network, and then try connecting again.",
                        "1032": "The specified computer name contains invalid characters.",
                        "1796": "This computer can't connect to the remote computer.  Try connecting again.",
                        "1800": "Your computer could not connect to another console session on the remote computer because you already have a console session in progress.",
                        "2056": "The remote computer disconnected the session because of an error in the licensing protocol.",
                        "2308": "Your Remote Desktop Services session has ended.  The connection to the remote computer was lost, possibly due to network connectivity problems.",
                        "2311": "The connection has been terminated because an unexpected server authentication certificate was received from the remote computer.",
                        "2312": "A licensing error occurred while the client was attempting to connect (Licensing timed out).",
                        "2567": "The specified username does not exist.",
                        "2820": "This computer can't connect to the remote computer.  An error occurred that prevented the connection.",
                        "2822": "Because of an error in data encryption, this session will end.",
                        "2823": "The user account is currently disabled and cannot be used.",
                        "2825": "The remote computer requires Network Level Authentication, which your computer does not support.",
                        "3079": "A user account restriction (for example, a time-of-day restriction) is preventing you from logging on.",
                        "3080": "The remote session was disconnected because of a decompression failure at the client side.",
                        "3335": "As a security precaution, the user account has been locked because there were too many logon attempts or password change attempts.",
                        "3337": "The security policy of your computer requires you to type a password on the Windows Security dialog box. However, the remote computer you want to connect to cannot recognize credentials supplied using the Windows Security dialog box.",
                        "3590": "The client can't connect because it doesn't support FIPS encryption level.",
                        "3591": "This user account has expired.",
                        "3592": "Failed to reconnect to your remote session. Please try to connect again.",
                        "3593": "The remote PC doesn't support Restricted Administration mode.",
                        "3847": "This user account's password has expired. The password must change in order to logon.",
                        "3848": "A connection will not be made because credentials may not be sent to the remote computer.",
                        "4103": "The system administrator has restricted the times during which you may log in. Try logging in later.",
                        "4104": "The remote session was disconnected because your computer is running low on video resources.",
                        "4359": "The system administrator has limited the computers you can log on with. Try logging on at a different computer.",
                        "4615": "You must change your password before logging on the first time.",
                        "4871": "The system administrator has restricted the types of logon (network or interactive) that you may use.",
                        "5127": "The Kerberos sub-protocol User2User is required.",
                        "6919": "Remote Desktop cannot connect to the remote computer because the authentication certificate received from the remote computer is expired or invalid. In some cases, this error might also be caused by a large time discrepancy between the client and server computers.",
                        "7431": "Remote Desktop cannot verify the identity of the remote computer because there is a time or date difference between your computer and the remote computer.",
                        "9479": "Could not auto-reconnect to your applications,please re-launch your applications",
                        "9732": "Client and server versions do not match. Please upgrade your client software and then try connecting again.",
                        "33554433": "Failed to reconnect to the remote program. Please restart the remote program.",
                        "33554434": "The remote computer does not support RemoteApp.",
                        "50331649": "Your computer can't connect to the remote computer because the username or password is not valid.",
                        "50331650": "Your computer can't connect to the remote computer because it can't verify the certificate revocation list.",
                        "50331651": "Your computer can't connect to the remote computer due to one of the following reasons:  1) The requested Remote Desktop Gateway server address and the server SSL certificate subject name do not match. 2) The certificate is expired or revoked. 3) The certificate root authority does not trust the certificate.",
                        "50331652": "Your computer can't connect to the remote computer because the SSL certificate was revoked by the certification authority.",
                        "50331653": "This computer can't verify the identity of the RD Gateway X. It's not safe to connect to servers that can't be identified.",
                        "50331654": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server address requested and the certificate subject name do not match.",
                        "50331655": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server's certificate has expired or has been revoked.",
                        "50331656": "Your computer can't connect to the remote computer because an error occurred on the remote computer that you want to connect to.",
                        "50331657": "An error occurred while sending data to the Remote Desktop Gateway server. The server is temporarily unavailable or a network connection is down.",
                        "50331658": "An error occurred while receiving data from the Remote Desktop Gateway server. Either the server is temporarily unavailable or a network connection is down.",
                        "50331659": "Your computer can't connect to the remote computer because an alternate logon method is required. Contact your network administrator for assistance.",
                        "50331660": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server address is unreachable or incorrect.",
                        "50331661": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server is temporarily unavailable.",
                        "50331662": "Your computer can't connect to the remote computer because the Remote Desktop Services client component is missing or is an incorrect version.",
                        "50331663": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server is running low on server resources and is temporarily unavailable.",
                        "50331664": "Your computer can't connect to the remote computer because an incorrect version of rpcrt4.dll has been detected.",
                        "50331665": "Your computer can't connect to the remote computer because no smart card service is installed.",
                        "50331666": "Your computer can't stay connected to the remote computer because the smart card has been removed.",
                        "50331669": "Your computer can't connect to the remote computer because the user name or password is not valid.",
                        "50331671": "Your computer can't connect to the remote computer because a security package error occurred in the transport layer.",
                        "50331672": "The Remote Desktop Gateway server has ended the connection.",
                        "50331673": "The Remote Desktop Gateway server administrator has ended the connection.",
                        "50331674": "Your computer can't connect to the remote computer due to one of the following reasons:   1) Your credentials (the combination of user name, domain, and password) were incorrect. 2) Your smart card was not recognized.",
                        "50331675": "Remote Desktop can't connect to the remote computer X for one of these reasons:  1) Your user account is not listed in the RD Gateway's permission list 2) You might have specified the remote computer in NetBIOS format (for example, computer1), but the RD Gateway is expecting an FQDN or IP address format (for example, computer1.fabrikam.com or 157.60.0.1).",
                        "50331676": "Remote Desktop can't connect to the remote computer X for one of these reasons:  1) Your user account is not authorized to access the RD Gateway "" 2) Your computer is not authorized to access the RD Gateway "" 3) You are using an incompatible authentication method (for example, the RD Gateway might be expecting a smart card but you provided a password)",
                        "50331679": "Your computer can't connect to the remote computer because your network administrator has restricted access to this RD Gateway server.",
                        "50331680": "Your computer can't connect to the remote computer because the web proxy server requires authentication.",
                        "50331681": "Your computer can't connect to the remote computer because your password has expired or you must change the password.",
                        "50331682": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server reached its maximum allowed connections.",
                        "50331683": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server does not support the request.",
                        "50331684": "Your computer can't connect to the remote computer because the client does not support one of the Remote Desktop Gateway's capabilities.",
                        "50331685": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server and this computer are incompatible",
                        "50331687": "Your computer can't connect to the remote computer because your computer or device did not pass the Network Access Protection requirements set by your network administrator.",
                        "50331688": "Your computer can't connect to the remote computer because no certificate was configured to use at the Remote Desktop Gateway server.",
                        "50331689": "Your computer can't connect to the remote computer because the RD Gateway server that you are trying to connect to is not allowed by your computer administrator.",
                        "50331690": "Your computer can't connect to the remote computer because your computer or device did not meet the Network Access Protection requirements set by your network administrator, for one of the following reasons:  1) The Remote Desktop Gateway server name and the server's public key certificate subject name do not match. 2) The certificate has expired or has been revoked. 3) The certificate root authority does not trust the certificate. 4) The certificate key extension does not support encryption. 5) Your computer cannot verify the certificate revocation list.",
                        "50331695": "Your computer can't connect to the remote computer because authentication to the firewall failed due to missing firewall credentials.",
                        "50331696": "Your computer can't connect to the remote computer because authentication to the firewall failed due to invalid firewall credentials.",
                        "50331699": "The connection has been disconnected because the session timeout limit was reached.",
                        "50331700": "Your computer can't connect to the remote computer because an invalid cookie was sent to the Remote Desktop Gateway server.",
                        "50331701": "Your computer can't connect to the remote computer because the cookie was rejected by the Remote Desktop Gateway server.",
                        "50331703": "Your computer can't connect to the remote computer because the Remote Desktop Gateway server is expecting an authentication method different from the one attempted.",
                        "50331704": "The RD Gateway connection ended because periodic user authentication failed.",
                        "50331705": "The RD Gateway connection ended because periodic user authorization failed.",
                        "50331709": 'To use this program or computer, first log on to the following website: <a href=""></a>.',
                        "50331710": "To use this program or computer, you must first log on to an authentication website. Contact your network administrator for assistance.",
                        "50331711": 'Your session has ended. To continue using the program or computer, first log on to the following website: <a href=""></a>.',
                        "50331712": "Your session has ended. To continue using the program or computer, you must first log on to an authentication website.",
                        "50331713": "The RD Gateway connection ended because periodic user authorization failed. Your computer or device didn't pass the Network Access Protection (NAP) requirements set by your network administrator.",
                        "50331714": "Your computer can't connect to the remote computer because the size of the cookie exceeded the supported size.",
                        "50331717": "This computer cannot connect to the remote resource because you do not have permission to this resource.",
                        "50331724": "The user name you entered does not match the user name used to subscribe to your applications.",
                        "50331725": "Looks like there are too many users trying out the Azure RemoteApp service at the moment.",
                        "50331726": "Maximum user limit has been reached.",
                        "50331727": "Your trial period for Azure RemoteApp has expired.",
                        "50331728": "You no longer have access to Azure RemoteApp."}

        json_file = self.config.config[self.config.job_name]['json_conf']

        for ev in GetEvents(path, json_file).parse():
            if "Reason" in ev.keys() and ev["event.code"] == "39":
                ev['reasonStr'] = "SessionID {} disconnected by session {}".format(ev["SessionID"], ev["Source"])
            elif "Reason" in ev.keys() and ev["event.code"] == "1026":
                ev["reasonStr"] = error_reason.get(ev.get('Reason'), '')
            yield ev
