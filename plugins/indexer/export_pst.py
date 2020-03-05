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


""" Modules to parse the output from the RVT related to emails. """

import os
import re
import shutil
from mako.template import Template
import mimetypes
from email.message import EmailMessage
import subprocess
import tempfile
import chardet

# from base.commands import run_command
import base.utils
import base.job


# dicts for html names
activity = {}
activity['Creation time'] = "Creation"
activity['Modification time'] = "Modification"
activity['Flags'] = "Flags"
activity['Subject'] = "Subject"
activity['Sender name'] = "Creator"
activity['Importance'] = "Importance"
activity['Priority'] = "Priority"
activity['Conversation topic'] = "Conversation topic"
# Appointments:
appointment = {}
appointment['Creation time'] = "Creation"
appointment['Modification time'] = "Modification"
appointment['Flags'] = "Flags"
appointment['Subject'] = "Subject"
appointment['Sender name'] = "Creator"
appointment['Importance'] = "Importance"
appointment['Priority'] = "Priority"
appointment['Conversation topic'] = "Conversation topic"
# Contacts:
contact = {}
contact['Creation time'] = "Creation"
contact['Sender name'] = "Creator"
contact['Modification time'] = "Modification"
contact['Subject'] = "Contact name"
contact['Flags'] = "Flags"
contact['Conversation topic'] = "Conversation topic"
# Meetings:
meeting = {}
meeting['Creation time'] = "Creation"
meeting['Modification time'] = "Modification"
meeting['Flags'] = "Flags"
meeting['Subject'] = "Subject"
meeting['Sender name'] = "Creator"
meeting['Importance'] = "Importance"
meeting['Priority'] = "Priority"
meeting['Conversation topic'] = "Conversation topic"
# Messages:
message = {}
message['Client submit time'] = "Sent"
message['Delivery time'] = "Received"
message['Flags'] = "Flags"
message['Subject'] = "Subject"
message['Sender name'] = "From"
message['Conversation topic'] = "Conversation topic"
# Notes:
note = {}
note['Creation time'] = "Creation"
note['Modification time'] = "Modification"
note['Flags'] = "Flags"
note['Subject'] = "Subject"
note['Sender name'] = "Creator"
note['Importance'] = "Importance"
note['Priority'] = "Priority"
note['Conversation topic'] = "Conversation topic"
# Tasks:
task = {}
task['Creation time'] = "Creation"
task['Modification time'] = "Modification"
task['Flags'] = "Flags"
task['Subject'] = "Subject"
task['Sender name'] = "Created by"
task['Importance'] = "Importance"
task['Priority'] = "Priority"
task['Conversation topic'] = "Conversation topic"


