#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
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

""" An RVT2 plugin to:

- parse documents and directories using Apache Tika and saving the data as json.
- parse the output from other modules and save the data as json.
- index these JSON into an ElasticSearch server.
- query, tag and export the data in an ElasticSearach server.

In order to use these modules, you'll need a Tika server and/or an ElasticSearch server running  in the network.

"""
