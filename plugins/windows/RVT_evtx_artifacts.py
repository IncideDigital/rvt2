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
import re
import csv
import lxml.etree
import base.job
from base.utils import check_directory


class EventList():

    events = []

    def getNodeData(self, node, data_list):
        """ Auxiliary function to get data from evtx

        Args:
            node (str): node string
            data_list (list): fields to extract
        Returns:
            dict: dict of data fields
        """
        if isinstance(node, str):
            a = lxml.etree.fromstring(node)
        else:
            a = node

        data = dict()

        for i in data_list:
            data[i] = ""

        for df in a:
            for sf in df:
                aux = sf.tag.split("}")[-1]
                if aux == "EventID":
                    data["EventID"] = sf.text
                elif aux == "Provider":
                    data["Provider"] = sf.attrib['Name']
                elif aux == "TimeCreated":
                    data["TimeCreated"] = sf.attrib['SystemTime'][:19]  # precision segundos
                elif 'Name' in sf.attrib.keys() and (not data_list or sf.attrib['Name'] in data_list):
                    data[sf.attrib['Name']] = sf.text
                elif "instance" in sf.attrib.keys():
                    data["instance"] = sf.attrib["instance"]
                    data["lifetime"] = sf.attrib["lifetime"]
                elif aux == "InstallDeviceID" or aux == "AddServiceID":
                    for sf2 in sf:
                        if sf2.tag.split("}")[-1] == "DeviceInstanceID":
                            data["DeviceInstanceID"] = sf2.text
                elif aux == "UMDFDeviceInstallBegin":
                    for sf2 in sf:
                        if sf2.tag.split("}")[-1] == "DeviceId":
                            data["DeviceInstanceID"] = sf2.text
                elif aux == "Data" and "Application" in data_list:
                    regex = re.compile(r"\[0\] ([^\[]*)\[1\] ([^[]*)")
                    if sf.text:
                        aux2 = regex.search(sf.text)
                    else:
                        continue
                    if aux2:
                        data["Application"] = aux2.group(1).rstrip().replace("\n", " ")
                elif aux == "EventXML":
                    for sf2 in sf:
                        if sf2.tag.split("}")[-1] == "User":
                            data["User"] = sf2.text
                        elif sf2.tag.split("}")[-1] == "SessionID":
                            data["SessionID"] = sf2.text
                        elif sf2.tag.split("}")[-1] == "Address":
                            data["Address"] = sf2.text
                        elif sf2.tag.split("}")[-1] == "Param1":
                            data["User"] = sf2.text
                        elif sf2.tag.split("}")[-1] == "Param2":
                            data["User"] = "{}\\{}".format(sf2.text, data['User'])
                        elif sf2.tag.split("}")[-1] == "Param3":
                            data["Address"] = sf2.text
        return data

    def parse_evtx(self, inputfile, eventIDs, data_list):
        """ Extracts data from evtx

        Args:
            inputfile (str): extx's path
            eventIDs (dict): dict of events to extract data with ID and Provider
            data_list (list): fields to extract (coma separated)
        Returns:
            dict: dict of data fields
        """
        if not os.path.isfile(inputfile):
            return {}
        try:
            with open(inputfile, "r", encoding="cp1252") as a:
                xml_text = a.read().encode("cp1252")
        except Exception:
            with open(inputfile, "r", encoding="iso8859-15") as a:
                xml_text = a.read().encode("iso8859-15")

        parser = lxml.etree.XMLParser(recover=True)  # to ignore ilegal chars
        a = lxml.etree.fromstring(xml_text, parser)

        if a is None:
            return {}

        for node in a:
            data = self.getNodeData(node, data_list)
            if data["EventID"] in eventIDs.keys() and data["Provider"].startswith(eventIDs[data["EventID"]]):
                self.events.append(data)

    def sort_events(self, uniq=True):
        """ Returns a sorted list of events"""

        lista = sorted(self.events, key=lambda k: k['TimeCreated'])
        lista2 = []
        aux = ""
        for item in lista:
            uniq = False
            for i, v in item.items():
                if aux == "" or aux.get(i, '') != v:
                    uniq = True
                    break
            if uniq:
                aux = item
                lista2.append(item)
        return lista2

    def replace_field_events(self, keyname, assoc):
        """ Replace values of a key

        Args:
            keyname (str): keyname field where replace values
            assoc (dict): dict with values to be replaced
        """

        for item in self.events:
            if keyname in item.keys() and item[keyname] in assoc.keys():
                item[keyname] = assoc[item[keyname]]

    def replace_field_name(self, keyname, newkey):
        """ Replace key name for other

        Args:
            keyname (str): keyname field to replace
            newkey (str): keyname to change
        """
        for item in self.events:
            if keyname in item.keys():
                item[newkey] = item[keyname]
                del item[keyname]

    def addEventIDDescription(self, eventID_assoc, fieldName="Description"):
        """ Add a fieldName key with description associated

        Args:
            eventID_assoc (dict): dictionary with description associated to an eventID
            fieldName (str): field name to add with the description
        """
        for item in self.events:
            if item["EventID"] in eventID_assoc.keys():
                item[fieldName] = eventID_assoc[item["EventID"]]

    def write_csv(self, output_file, items):

        with open(output_file, "w") as f_o:
            writer = csv.writer(f_o, delimiter=";", quotechar='"')
            writer.writerow(items)
            for e in self.sort_events():
                try:
                    writer.writerow([e[v] for v in items])
                except Exception:
                    pass  # some item is mistaken, skip entry

    def clearEvents(self):
        self.events = []


