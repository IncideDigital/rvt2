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
import shutil
import tempfile
import json
import logging
from collections import Counter, OrderedDict, defaultdict
from tqdm import tqdm

import base.job
from plugins.common.RVT_disk import getSourceImage
from plugins.common.RVT_filesystem import FileSystem
from base.utils import check_directory, check_file, save_csv, save_json
from base.commands import run_command, yield_command
from plugins.common.RVT_string import StringGenerate


def getSearchItems(key_file, is_file=True):
    """ Get keywords and names for searching
    Args:
        key_file (str): File name with keywords
        is_file (boolean): get data from a file or from an string
    Returns:
        key_dict (dict): dictionary with keynames and keywords to search
    """

    if not is_file:
        aux = re.search("(.*):::(.*)", key_file)
        if aux:
            return {aux.group(1): aux.group(2).rstrip()}
        return{os.path.basename(key_file).rstrip(): os.path.basename(key_file).rstrip()}

    key_dict = OrderedDict()
    with open(key_file, "r") as f:
        for line in f:
            if line.startswith("#") or line.strip() == "":
                continue
            aux = re.search("(.*):::(.*)", line)

            if aux:
                key_dict[aux.group(1)] = aux.group(2).rstrip()
            else:
                key_dict[line.rstrip()] = line.rstrip()

    return key_dict


def searchCountRegex(regex, string_path, grep='grep', logger=logging):
    """ Return number of times a hit appears

    Args:
        regex (str): regular expression to seek
    Returns:
        dict: dict with number of times a hit appears
        """

    data = Counter()

    for f in os.listdir(string_path):
        try:
            text = run_command([grep, "-oP", regex, os.path.join(string_path, f)], logger=logger)
        except Exception:  # no hits
            continue
        for hit in text.split("\n"):
            data[hit] += 1

    return data