class ExportPstHtml(base.job.BaseModule):
    """
    Exports to html items from pst/ost.

    """

    def read_config(self):
        super().read_config()
        self.set_default_config('outfile', 'render.html')

    def run(self, path):
        """
        Exports to html items from pst/ost

        Parameters:
            path (str): path to item to export (Message, Task, Appointment, Activity, Meeting, Note, Contact)
        """
        self.logger().info('Running on %s', path)
        self.path = path

        self.tika_parser = base.job.load_module(self.config, 'indexer.tikaparser.TikaParser')

        self._export_item(self.path)
        return []

    def _export_item(self, item, export_dir=None):
        """ Exports item to html.

        Parameters:
            item (str): item to export (Message, Appointment, Activity, Contact, Meeting, Note or Task)
            export_dir (str): optional export path used for Message Attachments
        """
        if not export_dir:
            export_dir = item
        base.utils.check_folder(export_dir)
        output_filename = os.path.join(export_dir, self.myconfig('outfile'))
        if base.utils.check_file(output_filename):
            return

        tipe = ''
        srch_type = re.compile("(Message|Appointment|Activity|Contact|Meeting|Note|Task)")
        aux = srch_type.match(os.path.basename(item))
        if aux:
            tipe = aux.group(1)

        out_headers = []
        conv_ind = ""
        R_out_head = []
        body = ""
        int_headers = ""
        recipientes = ""

        srch = re.compile(r'(Client submit time|Creation time|Delivery time|Flags|Importance|Modification time|Priority|Sender email address|Sender name|Subject|Conversation topic):\s*(.*)')

        tos = ""
        ccs = ""
        bccs = ""
        attach = []

        pretable = ""

        if tipe == "Message":
            fich = os.path.join(item, "OutlookHeaders.txt")
            if os.path.isfile(fich):
                out_headers = ["OutlookHeaders.txt", get_text(fich)]

        else:
            for tp in ["Contact", "Appointment", "Meeting", "Task", "Note", "Activity"]:
                fich = os.path.join(item, "{}.txt".format(tp))
                if os.path.isfile(fich):
                    temp = get_text(fich)
                    temp = temp.split("{}:".format(tp))
                    out_headers = ["{}.txt".format(tp), temp[0][:-1]]
                    R_out_head = ["Rest of {}.txt (if any):".format(tp), "{}:{}".format(tp, temp[1])]
                    pretable = "{}:{}".format(tp, temp[1].replace("\n", "\n<br>"))
                    break

        if os.path.isfile(os.path.join(item, "InternetHeaders.txt")):
            int_headers = repl_lt_gt(get_text(os.path.join(item, "InternetHeaders.txt")))
        if os.path.isfile(os.path.join(item, "ConversationIndex.txt")):
            conv_ind = get_text(os.path.join(item, "ConversationIndex.txt"))
        if os.path.isfile(os.path.join(item, "Recipients.txt")):
            recipientes = get_text(os.path.join(item, "Recipients.txt"))
        if os.path.isfile(os.path.join(item, "RestOutlookHeaders.txt")):
            R_out_head = ["RestOutlookHeaders.txt", get_text(os.path.join(item, "RestOutlookHeaders.txt"))]
        extra_style = ""
        body = ""
        for fich in os.listdir(item):
            if fich.startswith("Message"):
                fichero = os.path.join(item, fich)
                if fich.endswith(".html"):
                    body = get_text(fichero)
                    if body.find("/* Font Definitions */") > -1:
                        try:
                            extra_style = body.split("/* Font Definitions */")[1].split("</style>")[0]
                        except Exception:
                            extra_style = body.split("/* Font Definitions */")[1].split("</style>")[0]
                    aux = body.find(">", body.find("<body"))
                    aux2 = body.find("</body>")
                    body = body[aux + 1:aux2]
                    body = body.replace("<o:p>", "")
                    body = body.replace("</o:p>", "")
                    body = body.replace(" lang=ES-TRAD", "")
                    break
                elif fich.endswith(".rtf"):
                    body = self.tika_parser.run(os.path.join(item, fich))[0]['content'].replace("\n", "<br>\n")
                elif fich.endswith(".txt"):
                    with open(fichero, "r") as f:
                        body = f.read().replace("\n", "<br>\n")

        attach_info = "no"

        att_dir = os.path.join(item, "Attachments")

        if os.path.isdir(att_dir):
            attach_info = "si"

            export_att_dir = os.path.join(export_dir, "%s.attach" % os.path.basename(item))
            base.utils.check_folder(export_att_dir)

            for f in os.listdir(att_dir):
                fichero = os.path.join(att_dir, f)
                r = os.path.join(os.path.basename(export_att_dir), f)
                if os.path.isfile(fichero):
                    shutil.copy2(fichero, export_att_dir)
                    attach.append([os.path.join(os.path.basename(export_att_dir), f), os.stat(fichero).st_size])
                    regex = f.split("_")[1].replace("(", "\\(").replace(")", "\\)")
                    body = re.sub('"cid:{}@[^"]*'.format(regex), r, body)
                    body = re.sub('cid:%s@.{17}' % regex, '<img src="{}">'.format(r), body)
                else:
                    for f2 in os.listdir(os.path.join(att_dir, f)):
                        if srch_type.search(f2):
                            total_bytes = subprocess.check_output(["du", "-k", os.path.join(att_dir, f, f2)]).decode().split()[0]
                            self._export_item(os.path.join(att_dir, f, f2), export_dir=os.path.join(export_dir, "%s.attach" % os.path.basename(item), f))
                            attach.append([os.path.join(r, f2 + ".html"), total_bytes])

        snt = ""
        temporal = dict()

        if len(out_headers) == 2:
            for linea in out_headers[1].split("\n"):
                aux = srch.match(linea)
                if aux:
                    if aux.group(1) == "Sender name":
                        snt = aux.group(2) + snt
                    elif aux.group(1) == "Sender email address":
                        snt = "{} ({})".format(snt, aux.group(2))
                    else:
                        temporal[aux.group(1)] = aux.group(2)

        if "Conversation topic" in temporal.keys():
            temporal["Subject"] = str(temporal["Conversation topic"])

        temporal['Sender name'] = snt
        campos = []
        for tp in ["Message", "Appointment", "Contact", "Activity", "Meeting", "Note", "Task"]:
            if tipe == tp:
                for i, j in globals()[tp.lower()].items():
                    if i in temporal.keys():
                        campos.append([j, temporal[i]])

        for linea in recipientes.split("\n"):
            aux = re.search(r"(Email address|Display name):\s*(.*)", linea)
            if aux:
                if aux.group(1) == "Email address":
                    tos += " ({}); ".format(aux.group(2))
                else:
                    tos += aux.group(2)

        subject = ""
        if "Subject" in temporal.keys():
            subject = repl_lt_gt(temporal["Subject"])

        source = ""
        if item.find('.export') > -1:
            source = item.split(".export/")[1]
        elif item.find('orphan') > -1:
            source = item.split(".orphan/")[1]
        elif item.find('recovered') > -1:
            source = item.split(".recovered/")[1]

        template = Template(filename=os.path.join(self.myconfig('rvthome'), "templates/pff2html.mako"))

        with open(output_filename, 'w') as f_index:
            output_text = template.render(tipe=tipe, attach_info=attach_info, attach=attach, subject=subject, body=body, out_headers=out_headers, conv_ind=conv_ind, extra_style=extra_style, R_out_head=R_out_head, pretable=pretable, int_headers=int_headers, recipientes=recipientes, campos=campos, tos=tos, ccs=ccs, source=source, bccs=bccs)
            f_index.write(output_text)