class Login(base.job.BaseModule, EventList):

    # Security.evtx
    # 4634   An account was logged off.
    # 4647   User initiated logoff.
    # 4624   An account was successfully logged on.
    # 4625   An account failed to log on.
    # 4648   A logon was attempted using explicit credentials.
    # 4675   SIDs were filtered.
    # 4649   A replay attack was detected.
    # 4778   A session was reconnected to a Window Station.
    # 4779   A session was disconnected from a Window Station.
    # 4800   The workstation was locked.
    # 4801   The workstation was unlocked.
    # 4802   The screen saver was invoked.
    # 4803   The screen saver was dismissed.
    # 5378   The requested credentials delegation was disallowed by policy.
    # 5632   A request was made to authenticate to a wireless network.
    # 5633   A request was made to authenticate to a wired network.
    # 4964   Special groups have been assigned to a new logon.

    # System.evtx
    # 12     The operating system started at system time
    # 13     The operating system is shutting down at system time
    # 41     The system has rebooted without cleanly shutting down first.
    # 42     The system is entering sleep.
    # 1074   is generated when an application causes the system to restart, or when the user initiates a restart or shutdown
    # 6005   The Event log service was started
    # 6006   The Event log service was stopped
    # 6008   The previous system shutdown at time on date was unexpected

    # Event 42 -> Reason 0 ->Button or Lid
    # Event 42 -> Reason 2 ->Battery
    # Event 42 -> Reason 7 ->System Idle

    # TODO: include RDP related event in system: 9009:The Desktop Window Manager has exited with code (<X>)

    def run(self, path=""):
        vss = self.myflag('vss')

        if not vss:
            self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
            self.outdir = self.myconfig('outdir')
            check_directory(self.indir, error_missing=True)
            check_directory(self.outdir, create=True)
            self.log_main()
            self.pow_main()
        else:
            self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir')
            self.outdir = self.myconfig('voutdir')
            check_directory(self.indir, error_missing=True)
            check_directory(self.outdir, create=True)
            try:
                for dir in os.listdir(self.indir):
                    self.log_main(dir)
                    self.pow_main(dir)
            except Exception:
                return []

        return []

    def log_main(self, vss_dir=""):
        """ Extracts logon and logoffs artifacts

        Logon error codes:
        Status:
        0XC0000234  user is currently locked out
        0XC0000193  account expiration
        0XC0000133  clocks between DC and other computer too far out of sync
        0XC0000224  user is required to change password at next logon
        0XC0000225  evidently a bug in Windows and not a risk
        0XC000015B  The user has not been granted the requested logon type (aka logon right) at this machine
        0XC000006D  This is either due to a bad username or authentication information
        0XC000006E  Unknown user name or bad password.
        0XC00002EE  Failure Reason: An Error occurred during Logon
        Substatus:
        0XC000005E  There are currently no logon servers available to service the logon request.
        0xC0000064  user name does not exist
        0xC000006A  user name is correct but the password is wrong
        0XC000006D  This is either due to a bad username or authentication information
        0XC000006E  Unknown user name or bad password.
        0xC0000071  expired password
        0xC0000072  account is currently disabled
        0xC000006F  user tried to logon outside his day of week or time of day restrictions
        0xC0000070  workstation restriction, or Authentication Policy Silo violation (look for event ID 4820 on domain controller)
        0XC00000DC  Indicates the Sam Server was in the wrong state to perform the desired operation.
        0xc000015b  The user has not been granted the requested logon type (aka logon right) at this machine
        0XC000018C  The logon request failed because the trust relationship between the primary domain and the trusted domain failed.
        0XC0000192  An attempt was made to logon, but the netlogon service was not started.
        0xC0000193  account expiration
        0xC0000133  clocks between DC and other computer too far out of sync
        0xC0000224  user is required to change password at next logon
        0xC0000225  evidently a bug in Windows and not a risk
        0xC0000234  user is currently locked out
        0XC0000413  Logon Failure: The machine you are logging onto is protected by an authentication firewall. The specified account is not allowed to authenticate to the machine.

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """
        eventos_login = {"4624": "Microsoft-Windows-Security-Auditing", "4625": "Microsoft-Windows-Security-Auditing",
                         "4634": "Microsoft-Windows-Security-Auditing", "4647": "Microsoft-Windows-Security-Auditing", "4648": "Microsoft-Windows-Security-Auditing"}
        data_list = ("EventID", "LogonType", "TargetLogonId", "TargetUserName", "IpAddress", "Status", "SubStatus")

        errordict = {"0xc000005e": "There are currently no logon servers available to service the logon request.", "0xc0000064": "user name does not exist",
                     "0xc000006a": "user name is correct but the password is wrong", "0xc000006d": "This is either due to a bad username or authentication information",
                     "0xc000006e": "Unknown user name or bad password.", "0xc000006f": "user tried to logon outside his day of week or time of day restrictions",
                     "0xc0000070": "workstation restriction, or Authentication Policy Silo violation (look for event ID 4820 on domain controller)", "0xc0000071": "expired password",
                     "0xc0000072": "account is currently disabled", "0xc00000dc": "Indicates the Sam Server was in the wrong state to perform the desired operation.",
                     "0xc0000133": "clocks between DC and other computer too far out of sync", "0xc0000193": "account expiration", "0xc0000234": "user is currently locked out",
                     "0xc000015b": "The user has not been granted the requested logon type (aka logon right) at this machine",
                     "0xc0000192": "An attempt was made to logon, but the netlogon service was not started.", "0xc0000224": "user is required to change password at next logon",
                     "0xc0000225": "evidently a bug in Windows and not a risk", "0xc0000234": "user is currently locked out", "0xc00002ee": "Failure Reason: An Error occurred during Logon",
                     "0xc0000413": "Logon Failure: The machine you are logging onto is protected by an authentication firewall. The specified account is not allowed to authenticate to the machine."}

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Security.txt")
            output_file = os.path.join(self.outdir, "logons_offs.csv")
            output_file2 = os.path.join(self.outdir, "logons_offs.md")

        else:
            inputfile = os.path.join(self.indir, vss_dir, "Security.txt")
            output_file = os.path.join(self.outdir, "logons_offs_%s.csv" % vss_dir)
            output_file2 = os.path.join(self.outdir, "logons_offs_%s.md" % vss_dir)

        LogonTypeStr = {'2': 'Local', '3': 'SMB', '5': 'Service', '7': 'Unlock', '8': 'NetworkCleartext', '9': 'NewCredentials', '10': 'Remote', '11': 'CachedInteractive'}
        LogonsIds = ('4624', '4648')
        LogoffsIds = ('4647', '4634')
        logons = []
        logoffs = []

        self.clearEvents()

        self.parse_evtx(inputfile, eventos_login, data_list)

        for e in self.events:
            if e["SubStatus"] in errordict.keys():
                e["Error"] = errordict[e["SubStatus"]]
            elif e["Status"] in errordict.keys():
                e["Error"] = errordict[e["Status"]]
            else:
                e["Error"] = ""
        events = self.sort_events()

        self.logger().info("Extracting logins and logoffs related information")
        self.write_csv(output_file, ["TimeCreated", "EventID", "LogonType", "TargetLogonId", "TargetUserName", "Error", "IpAddress"])

        self.replace_field_events("LogonType", LogonTypeStr)

        for e in events:
            if e['EventID'] in LogonsIds and 'TargetLogonId' in e:
                logons.append(e)
            elif e['EventID'] in LogoffsIds and 'TargetLogonId' in e:
                logoffs.append(e)

        # look at when logoff was done
        for e in logons:
            targetlogonid = e['TargetLogonId']
            if not e['LogonType'] == 'Unlock':  # < Unblock has a logoff associated at the same hour, but it has no sense to put it
                for lo in logoffs:
                    if 'TargetLogonId' in lo and lo['TargetLogonId'] == targetlogonid:
                        e['LogOff'] = lo
            # If LogonTypeStr is Remote, it is changed by IP
            if e['LogonType'] == 'Remote':
                try:
                    e['LogonTypeStr'] = e['IpAddress']
                except Exception:
                    self.logger().error(e)

        with open(output_file2, "w") as f_o2:
            f_o2.write('User|Logon|Type|Logoff\n')
            f_o2.write('--|--|--|--')
            for e in logons:
                if e['LogonType'] in ('SMB', 'Service', ''):
                    continue
                if 'TargetLogonId' not in e:
                    f_o2.write(e)
                if 'LogOff' in e:
                    f_o2.write("\n{}|{}|{}|{}".format(e['TargetUserName'], e['TimeCreated'],
                                                      e['LogonType'], e['LogOff']['TimeCreated']))
                else:
                    f_o2.write("\n{}|{}|{}|-".format(e['TargetUserName'], e['TimeCreated'], e['LogonType']))
        self.logger().info("Finished login logoff extraction")

    def pow_main(self, vss_dir=""):
        """ Extracts poweron and poweroffs artifacts

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """

        # <Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
        # <System>
        # <Provider Name="Microsoft-Windows-Kernel-Boot" Guid="{15CA44FF-4D7A-4BAA-BBA5-0998955E531E}" />
        # <EventID>27</EventID>
        # <Version>1</Version>
        # <Level>4</Level>
        # <Task>33</Task>
        # <Opcode>0</Opcode>
        # <Keywords>0x8000000000000000</Keywords>
        # <TimeCreated SystemTime="2019-04-04T10:30:41.8052Z" />
        # <EventRecordID>51505</EventRecordID>
        # <Correlation />
        # <Execution ProcessID="4" ThreadID="14564" />
        # <Channel>System</Channel>
        # <Computer>CASA</Computer>
        # <Security /></System>
        # <EventData>
        # <Data Name="BootType">1</Data>
        # <Data Name="LoadOptions">  e870:                                  00                         .
        # </Data></EventData></Event>

        #     Boot type:
        #     0x0 - Windows 10 was started after a full shutdown.
        #     0x1 - Windows 10 was started after a hybrid shutdown.
        #     0x2 - Windows 10 was resumed from hibernation.

        eventos_apagado = {"1": "Microsoft-Windows-Power-Troubleshooter", "12": "Microsoft-Windows-Kernel-General", "13": "Microsoft-Windows-Kernel-General", "27": "Microsoft-Windows-Kernel-Boot",
                           "41": "Microsoft-Windows-Kernel-Power", "42": "Microsoft-Windows-Kernel-Power", "1074": "User32", "6005": "EventLog", "6006": "EventLog", "6008": "EventLog"}
        data_list_apagado = ("EventID", "Reason", "BootType")

        if not vss_dir:
            inputfile = os.path.join(self.indir, "System.txt")
            output_file = os.path.join(self.outdir, "poweron_off.csv")
            output_file2 = os.path.join(self.outdir, "poweron_off.md")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "System.txt")
            output_file = os.path.join(self.outdir, "poweron_off_%s.csv" % vss_dir)
            output_file2 = os.path.join(self.outdir, "poweron_off_%s.md" % vss_dir)

        pow_event = {"1": "The system has resumed from Sleep", "12": "The operating system started", "13": "The operating system is shutting down", "27": "Boot event", "41": "The system has rebooted without cleanly shutting",
                     "42": "The system is entering sleep", "1074": "an application causes the system to restart, or user initiates a restart or shutdown",
                     "6005": "Event log service was started", "6006": "Event log service was stopped", "6008": "Previous system shutdown unexpected"}
        reason_sleep = {"0": "Button or Lid", "2": "Battery", "7": "System Idle"}
        boot_type = {"0": "After full shutdown", "1": "After hybrid shutdown", "2": "Resumed from hibernation"}

        self.clearEvents()

        self.parse_evtx(inputfile, eventos_apagado, data_list_apagado)
        self.addEventIDDescription(pow_event, "Description")
        self.replace_field_events("Reason", reason_sleep)
        self.replace_field_events("BootType", boot_type)
        self.replace_field_name("BootType", "Reason")

        events = self.sort_events()
        self.write_csv(output_file, ["TimeCreated", "EventID", "Description", "Reason"])

        lista = []

        fecha = ""
        self.logger().info("Extracting poweron and poweroff events information")
        for e in events:
            if e["EventID"] == "42":
                lista.append("{}|Sleep||".format(e["TimeCreated"]))
            elif e["EventID"] == "12":
                fecha = e["TimeCreated"]
            elif e["EventID"] == "13":
                if fecha != "":
                    lista.append("{}|Init|{}|Shutdown".format(fecha, e["TimeCreated"]))
                    fecha = ""
            elif e["EventID"] == "41":
                if fecha != "":
                    lista.append("{}|Init||Unexpected shutdown".format(fecha))
                    fecha = e["TimeCreated"]

        with open(output_file2, "w") as f_o2:
            f_o2.write('Date|Type|Date|Shutdown\n')
            f_o2.write('--|--|--|--')

            for i in sorted(lista):
                f_o2.write("\n" + i)

        self.logger().info("Poweron and poweroff extraction finished")