class StringSearch(base.job.BaseModule):
    """ Find strings that matches regular expression.
    There are three different output files types:
     - *hits_somekeyword*: For every hit in the search of 'somekeyword' in strings, show:
        Partition;Offset;Block;Status;String
     - *blocks_somekeyword*: All blocks (clusters) associated with a hit for a partition.
        It is an intermediate file, only for perfoming purposes
     - *all_somekeyword*: Displays every block where somekeyword has been found, along with the next information:
        Partition;Block;Inode;InodeStatus;PossibleFilename

    Parameter:
        path (str): filename with keywords to seek (same as keyfile in configuration)

    Configuration:
        - **keyfile**: default filename with keywords in case path is not specified
        - **outdir**: path to directory where generated match files will be stored
        - **strings_dir**: path to directory where string files are generated.

    Warning: if a keyword is found between two consecutive blocks, result won't be shown.
    """

    def run(self, path=""):
        self.disk = getSourceImage(self.myconfig)

        keyfile = path
        self.logger().debug('Testing existance of {}'.format(keyfile))
        if not keyfile:
            keyfile = self.myconfig('keyfile')
        check_file(keyfile, error_missing=True)

        # Get string files or generate them if not found
        self.string_path = self.myconfig('strings_dir')
        if not (check_directory(self.string_path) and os.listdir(self.string_path)):
            self.logger().debug("No string files found. Generating them")
            StringGenerate(config=self.config, disk=self.disk).generate_strings()

        self.search_path = self.myconfig('outdir')
        check_directory(self.search_path, create=True)

        self.keywords = getSearchItems(keyfile)  # Get kw:regex dictionary reading keyfile
        self.blocks = {}  # Store set of blocks for kw and partition. Ex: {'my_kw': {'p02': set(1234, 1235, ...)}}
        self.block_status = defaultdict(dict)  # Store status for blocks with search hits in a partition. Ex:{'03':{4547:'Allocated', 1354536:'Not Allocated'}}

        self.fs_object = FileSystem(self.config, disk=self.disk)

        # Generate or load 'hits_' and 'blocks_' files
        for kname in tqdm(self.keywords, total=len(self.keywords), desc='Searching keywords in strings'):
            kw = kname.strip()
            self.get_blocks(kw, self.keywords[kname])

        # Generate 'all_' files
        self.get_cluster()

        self.logger().info("StringSearch done")
        return []

    def get_blocks(self, kw, regex):
        """ Updates variable self.blocks, that stores set of blocks for kw and partition, creating new 'block' and 'hits' files """
        self.blocks_file_path = os.path.join(self.search_path, "blocks_{}".format(kw))
        hits_file = os.path.join(self.search_path, "hits_%s" % kw)

        # Create hits file if not found
        if not check_file(hits_file) or os.path.getsize(hits_file) == 0:
            self.logger().debug('Creating {} file'.format("hits_%s" % kw))
            extra_args = {'write_header': True, 'file_exists': 'OVERWRITE'}
            save_csv(self.search_strings(kw, regex), config=self.config, outfile=hits_file, **extra_args)

        # Create or load blocks file if not found
        if not check_file(self.blocks_file_path) or os.path.getsize(self.blocks_file_path) == 0:
            self.blocks[kw] = defaultdict(list)
            cmd = "sed -n '1!p' {} | cut -d ';' -f1,3 | sort | uniq".format(hits_file)
            for line in yield_command(cmd, logger=self.logger()):
                part, blk = line.split(';')
                part = part.strip('"')
                self.blocks[kw][part].append(int(blk.strip('"').rstrip('\n')))
            self.save_blocks_file(self.blocks[kw], kw)
        else:
            self.logger().info('Loading {} file'.format("blocks_%s" % kw))
            try:
                with open(self.blocks_file_path, "r") as block_file:
                    self.blocks[kw] = json.load(block_file)
            except Exception as exc:
                self.logger().error('Cannot load {}'.format(self.blocks_file_path))
                raise exc

    def search_strings(self, kw, regex):
        """ Generates a string search and yields hits. Also stores blocks where there's a match for the keyword 'kw'.

        Parameters:
            kw (str): keyword name
            regex (str): regular expression associated to keyword

        Yields:
            Dictionaries containing partition, block, offset and string match
        """
        self.logger().info('Searching keyword {} with regex {}'.format(kw, regex))

        partitions = {p.partition: [p.loop if p.loop != "" else "", p.clustersize] for p in self.disk.partitions}
        blocks = {}
        for p in self.disk.partitions:
            blocks.update({''.join(['p', p.partition]): set()})

        # In string files to search, all characters are lowercase, so the '-i' option is no needed
        grep = self.myconfig('grep', '/bin/grep')
        args = "-H" if kw == regex else "-HP"
        regex_search = [regex] if regex else [kw]
        search_command = '{} {} '.format(grep, args) + '"{regex}" "{path}"'
        module = base.job.load_module(self.config, 'base.commands.RegexFilter',
                                      extra_config=dict(cmd=search_command, keyword_list=regex_search, from_dir=self.string_path))

        srch = re.compile(r"(p\d{1,2})_strings_?[\w.]+:\s*(\d+)\s+(.*)")
        for f in os.listdir(self.string_path):
            for match in module.run(os.path.join(self.string_path, f)):
                line = match['match']
                aux = srch.match(line)
                if not aux:
                    continue

                pname, offset, string = aux.group(1), aux.group(2), aux.group(3)
                pt = pname[1:]
                bsize = int(partitions[pt][1])

                try:
                    blk = int(offset) // bsize
                    if blk not in self.block_status[pt]:
                        self.block_status[pt][blk] = self.fs_object.cluster_allocation_status(pname, str(blk))
                    status = self.block_status[pt].get(blk)
                except Exception as exc:
                    self.logger().error('Error searching {} in line {}'.format(srch, line))
                    raise exc

                if blk not in blocks[pname]:  # new block
                    blocks[pname].add(blk)

                yield OrderedDict([('Partition', pname), ('Offset', int(offset)), ('Block', blk), ('Status', status), ('String', string)])

        # Save blocks where a kw has been found
        if not check_file(self.blocks_file_path):
            self.save_blocks_file(blocks, kw)

    def save_blocks_file(self, blocks, kw):
        self.logger().info('Creating {} file'.format("blocks_%s" % kw))
        blocks = {p: list(b) for p, b in blocks.items()}  # json does not accept set structure
        outfile = os.path.join(self.search_path, "blocks_%s" % kw)
        save_json((lambda: (yield blocks))(), config=self.config, outfile=outfile, file_exists='OVERWRITE')

    def get_cluster(self):
        """ Generates report files containing information about the block where a hit is found, along with the contents of the block itself. """
        self.inode_from_block = {}
        self.inode_status = {}
        self.path_from_inode = {}
        self.path_from_inode_del = {}

        # Creating relation between every inode and its blocks takes a long time.
        # Searching only the required blocks, although slower one by one, colud be faster if the list is short
        blocks_thereshold = 20000  # it takes about an hour
        sum_blocks = 0
        for kw, parts in self.blocks.items():
            for p in parts:
                sum_blocks += len(parts[p])
        if sum_blocks > blocks_thereshold:
            for p in self.disk.partitions:
                if not p.isMountable or p.filesystem == "NoName":
                    continue
                self.inode_from_block['p{}'.format(p.partition)] = self.fs_object.load_inode_from_block(partition='p{}'.format(p.partition))

        # Get the necessary files relating inodes with paths and status
        for p in self.disk.partitions:
            if not p.isMountable or p.filesystem == "NoName":
                continue
            part_name = 'p{}'.format(p.partition)
            self.inode_status[part_name] = self.fs_object.load_inode_status(partition=part_name)
            self.path_from_inode[part_name] = self.fs_object.load_path_from_inode(partition=part_name)
            self.path_from_inode_del[part_name] = self.fs_object.load_path_from_inode(partition=part_name, deleted=True)

        self.used_blocks = defaultdict(set)
        self.block_inodes = defaultdict(dict)

        for kw in self.blocks:
            all_file = os.path.join(self.search_path, "all_{}".format(kw))
            if check_file(all_file) and os.path.getsize(all_file) != 0:
                self.logger().info('File {} already generated'.format(all_file))
                continue
            with open(all_file, "wb") as all_stream:
                for entry in self.all_info(self.blocks[kw], kw):
                    all_stream.write(entry)

    def all_info(self, kw_blocks, kw=''):
        """ Yields partition, block, inode, status, file and block content for each block where there is a match for 'kw'

        Parameters:
            kw_blocks (dict): mapping between partition and blocks with a hit for a keyword
            kw (str): keyword name
        """

        for p_name, blks in kw_blocks.items():
            # p_name = ''.join(['p', pt])
            for blk in tqdm(blks, total=len(blks), desc='Dumping searches for {} in partition {}'.format(kw, p_name)):
                self.used_blocks[p_name].add(blk)

                if blk not in self.block_inodes[p_name]:
                    inodes = self.fs_object.inode_from_cluster(p_name, blk, self.inode_from_block.get(p_name, None))
                    self.block_inodes[p_name][blk] = inodes
                else:
                    inodes = self.block_inodes[p_name][blk]

                if not inodes:
                    yield "Pt: {}; Blk: {}; Inode: {} {}; File: {}\n".format(p_name, blk, '', 'Not Allocated', '').encode()

                for inode in inodes:
                    status = self.inode_status[p_name].get(inode, "f")
                    try:
                        paths = self.path_from_inode[p_name][inode]
                    except KeyError:
                        paths = self.path_from_inode_del[p_name].get(inode, [""])

                    for name in paths:
                        alloc = 'Allocated' if status == 'a' else 'Not Allocated'
                        yield "Pt: {}; Blk: {}; Inode: {} {}; File: {}\n".format(p_name, blk, inode, alloc, name).encode()

                yield b"\n"
                yield self.fs_object.cluster_extract(p_name, str(blk))
                yield '\n\n{}\n'.format('-' * 42).encode()


