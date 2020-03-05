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


# Structure
# <tr id=".." class="zA yO" tabindex="-1" ...
#     <td class="yX xY ">
#        ...
#        <div id=".." class="yW"> mail start with <span
#     <td id=".." class="xY a4W"...
#        ...
#        <div class="y6">
#           <span id="..">subject</span>
#           <span ckass="y2">body</span>
#     <td class="yf xY ">
#         <img class="yE" src="Recibidos.../cleardot.gif" title="nombres" alt="Archivo adjunto"></td>
#     <td class="xW xY ">
#         <span id=".." title="fecha"...


# Detected proble: chains are large and may take two or more blocks
# Alternative method: detecting start like ["^all","^.. \u003cspan class\u003d\"yP\" email\u003d\

# Search '\\\\u003cspan class\\\\u003d\\\\"(yP|zF)\\\\" email\\\\u003d\\\\"'

import re
import os
import os.path
from base.utils import check_folder
import base.job


def sanitize_text(texto):
    """ Sanitize text
    Args:
        texto (str): text to sanitize
    Returns:
        str: text replacing some chars
    """
    # chars < or > are not replaced because problems transforming to markdown
    texto = texto.replace(r"\u0026", "&")
    texto = texto.replace(r"&#39;", "'")
    texto = texto.replace(r"&amp;", "&")
    texto = texto.replace("|", "/")
    return texto


def check_make_search_file(fname, webmail, kw):
    if not os.path.isfile(fname):
        with open(fname, "w") as f:
            f.write('# Search file autmaticaly created by rvt2\n# for {} webmail detection\n{}'.format(webmail, kw))


class Gmail(base.job.BaseModule):

    def run(self, path=""):
        """ Main function to generate inbox files based on string searches

        """
        outdir = self.myconfig('outdir')
        check_folder(outdir)
        output_file = os.path.join(outdir, "gmail_mailbox.md")

        searches_path = self.config.get('plugins.common.RVT_search.StringSearch', 'outdir')
        check_folder(searches_path)

        if not (os.path.exists(os.path.join(searches_path, "all_gmail")) and os.path.exists(os.path.join(searches_path, "all_u003cspan"))):
            self.generate_search_file()

        with open(output_file, 'w') as of:
            of.write("date, emails, subject, body, attachments\n--|--|--|--|--\n")

            for i in os.listdir(searches_path):
                if i.startswith("all_gmail") and os.stat(os.path.join(searches_path, i)).st_size > 0:
                    self.logger().debug("Extracting data from {}".format(i))
                    self.extract_from_gmail(os.path.join(searches_path, i), of)

                if i.startswith("all_u003cspan") and os.stat(os.path.join(searches_path, i)).st_size > 0:
                    self.logger().debug("Extracting data from {}".format(i))
                    self.extract_from_cspan(os.path.join(searches_path, i), of)
        return []

    def extract_from_gmail(self, infile, of):
        with open(infile, "r", encoding='utf-8', errors='ignore') as file:
            file.readline()  # datos bloque
            linea = file.readline()  # linea en blanco

            texto = ""
            while True:
                texto += linea
                linea = file.readline()

                if linea == "":
                    break
                if linea.startswith("--------------------------"):
                    td = 0
                    while td > -1:
                        emails = ""
                        subject = ""
                        fecha = ""
                        body = ""
                        attachments = ""
                        td = texto.find('<td class="yX xY ">', td)
                        td_end = texto.find("</td>", td)
                        td = texto.find('class="yW">', td)
                        for r in re.finditer('<span class="(yP|zF)" email="([^"]*)"', texto[td:td_end]):
                            emails += r.group(2) + ", "

                        td = texto.find('class="xY a4W">', td_end)
                        td_end = texto.find("</td>", td)
                        aux = re.search('<span id="[^"]*">(.*)</span><span class="y2">', texto[td:td_end])
                        if aux:
                            subject = aux.group(1).replace("&nbsp;", "")
                        aux = re.search('<span class="y2">(.*)</span></div>', texto[td:td_end])
                        if aux:
                            body = aux.group(1).replace("&nbsp;", "")

                        td = texto.find('<td class="yf xY "', td_end)
                        td_end = texto.find("</td>", td)
                        aux = re.search('<img class="[^"]*" src="[^"]*" title="([^"]*)"', texto[td:td_end])
                        if aux:
                            attachments = aux.group(1).replace("&nbsp;", "")

                        td = texto.find('<td class="xW xY "', td_end)
                        td_end = texto.find("</td>", td)
                        aux = re.search('<span title="([^"]*)', texto[td:td_end])
                        if aux:
                            fecha = aux.group(1)
                        if fecha != "" or emails != "" or subject != "" or body != "":
                            of.write("{}|{}|{}|{}|{}\n".format(fecha, emails, subject, body, attachments))

                    file.readline()
                    file.readline()
                    linea = ""
                    texto = ""

    def extract_from_cspan(self, infile, of):
        with open(infile, "r", errors='replace') as file:
            file.readline()  # datos bloque
            linea = file.readline()  # linea en blanco

            texto = ""
            while True:
                texto += linea
                linea = file.readline()

                if linea == "":
                    break
                if linea.startswith("------------------------"):
                    td = 0
                    td_end = texto.find('["^all","^', 0)
                    while td > -1 and td_end != len(texto) - 1:
                        emails = ""
                        td = td_end
                        td_end = texto.find('["^all","^', td + 1)

                        for r in re.finditer('\\\\u003cspan class\\\\u003d\\\\"(yP|zF)\\\\" email\\\\u003d\\\\"([^\\\\]*)\\\\"', texto[td:td_end]):
                            emails += r.group(2) + ", "
                        aux = re.search('\\\\u0026nbsp;","([^"]*)","([^"]*)",0,"","([^"]*)","[^"]*","([^"]*)', texto[td:td_end])

                        if aux:
                            of.write("{}|{}|{}|{}|{}\n".format(aux.group(4), emails, sanitize_text(aux.group(1)), sanitize_text(aux.group(2)), sanitize_text(aux.group(3))))

                    file.readline()
                    file.readline()
                    linea = ""
                    texto = ""

    def generate_search_file(self):
        """ Generates needed searches files if it doesn't exists """

        kwdir = self.myconfig('kwdir')

        check_folder(kwdir)

        check_make_search_file(os.path.join(kwdir, "webmail_gmail"), "gmail", "upro:::_upro_")
        check_make_search_file(os.path.join(kwdir, "webmail_gmail2"), "gmail2", "u003cspan")
        check_make_search_file(os.path.join(kwdir, "webmail_gmail3"), "gmail3", r'gmail:::<td class=\"yx xy \">')

        for item in ["webmail_gmail", "webmail_gmail2", "webmail_gmail3"]:
            list(base.job.run_job(self.config, 'plugins.common.RVT_search.StringSearch', path=[os.path.join(self.myconfig('kwdir'), item)]))