class Usb(base.job.BaseModule, EventList):

    def run(self, path=""):
        vss = self.myflag('vss')

        self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir') if vss else self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
        self.outdir = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(self.indir, error_missing=True)
        check_directory(self.outdir, create=True)

        if not vss:
            self.usb_main()
            self.usb_install()
        else:
            for dir in os.listdir(self.indir):
                self.usb_main(dir)
                self.usb_install(dir)
        return []

    def usb_main(self, vss_dir=""):
        """ Extracts USB sticks' plugins and plugoffs data

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """

        eventos_usb = {"2003": "Microsoft-Windows-DriverFrameworks-UserMode", "2010": "Microsoft-Windows-DriverFrameworks-UserMode",
                       "2100": "Microsoft-Windows-DriverFrameworks-UserMode", "2101": "Microsoft-Windows-DriverFrameworks-UserMode"}
        data_list_usb = ("EventID", "UMDFHostDeviceRequest")

        PluginsIds = ('2003', '2010')
        PlugoffsIds = ('2100', '2101')
        plugins = []
        plugoffs = []

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Microsoft-Windows-DriverFrameworks-UserMode%4Operational.txt")
            output_file = os.path.join(self.outdir, "usbdevices.csv")
            output_file2 = os.path.join(self.outdir, "usbdevices.md")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "Microsoft-Windows-DriverFrameworks-UserMode%4Operational.txt")
            output_file = os.path.join(self.outdir, "usbdevices_%s.csv" % vss_dir)
            output_file2 = os.path.join(self.outdir, "usbdevices_%s.md" % vss_dir)

        self.clearEvents()

        self.logger().info("Extracting pendrives plugs events")
        self.parse_evtx(inputfile, eventos_usb, data_list_usb)

        events = self.sort_events()
        self.write_csv(output_file, ["TimeCreated", "EventID", "lifetime", "instance"])
        lista = []

        self.logger().info("Extracting pendrives plugs events")
        for e in events:
            if e['EventID'] in PluginsIds and self.check(e, 0, plugins, plugoffs):
                plugins.append(e)
            elif e['EventID'] in PlugoffsIds and self.check(e, 1, plugins, plugoffs):
                plugoffs.append(e)

        with open(output_file2, "w") as f_o2:
            f_o2.write('Plugin|Plugoff|Device\n')
            f_o2.write('--|--|--')

            for e in plugins:
                flag = True
                for ev in plugoffs:
                    if ev['lifetime'] == e['lifetime'] and ev['instance'] == e['instance'] and ev['TimeCreated'] > e['TimeCreated']:
                        f_o2.write("\n{}|{}|{}".format(e['TimeCreated'], ev['TimeCreated'], e['instance']))
                        flag = False
                        break
                if flag:
                    f_o2.write("\n{}| |{}".format(e['TimeCreated'], e['instance']))

            for i in sorted(lista):
                f_o2.write("\n" + i)

    def usb_install(self, vss_dir=""):
        """ Extracts USB sticks' data about drivers installation

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """
        eventos_usb = {"20001": "Microsoft-Windows-UserPnp", "20003": "Microsoft-Windows-UserPnp", "10000": "Microsoft-Windows-DriverFrameworks-UserMode"}
        data_list_usb = ("EventID", "UMDFHostDeviceRequest")

        if not vss_dir:
            inputfile = os.path.join(self.indir, "System.txt")
            output_file = os.path.join(self.outdir, "usb_install_events.csv")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "System.txt")
            output_file = os.path.join(self.outdir, "usb_install_events_%s.csv" % vss_dir)

        self.logger().info("Extracting installation artifact of USB devices")

        self.clearEvents()
        self.parse_evtx(inputfile, eventos_usb, data_list_usb)

        events = self.sort_events()

        with open(output_file, "w") as f:
            f.write("Date|EventID|Device\n")
            for e in events:
                if re.search("usbstor", e['DeviceInstanceID'], re.I):
                    f.write("{}|{}|{}\n".format(e['TimeCreated'], e["EventID"], e['DeviceInstanceID']))

    def check(self, e, flag, plugins, plugoffs):
        """
        usb_main auxiliary function
        """
        if flag == 0:
            for evento in plugins:
                if evento["TimeCreated"] == e["TimeCreated"] and evento["instance"] == e["instance"] and evento["lifetime"] == e["lifetime"]:
                    return False  # already used
        else:
            for evento in plugoffs:
                if evento["TimeCreated"] == e["TimeCreated"] and evento["instance"] == e["instance"] and evento["lifetime"] == e["lifetime"]:
                    return False  # already used
            for evento in plugins:
                if evento["TimeCreated"] == e["TimeCreated"] and evento["instance"] == e["instance"] and evento["lifetime"] == e["lifetime"]:
                    return False  # same time, does not used
        return True