class ReportSearch(base.job.BaseModule):
    """ Generates reports from keywords files
    Parameter:
        path (str): filename with keywords to seek

    Configuration:
        - **keyfile**: filename with keywords in case path is not specified
        - **search_dir**: output directory for StringSearch generated files

    """
    def run(self, path=""):
        keyfile = path
        if not keyfile:
            keyfile = self.myconfig('keyfile')
        check_file(keyfile, error_missing=True)
        keywords = getSearchItems(keyfile)

        for kname, regex in keywords.items():
            self.report_search_kw(kname, regex)
        return []

    def report_search_kw(self, keyword, regex):
        """ Creates a pdf file from 'all_kw' file, using LaTex.

        Parameters:
            keyword (str): keyword name
            regex (str): regular expression associated to keyword
        """

        # TODO: do not break lines. Use lstlisting or something else
        pdflatex = self.myconfig('pdflatex', '/usr/bin/pdflatex')

        search_path = self.myconfig('search_dir')
        check_directory(search_path, error_missing=True)
        report_path = self.myconfig('outdir')
        check_directory(report_path, create=True)

        kw_utf8 = ''.join([i + '.' for i in keyword])
        # Avoid LaTeX special characters
        replaces = [(u'\ufffd', "."), ("\\", "/"), (r"{", "("), (r"]", ")"),
                    (r"$", "\\$"), (r"_", "\\_"), (r"%", "\\%"), (r"}", ")"),
                    (r"^", "."), (r"#", "\\#"), (r"~", "."), ("&", "\\&"),
                    ('"', "'"), (r"€", "euro")]
        line_width = 68  # number of characters per line in tex file

        for file in os.listdir(search_path):
            if not file.startswith("all_{}".format(keyword)):
                continue
            self.logger().info('Creating file {}'.format(file + '.pdf'))

            with open(os.path.join(report_path, file + ".tex"), "w") as foutput:

                foutput.write("\\documentclass[a4paper,11pt,oneside]{report}\n\\usepackage[spanish]{babel}\n")
                foutput.write("\\usepackage[utf8]{inputenc}\n")
                foutput.write("\\usepackage[pdftex]{color,graphicx}\n")
                foutput.write("\\usepackage[pdftex,colorlinks]{hyperref}\n")
                foutput.write("\\usepackage{fancyvrb}\n")
                foutput.write("\\usepackage{eurosym}\n")
                foutput.write("\\usepackage{listings}\n")
                foutput.write("\\lstset{breakatwhitespace=false,breaklines=true,frame=single}\n")
                foutput.write("\\UseRawInputEncoding\n")
                foutput.write("\\begin{document}\n\n")
                foutput.write("\\section*{blindsearches in disk. Keyword:  \\emph{" + keyword + "}}\n")
                initial = True

                if os.path.getsize(os.path.join(search_path, file)) == 0:
                    foutput.write("\\end{document}\n")
                    continue

                with open(os.path.join(search_path, file), "rb") as finput:
                    for line in finput:
                        line = line.decode("iso8859-15", "replace")
                        for r in replaces:
                            line = line.replace(r[0], r[1])

                        if line.startswith('Pt: p'):  # Block information
                            foutput.write("\\end{Verbatim}\n\n" if not initial else "")
                            foutput.write("\\newpage\n" if not initial else "")
                            initial = False
                            foutput.write("\\begin{lstlisting}\n")
                            foutput.write(line)
                            foutput.write("\\end{lstlisting}\n")
                            foutput.write("\\begin{Verbatim}[commandchars=\\\\\\{\\}]\n")
                            continue

                        line = re.sub("[\x00-\x09\x0B-\x1F\x7F-\xFF]", ".", line)
                        # Write by chuncks. Note: Some hits may be missed this way
                        for chunk_line in [line[i:i + line_width] for i in range(0, len(line), line_width)]:
                            chunk_line = re.sub('({})'.format(regex), r"\\colorbox{green}{" + r'\1' + r"}", chunk_line, flags=re.I | re.M)
                            chunk_line = re.sub('({})'.format(kw_utf8), r"\\colorbox{green}{" + r'\1' + r"}", chunk_line, flags=re.I | re.M)
                            foutput.write(chunk_line + "\n")

                foutput.write("\\end{Verbatim}\n")
                foutput.write("\\end{document}\n")

            run_command([pdflatex, "-output-directory", report_path, file + ".tex"], logger=self.logger())
            break

        else:
            self.logger().warning('No file: all_{}. Perhaps there is no match for the keyword'.format(keyword))

        for file in os.listdir(report_path):
            if file.endswith(".log") or file.endswith(".tex") or file.endswith(".aux") or file.endswith(".toc") or file.endswith(".out") or file.endswith(".synctex.gz"):
                os.remove(os.path.join(report_path, file))