def repl_lt_gt(text):
    """ replace text to show in html
    """
    aux = text.replace("<", "&lt;")
    return aux.replace(">", "&gt;")


def get_text(filename):
    """ get content of a file
    """
    try:
        with open(filename, "r") as f:
            text = f.read()
    except Exception:
        with open(filename, "r", encoding="cp1252") as f:
            text = f.read()
    return text


class ExportPstEml(base.job.BaseModule):
    """ Exports to html items from pst/ost.

    """

    def run(self, path):
        """
        Exports to eml items from pst/ost

        Parameters:
            path (str): path to item to export (Message, Task, Appointment, Activity, Meeting, Note, Contact)
        """
        self.logger().info('Running on %s', path)
        self.path = path
        self.msg = EmailMessage()
        self.path = path

        self.export_eml(self.path)
        return []

    def export_eml(self, item, write=True):
        """
        Exports to eml an item parsed with pff-export

        Args:
            item (str): path to item
            write (bool): writes eml file or returns eml content
        """
        content = ""
        bodyfile = ""
        for i in os.listdir(item):
            if i.startswith("Message"):
                bodyfile = os.path.join(item, i)
                break

        if not os.path.isfile(os.path.join(item, "InternetHeaders.txt")):
            self._setIntHeaders(item)
        else:
            content, boundary = self._getIntHeaders(item)
        self._getBody(bodyfile)
        self._addAttach(item)

        if content == "":
            email = self.msg.as_string()
        else:
            email = "{}\r\n--{}\r\n{}\r\n--{}--".format(content, boundary, self.msg.as_string(), boundary)
        if write:
            export_dir = os.path.dirname(item)
            base.utils.check_folder(export_dir)
            output_filename = "{}.eml".format(os.path.join(export_dir, os.path.basename(item)))
            with open(output_filename, 'w') as of:
                of.write(email)
        else:
            return email

    def _addAttach(self, item):

        if not os.path.isdir(os.path.join(item, "Attachments")):
            return

        for i in os.listdir(os.path.join(item, "Attachments")):
            fname = os.path.join(item, "Attachments", i)
            if os.path.isdir(fname):  # attachment is a message
                for l in os.listdir(fname):
                    msg2 = self.msg
                    self.msg = EmailMessage()
                    a = self.export_eml(os.path.join(fname, l), False)
                    with tempfile.NamedTemporaryFile() as fp:
                        fp.write(a.encode())
                        self.msg = msg2
                        # ctype, encoding = mimetypes.guess_type(fp.name)
                        # if ctype is None or encoding is not None:
                        #     # No guess could be made, or the file is encoded (compressed), so
                        #     # use a generic bag-of-bits type.
                        #     ctype = 'text/rfc822'
                        # maintype, subtype = ctype.split('/', 1)
                        with open(fp.name, 'rb') as fp2:
                            self.msg.add_attachment(fp2.read(),
                                                    maintype='application',
                                                    subtype='rfc822',
                                                    filename="%s.eml" % os.path.basename(fname))
            else:
                ctype, encoding = mimetypes.guess_type(fname)
                if ctype is None or encoding is not None:
                    # No guess could be made, or the file is encoded (compressed), so
                    # use a generic bag-of-bits type.
                    ctype = 'application/octet-stream'
                maintype, subtype = ctype.split('/', 1)
                with open(fname, 'rb') as fp:
                    self.msg.add_attachment(fp.read(),
                                            maintype=maintype,
                                            subtype=subtype,
                                            filename=i)

    def _getIntHeaders(self, item):
        int_headers = os.path.join(item, "InternetHeaders.txt")
        content = ''
        addcontent = True
        boundary = "--=11111111111"

        with open(int_headers, 'r') as f:
            for line in f:
                if line.find("%s--" % boundary) > -1:
                    return content, boundary
                if line.strip() == '':
                    addcontent = False
                    continue
                if addcontent:
                    content += line

                bound = re.search('boundary="([^"]+)"', line)
                if bound:
                    boundary = bound.group(1)
        return content, boundary

    def _setIntHeaders(self, item):

        d = self._getDataFromFile(os.path.join(item, "OutlookHeaders.txt"), ['Client submit time', 'Subject', 'Sender name', 'Sender email address'])
        self.msg.add_header('Date', d['Client submit time'][:21])
        self.msg.add_header('Subject', d['Subject'])
        self.msg.add_header('From', "{} <{}>".format(d['Sender name'], d['Sender email address']))

        messageID = self._getGUID(item)
        self.msg.add_header('MessageID', messageID)

        self._setRecipients(item)

    def _setRecipients(self, item):
        r = {'To': '', 'CC': '', 'BCC': ''}
        recipients = os.path.join(item, 'Recipients.txt')
        if not os.path.isfile(recipients):
            return r
        rec = {'To': [], 'CC': [], 'BCC': []}
        with open(recipients, 'r') as f:
            temp = {}
            for line in f:
                if line == "\n":
                    rec[temp['Recipient type']].append("{} <{}>".format(temp['Display name'], temp['Email address']))  # Solves problems with multiples To, CC and BCC fields
                    # self.msg.add_header(temp['Recipient type'], "{} <{}>".format(temp['Display name'], temp['Email address']))
                    temp = {}
                else:
                    aux = line.split(":")
                    temp[aux[0]] = aux[1].strip()
        for i in ['To', 'CC', 'BCC']:
            if len(rec[i]) > 0:
                self.msg.add_header(i, ", ".join(rec[i]))

    def _getDataFromFile(self, filename, items):
        """ Gets item information from a file

        File structure is 'item:        content'

        Args:
            filename (str): file to get information
            items (list): list of items to extract

        """
        res = {}
        for i in items:
            res[i] = ''

        if not os.path.isfile(filename):
            return res

        regex = r'({}):\s+(.*)'.format("|".join(items))
        with open(filename, 'r') as f:
            for line in f:
                item = re.search(regex, line)
                if item:
                    res[item.group(1)] = item.group(2)
        return res

    def _getGUID(self, item):
        conv_ind = os.path.join(item, "ConversationIndex.txt")
        if not os.path.isfile(conv_ind):
            return "AAAAAAAAAAAAAAAAAA@A.A"
        with open(conv_ind, 'r') as f:
            for line in f:
                guid = re.search(r'GUID:\s+([^\s]+)', line)
                if guid:
                    return "--=%s" % guid.group(1)
        return "AAAAAAAAAAAAAAAAAA@A.A"

    def _getBody(self, bodyfile):
        if not os.path.isfile(bodyfile):
            return ""

        if bodyfile.endswith('.txt'):
            with open(bodyfile) as bf:
                self.msg.set_content(bf.read())

        if bodyfile.endswith('.rtf'):
            tika_parser = base.job.load_module(self.config, 'indexer.tikaparser.TikaParser')
            body = tika_parser.run(bodyfile)[0]['content']

            self.msg.set_content(body)

        if bodyfile.endswith('.html'):
            with open(bodyfile, 'rb') as bf:
                data = bf.read()
                enc = chardet.detect(data)
                # self.msg.add_header('Content-Type', 'text/html')
                # self.msg.set_payload(bf.read())
                # self.msg.set_content(bf.read(), subtype='html')
                self.msg.set_content(data.decode(enc['encoding']), subtype='html')