class Network(base.job.BaseModule, EventList):

    def run(self, path=""):
        vss = self.myflag('vss')

        if not vss:
            self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
            self.outdir = self.myconfig('outdir')
            check_directory(self.indir, error_missing=True)
            check_directory(self.outdir, create=True)
            self.network_events()
            self.shares()
        else:
            self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir')
            self.outdir = self.myconfig('voutdir')
            check_directory(self.indir, error_missing=True)
            check_directory(self.outdir, create=True)
            for dir in os.listdir(self.indir):
                self.network_events(dir)
                self.shares(dir)
        return []

    def network_events(self, vss_dir=""):
        """ Extracts network events from evtx

        Event ID:   8000, Description: WLAN AutoConfig service started a connection to a wireless network.
        Event ID:   8001, Description: WLAN AutoConfig service has successfully connected to a wireless network
        Event ID:   8003, Description: WLAN AutoConfig service has successfully disconnected from a wireless network
        Event ID: 11001, Description: Wireless network association succeeded.

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """
        eventos_network = {"8000": "Microsoft-Windows-WLAN-AutoConfig", "8001": "Microsoft-Windows-WLAN-AutoConfig",
                           "8003": "Microsoft-Windows-WLAN-AutoConfig", "11001": "Microsoft-Windows-WLAN-AutoConfig"}
        data_list_network = ("EventID", "ProfileName", "SSID", "BSSID", "PHYType", "AuthenticationAlgorithm", "ConnectionId", "ConnectionMode", "Reason", "PeerMac")

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Microsoft-Windows-WLAN-AutoConfig%4Operational.txt")
            output_file = os.path.join(self.outdir, "network_events.csv")
            output_file2 = os.path.join(self.outdir, "network_events.md")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "Microsoft-Windows-WLAN-AutoConfig%4Operational.txt")
            output_file = os.path.join(self.outdir, "network_events_%s.csv" % vss_dir)
            output_file2 = os.path.join(self.outdir, "network_events_%s.md" % vss_dir)

        self.logger().info("Extracting network events")

        self.clearEvents()
        try:
            self.parse_evtx(inputfile, eventos_network, data_list_network)
        except lxml.etree.XMLSyntaxError:
            self.logger().warning('Problems to read %s. Probably empty xml file' % inputfile)
            return

        self.write_csv(output_file, ['TimeCreated', "EventID", "SSID", "BSSID", "ConnectionId", "ProfileName", "PHYType", "AuthenticationAlgorithm", "Reason"])

        events = self.sort_events()

        net_up = []
        net_down = []

        for e in events:
            if e["EventID"] == "8003":
                net_down.append(e)
            elif e["EventID"] == "8001":
                net_up.append(e)

        with open(output_file2, "w") as f_o2:
            f_o2.write('Wireless Up|Wireless Down|SSID|MAC|Reason\n--|--|--|--|--\n')

            for e in net_up:
                flag = True
                for ev in net_down:
                    if ev['ConnectionId'] == e['ConnectionId'] and ev['TimeCreated'] > e['TimeCreated']:
                        f_o2.write("{}|{}|{}|{}|{}\n".format(e['TimeCreated'], ev['TimeCreated'], e['SSID'], e['BSSID'], ev['Reason']))
                        flag = False
                        break
                if flag:
                    f_o2.write("{}| |{}|{}|\n".format(e['TimeCreated'], e['SSID'], e['BSSID']))

    def shares(self, vss_dir=""):
        """ Extract network shared folder events
        Args:
                vss_dir (str): vss folder or empty for normal allocated file

        # Security.evtx
        # 4624   An account was successfully logged on.
        # 5140   A network share object was accessed.
        # 5145   A network share object was checked to see whether client can be granted desired access
        """
        eventos_share = {"5140": "Microsoft-Windows-Security-Auditing", "5145": "Microsoft-Windows-Security-Auditing"}
        data_list = ("EventID", "SubjectLogonId", "SubjectDomainName", "SubjectUserName", "ShareName", "ShareLocalPath", "IpAddress", "IpPort")

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Security.txt")
            output_file = os.path.join(self.outdir, "shared_objects.csv")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "Security.txt")
            output_file = os.path.join(self.outdir, "shared_objects_%s.csv" % vss_dir)

        self.clearEvents()

        self.parse_evtx(inputfile, eventos_share, data_list)

        self.sort_events()
        self.logger().info("Extracting shared objects related information")
        self.write_csv(output_file, ["TimeCreated", "EventID", "SubjectLogonId", "SubjectDomainName", "SubjectUserName", "ShareName", "ShareLocalPath", "IpAddress", "IpPort"])