class SearchEmailAddresses(base.job.BaseModule):

    def run(self, path=""):
        """ Generates a list with number of times an email address apears in strings """

        regex = r"[a-z0-9._-]{2,25}@[a-z0-9.-]{3,35}\.[a-z]{2,8}"

        self.logger().info("Searching email addresses")
        string_path = self.config.get('plugins.common.RVT_string.StringGenerate', 'outdir')

        counts = searchCountRegex(regex, string_path, grep=self.myconfig('grep', '/bin/grep'), logger=self.logger())

        with open(os.path.join(self.myconfig('outdir'), "count_emails.txt"), "w") as f:
            for e, n in counts.most_common():
                f.write("{}\t{}\n".format(n, e))
        self.logger().info("SearchEmailAddresses done")
        return []


class SearchAccounts(base.job.BaseModule):

    def read_config(self):
        super().read_config()
        self.set_default_config('accounts', os.path.join(self.config.config['common']['plugindir'], 'list_accounts.txt'))

    def run(self, path=""):
        """ Search credit card accounts in strings """

        import collections

        regex = r"(ES\d{2}[.\s-]+\d{4}[.\s-]+\d{4}[.\s-]+\d{4}[.\s-]+\d{4}[.\s-]+\d{4}|ES\d{2}[.\s-]+\d{4}[.\s-]+\d{4}[.\s-]+\d{2}[.\s-]+\d{10}|\d{4}[.\s-]+\d{4}[.\s-]+\d{2}[.\s-]+\d{10})"

        self.logger().info("Finding accounts")
        string_path = self.config.get('plugins.common.RVT_string.StringGenerate', 'outdir')
        counts = searchCountRegex(regex, string_path, grep=self.myconfig('grep', '/bin/grep'))

        valids = collections.Counter()
        banks = {}
        with open(self.myconfig('accounts'), 'r') as fbanks:
            for i in fbanks:
                aux = i.split("|")
                banks[int(aux[0])] = aux[1].strip()

        with open(os.path.join(self.myconfig('outdir'), "raw_count_accounts.txt"), "w") as f:
            for e, n in counts.most_common():
                if not e:
                    continue
                f.write("{}\t{}\n".format(n, e))
                v = self.validate(e, banks)
                if v != "":
                    valids[v] += n

        with open(os.path.join(self.myconfig('outdir'), "valid_count_accounts.txt"), "w") as f:
            for e, n in valids.most_common():
                f.write("{}\t{}\n".format(n, e))
        self.logger().info("SearchAccounts done")
        return []

    def remove_separators(self, texto):
        """ Auxiliary function to remove chars """

        chars_to_remove = (' ', "\t", ".", "-")
        for i in chars_to_remove:
            texto = texto.replace(i, "")
        return texto

    def control_digits(self, account):
        """ Auxiliary function """

        control = 0
        control += int(account[0]) * 4 + int(account[1]) * 8 + int(account[2]) * 5 + int(account[3]) * 10
        control += int(account[4]) * 9 + int(account[5]) * 7 + int(account[6]) * 3 + int(account[7]) * 6
        d1 = 11 - control % 11
        if d1 == 10:
            d1 = 1
        elif d1 == 11:
            d1 = 0
        control = 0
        control += int(account[10]) + int(account[11]) * 2 + int(account[12]) * 4 + int(account[13]) * 8 + int(account[14]) * 5
        control += int(account[15]) * 10 + int(account[16]) * 9 + int(account[17]) * 7 + int(account[18]) * 3 + int(account[19]) * 6
        d2 = 11 - control % 11
        if d2 == 10:
            d2 = 1
        elif d2 == 11:
            d2 = 0
        return "{}{}".format(d1, d2)

    def validate(self, account, banks):
        """ Returns an account in a normalized format
        Args:
            account (str): string number to normalize
            banks (dict): dict that relates account with bank
        Returns:
            string: account in a normalized format or empty string if is not a valid account number"""

        aux = account
        if account.startswith("ES"):
            aux = re.search(r"ES\d+[.\s-](.*)", account)
            aux = aux.group(1)
        aux = self.remove_separators(aux)
        if len(aux) < 20:
            return ""

        if int(self.control_digits(aux)) != int(aux[8:10]):
            self.logger().warning("{} is not a valid account".format(aux))
            return ""
        entity = int(aux[0:4])
        control_IBAN = 98 - int(aux + "142800") % 97
        if control_IBAN < 10:
            control_IBAN = "0" + str(control_IBAN)

        if entity in banks:
            return("ES{} {} {} {} {} {}; {}".format(control_IBAN, aux[0:4], aux[4:8], aux[8:12], aux[12:16], aux[16:20], banks[entity]))
        else:
            return("ES{} {} {} {} {} {}".format(control_IBAN, aux[0:4], aux[4:8], aux[8:12], aux[12:16], aux[16:20]))