class RDP(base.job.BaseModule, EventList):
    # EventID 21: Remote Desktop Services: Session logon succeeded
    # EventID 22: Remote Desktop Services: Shell start notification received
    # EventID 23: Remote Desktop Services: Session logoff succeeded
    # EventID 24: Remote Desktop Services: Session has been disconnected
    # EventID 25: Remote Desktop Services: Session reconnection succeeded
    # EventID 39: Session <X> has been disconnected by session <Y>
    # EventID 40: Session <X> has been disconnected, reason code <Z>
    # EventID 1149: User authentication succeeded

    # TODO: combine with login events to get a flowchart as those in https://www.13cubed.com/downloads/rdp_flowchart.pdf:

    def run(self, path=""):
        vss = self.myflag('vss')

        self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', '{}outdir'.format('v' if vss else ''))
        self.outdir = self.myconfig('{}outdir'.format('v' if vss else ''))
        check_directory(self.indir, error_missing=True)
        check_directory(self.outdir, create=True)

        if not vss:
            self.rdp_main()
        else:
            for dir in os.listdir(self.indir):
                self.rdp_main(dir)
        return []

    def rdp_main(self, vss_dir=""):
        """ Extracts login logoff data from Microsoft-Windows-TerminalServices-LocalSessionManager%4Operational.txt
        and Microsoft-Windows-TerminalServices-RemoteConnectionManager%4Operational.txt

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """

        eventos_rdp = {"21": "Microsoft-Windows-TerminalServices-LocalSessionManager", "22": "Microsoft-Windows-TerminalServices-LocalSessionManager", "23": "Microsoft-Windows-TerminalServices-LocalSessionManager",
                       "24": "Microsoft-Windows-TerminalServices-LocalSessionManager", "25": "Microsoft-Windows-TerminalServices-LocalSessionManager", "39": "Microsoft-Windows-TerminalServices-LocalSessionManager", "40": "Microsoft-Windows-TerminalServices-LocalSessionManager"}
        eventos_rdp2 = {"1149": "Microsoft-Windows-TerminalServices-RemoteConnectionManager"}
        data_list = ("EventID", "SessionID", "User", "Address")

        LogonsIds = ('21', '25')
        LogoffsIds = ('23', '24')

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Microsoft-Windows-TerminalServices-LocalSessionManager%4Operational.txt")
            inputfile2 = os.path.join(self.indir, "Microsoft-Windows-TerminalServices-RemoteConnectionManager%4Operational.txt")
            output_file = os.path.join(self.outdir, "rdp_sessions.csv")
            output_file2 = os.path.join(self.outdir, "rdp_sessions.md")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "Microsoft-Windows-TerminalServices-LocalSessionManager%4Operational.txt")
            inputfile2 = os.path.join(self.indir, vss_dir, "Microsoft-Windows-TerminalServices-RemoteConnectionManager%4Operational.txt")
            output_file = os.path.join(self.outdir, "rdp_sessions_%s.csv" % vss_dir)
            output_file2 = os.path.join(self.outdir, "rdp_sessions_%s.md" % vss_dir)

        self.clearEvents()
        self.parse_evtx(inputfile, eventos_rdp, data_list)

        self.logger().info("Extracting RDP sessions related information")

        events = self.sort_events()

        with open(output_file2, "w") as f_o2:
            writer = csv.writer(f_o2, delimiter="|", quotechar='"')
            writer.writerow(['User', 'Logon', 'Address', 'Logoff'])
            writer.writerow(['--', '--' '--', '--'])

            log_in = ""

            for e in events:
                if e['EventID'] in LogonsIds:
                    log_in = e
                elif e['EventID'] in LogoffsIds and log_in != "":
                    writer.writerow([log_in['User'], log_in['TimeCreated'], log_in['Address'], e['TimeCreated']])
                    log_in = ""
            if log_in != "":  # session not closed
                writer.writerow([log_in['User'], log_in['TimeCreated'], log_in['Address'], ""])

        self.parse_evtx(inputfile2, eventos_rdp2, data_list)
        self.write_csv(output_file, ['TimeCreated', "EventID", "SessionID", "User", "Address"])

        self.logger().info("Finished RDP extraction")


class OAlert_Application(base.job.BaseModule, EventList):
    # OAlert EventID 300
    # Application EventID 29
    # Application EventID 30
    # Application EventID 38

    def run(self, path=""):
        vss = self.myflag('vss')

        if not vss:
            self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
            self.outdir = self.myconfig('outdir')
            check_directory(self.indir, error_missing=True)
            check_directory(self.outdir, create=True)
            self.oevents()
        else:
            self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir')
            self.outdir = self.myconfig('voutdir')
            check_directory(self.indir, error_missing=True)
            check_directory(self.outdir, create=True)
            for dir in os.listdir(self.indir):
                self.oevents(dir)
        return []

    def oevents(self, vss_dir=""):
        """ Extracts alert data from dumped OAlert.evtx and Application.evtx

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """

        oalert_event = {"300": "Microsoft Office"}
        app_event = {"29": "Outlook", "30": "Outlook", "38": "Outlook"}
        data_list = ("EventID", "updateTitle", "Descr")

        if not vss_dir:
            inputfile = os.path.join(self.indir, "OAlerts.txt")
            inputfile2 = os.path.join(self.indir, "Application.txt")
            output_file = os.path.join(self.outdir, "oevents.csv")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "OAlerts.txt")
            inputfile2 = os.path.join(self.indir, vss_dir, "Application.txt")
            output_file = os.path.join(self.outdir, "oevents_%s.csv" % vss_dir)

        self.logger().info("Extracting MS Office alert events")
        self.clearEvents()
        self.parse_evtx(inputfile, oalert_event, data_list)
        self.parse_evtx(inputfile2, app_event, data_list)

        self.sort_events()

        self.write_csv(output_file, ['TimeCreated', "EventID", "Application", "Descr"])

        self.logger().info("Finished OAlert and Application extraction")