class OutSearch(base.job.BaseModule):

    def run(self, keyfile=""):
        """
        Searche contents of regex in output dir except in strings, searches and parser folders
        """
        self.logger().info("Searching at output folder")
        if not keyfile:
            keyfile = self.myconfig('keyfile')
        check_file(keyfile, error_missing=True)

        grep = self.config.get('plugins.common', 'grep', '/bin/grep')

        skip_folders = ("strings", "parser", "searches")

        self.logger().info("Getting key list from {}".format(keyfile))
        keywords = getSearchItems(keyfile)

        temp_dir = tempfile.mkdtemp('outsearch')
        outdir = self.myconfig('outdir')
        check_directory(outdir, create=True)

        for kw, srch in keywords.items():
            output_file = os.path.join(temp_dir, "outsearch_{}.txt".format(kw))
            with open(output_file, "w") as f:
                f.write("\nKeyword: {}\n-----------------------------\n\n".format(srch))
                f.flush()

                for item in os.listdir(self.myconfig('outputdir')):
                    folder = os.path.join(self.myconfig('outputdir'), item)
                    if os.path.isdir(folder) and item not in skip_folders:
                        run_command([grep, "-ilR", srch, item], stdout=f, from_dir=self.myconfig('outputdir'), logger=self.logger())

        try:
            for file in os.listdir(temp_dir):
                shutil.copy(os.path.join(temp_dir, file), os.path.join(outdir, file))
        finally:
            shutil.rmtree(temp_dir)

        self.logger().info("OutSearch done")
        return []