class WinUpdate(base.job.BaseModule, EventList):
    # System EventID 19 Installation success
    # System EventID 20 Installation error
    # System EventID 43 Installation
    # System EventID 44 Download updates

    def run(self, path=""):
        vss = self.myflag('vss')

        self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir') if vss else self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
        self.outdir = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(self.indir, error_missing=True)
        check_directory(self.outdir, create=True)

        if not vss:
            self.uevents()
        else:
            for dir in os.listdir(self.indir):
                self.uevents(dir)
        return []

    def uevents(self, vss_dir=""):
        """ Extracts alert data from dumped OAlert.evtx and Application.evtx

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """

        uevent = {"19": "Microsoft-Windows-WindowsUpdateClient", "20": "Microsoft-Windows-WindowsUpdateClient",
                  "43": "Microsoft-Windows-WindowsUpdateClient", "44": "Microsoft-Windows-WindowsUpdateClient"}
        updescr = {"19": "Installation success", "20": "Installation error", "43": "Installation started", "44": "Downloading started"}
        data_list = ("EventID", "updateTitle")

        if not vss_dir:
            inputfile = os.path.join(self.indir, "System.txt")
            output_file = os.path.join(self.outdir, "update_events.csv")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "System.txt")
            output_file = os.path.join(self.outdir, "update_events_%s.csv" % vss_dir)

        self.logger().info("Extracting MS Office alert events")
        self.clearEvents()
        self.parse_evtx(inputfile, uevent, data_list)

        self.sort_events()
        self.addEventIDDescription(updescr, "Description")

        self.write_csv(output_file, ['TimeCreated', "EventID", "updateTitle", "Description"])

        self.logger().info("Finished update events extraction")


class ScheduledTasks(base.job.BaseModule, EventList):
    # 106 – Task scheduled
    # 200 – Task executed
    # 201 – Task completed
    # 141 – Task removed

    def run(self, path=""):
        vss = self.myflag('vss')

        self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir') if vss else self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
        self.outdir = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(self.indir, error_missing=True)
        check_directory(self.outdir, create=True)

        if not vss:
            self.taskEvents()
        else:
            for dir in os.listdir(self.indir):
                self.taskEvents(dir)
        return []

    def taskEvents(self, vss_dir=""):
        """ Extracts scheduled tasks events

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """

        task_event = {"106": "Microsoft-Windows-TaskScheduler", "141": "Microsoft-Windows-TaskScheduler",
                      "200": "Microsoft-Windows-TaskScheduler", "201": "Microsoft-Windows-TaskScheduler"}
        updescr = {"106": "Scheduled task registered", "141": "Scheduled Task Deleted", "200": "Scheduled Task launched", "201": "Scheduled Task finished"}
        data_list = ("EventID", "TaskName", "ActionName", "ResultCode", "UserContext")

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Microsoft-Windows-TaskScheduler%4Operational.txt")
            output_file = os.path.join(self.outdir, "scheduled_task_events.csv")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "Microsoft-Windows-TaskScheduler%4Operational.txt")
            output_file = os.path.join(self.outdir, "scheduled_task_events_%s.csv" % vss_dir)

        self.logger().info("Extracting Scheduled Task events")
        self.clearEvents()
        self.parse_evtx(inputfile, task_event, data_list)

        self.sort_events()
        self.addEventIDDescription(updescr, "Description")

        self.write_csv(output_file, ['TimeCreated', "EventID", "TaskName", "ActionName", "UserContext", "ResultCode", "Description"])

        self.logger().info("Finished scheduled task events extraction")


class InstallServices(base.job.BaseModule, EventList):
    # System.evtx
    # 7045   A new service was installed in the system
    # 4697   A process was installed

    # Security
    # 4688   A service was installed in the system

    def run(self, path=""):
        vss = self.myflag('vss')

        self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir') if vss else self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
        self.outdir = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(self.indir, error_missing=True)
        check_directory(self.outdir, create=True)

        if not vss:
            self.main()
        else:
            for dir in os.listdir(self.indir):
                self.main(dir)
        return []

    def main(self, vss_dir=""):
        """ Extracts logon and logoffs artifacts

        %%1936 - Type 1 is a full token with no privileges removed or groups disabled.  A full token is only used if User Account Control is disabled or if the user is the built-in Administrator account or a service account.
        %%1937 - Type 2 is an elevated token with no privileges removed or groups disabled.  An elevated token is used when User Account Control is enabled and the user chooses to start the program using Run as administrator.  An elevated token is also used when an application is configured to always require administrative privilege or to always require maximum privilege, and the user is a member of the Administrators group.
        %%1938 - Type 3 is the normal value when UAC is enabled and a user simply starts a program from the Start Menu.  It's a limited token with administrative privileges removed and administrative groups disabled.  The limited token is used when User Account Control is enabled, the application does not require administrative privilege, and the user does not choose to start the program using Run as administrator.

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """
        eventos_system = {"7036": "Service Control Manager", "7040": "Service Control Manager", "7045": "Service Control Manager"}
        eventos_sec = {"4688": "Microsoft-Windows-Security-Auditing"}
        data_list = ("EventID", "ServiceName", "ImagePath", "StartType", "SubjectUserName", "SubjectDomainName",
                     "SubjectLogonId", "NewProcessName", "CommandLine", "TargetUserName", "TargetDomainName", "TokenElevationType", "param1", "param2", "param3", "param4")
        description = {"7036": "The service entered the state.", "7040": "The start type of the  service was changed from disabled to auto start.", "7045": "A service was installed in the system", "4688": "A new process has been created", "4697": "A service was installed in the system"}

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Security.txt")
            inputfile2 = os.path.join(self.indir, "System.txt")
            output_file = os.path.join(self.outdir, "install_services.csv")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "Security.txt")
            inputfile2 = os.path.join(self.indir, vss_dir, "System.txt")
            output_file = os.path.join(self.outdir, "install_services_%s.csv" % vss_dir)

        self.clearEvents()

        self.parse_evtx(inputfile, eventos_sec, data_list)
        self.parse_evtx(inputfile2, eventos_system, data_list)
        self.addEventIDDescription(description, "Description")

        self.sort_events()
        self.logger().info("Extracting install services and process events")
        self.write_csv(output_file, ["TimeCreated", "EventID", "ServiceName", "ImagePath", "StartType", "SubjectUserName",
                                     "SubjectDomainName", "SubjectLogonId", "NewProcessName", "CommandLine", "TargetUserName", "TargetDomainName", "TokenElevationType", "Description"])
        self.logger().info("Extracting install services and process events")


class BITS(base.job.BaseModule, EventList):
    # Microsoft-Windows-Bits-Client%4Operational.evtx
    # 3   A new service was installed in the system
    # 59   A process was installed
    # 60

    def run(self, path=""):
        vss = self.myflag('vss')

        self.indir = self.config.get('plugins.windows.RVT_evtx.Evtx', 'voutdir') if vss else self.config.get('plugins.windows.RVT_evtx.Evtx', 'outdir')
        self.outdir = self.myconfig('voutdir') if vss else self.myconfig('outdir')
        check_directory(self.indir, error_missing=True)
        check_directory(self.outdir, create=True)

        if not vss:
            self.main()
        else:
            for dir in os.listdir(self.indir):
                self.main(dir)
        return []

    def main(self, vss_dir=""):
        """ Extracts BITS artifacts

        Args:
            vss_dir (str): vss folder or empty for normal allocated file
        """
        eventos_bits = {"3": "Microsoft-Windows-Bits-Client", "59": "Microsoft-Windows-Bits-Client", "60": "Microsoft-Windows-Bits-Client"}
        data_list = ("EventID", "transferId", "Id", "name", "url", "fileTime", "fileLength", "bytesTotal", "bytesTransferred", "proxy", "Filelength", "string", "string2", "string3", "owner")
        description = {"3": "BITS service created a new job", "59": "BITS is starting to transfer", "60": "BITS has stopped transferring", "64": "The BITS job is configured to launch after transfer"}

        if not vss_dir:
            inputfile = os.path.join(self.indir, "Microsoft-Windows-Bits-Client%4Operational.txt")
            output_file = os.path.join(self.outdir, "bits_events.csv")
        else:
            inputfile = os.path.join(self.indir, vss_dir, "Microsoft-Windows-Bits-Client%4Operational.txt")
            output_file = os.path.join(self.outdir, "bits_events_%s.csv" % vss_dir)

        self.clearEvents()

        self.parse_evtx(inputfile, eventos_bits, data_list)
        self.replace_field_name("string", "name")
        self.replace_field_name("string2", "owner")
        self.addEventIDDescription(description, "Description")

        self.sort_events()
        self.logger().info("Extracting install services and process events")
        self.write_csv(output_file, ["transferId", "Id", "name", "owner", "url", "fileTime", "fileLength", "bytesTotal", "bytesTransferred", "proxy", "Filelength", "string3", "Description"])
