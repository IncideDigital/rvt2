#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 INCIDE Digital Data S.L.
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

""" Modules to classify files using AI techniques """

try:
    from nudenet import NudeClassifier
except ImportError:
    # It won't crash when loading, but must be installed for the module to work
    pass
import base.job
import base.commands
import base.config
from base.utils import relative_path, check_directory
import os

__maintainer__ = 'Juanvi Vera'

classifier = None


def load_plugin(config):
    # Don't ask me why, but importing nudenet resets the logging system. Configure it again
    base.config.configure_logging(config)
    import logging
    logging.getLogger(__name__).info('Logging system reseted')


class NudeNetClassify(base.job.BaseModule):
    """ Classify an image using a NudeNet and a classifier model.

    Module description:
        - **path**: A path to an image, either relative to casedir or absolute
        - **from_module**: ignored
        - **yields*: ``{path:relative_to_casedir, aiclassify{classifier, results{safe, unsafe}, is_nude}, preview}``

    Configuration:
        - **model**: absolute path to the classifier model. Read INSTALL.md.
        - **threshold**: thresshold to consider a class as matched. Default 0.5.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('model', os.path.join(os.path.abspath(os.path.dirname(__file__)), 'classifier_model'))
        self.set_default_config('threshold', '0.5')

    def run(self, path):
        """ Classify an image using NudeNet."""
        # if there is not a classifier, create it. This takes a long time, so create only one classifier (global variable)
        global classifier
        if classifier is None:
            self.logger().debug('Creating classifier from model=%s', self.myconfig('model'))
            modelfile = self.myconfig('model')
            classifier = NudeClassifier(modelfile)
        threshold = float(self.myconfig('threshold'))

        self.logger().debug('Classifying path=%s', path)

        # classify path
        if os.path.isabs(path):
            abspath = path
            relpath = relative_path(path, self.myconfig('casedir'))
        else:
            abspath = os.path.join(self.myconfig('casedir'), path)
            relpath = path
        result = dict(path=relpath, aiclassify=dict(classifier='NudeNet'), preview=relpath)
        try:
            # we must convert the results, since they are returned as numpy object
            classification = classifier.classify(abspath)[abspath]
            result['aiclassify']['results'] = dict(
                safe=float(classification['safe']),
                unsafe=float(classification['unsafe']))
            result['aiclassify']['is_nude'] = result['aiclassify']['results']['unsafe'] > threshold
        except Exception as exc:
            self.logger().warning('Cannot process path=%s %s', path, exc)
            result['aiclassify']['results'] = dict(safe=None, unsafe=None)
            result['aiclassify']['is_nude'] = None
        yield result


class NudeNetClassifyVideo(NudeNetClassify):
    """ Classify an image using a NudeNet and a classifier model.

    Module description:
        - **path**: A path to a video, either relative to casedir or absolute
        - **from_module**: a module chain containing aiclassify.GenerateVideoSnapshots: preview must be defined.
        - **yields*: ``{path:relative_to_casedir, aiclassify{classifier, results{safe, unsafe}, is_nude}, preview}``.
            Results is the result of the image with a larger unsafe percentage.

    Configuration:
        - **model**: absolute path to the classifier model. Read INSTALL.md.
        - **threshold**: thresshold to consider a class as matched. Default 0.5.
        - **threshold_preview**: The percentage of preview images that must be classified as nude to classify as nude. 0 means "any"
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('threshold_preview', '0')

    def run(self, path):
        """ Classify a video using NudeNet."""
        if os.path.isabs(path):
            relpath = relative_path(path, self.myconfig('casedir'))
            abspath = path
        else:
            relpath = path
            abspath = os.path.join(self.myconfig('casedir'), path)

        self.check_params(abspath, check_path=True, check_path_exists=True)
        # if there is not a classifier, create it. This takes a long time, so create only one classifier (global variable)
        global classifier
        if classifier is None:
            self.logger().debug('Creating classifier from model=%s', self.myconfig('model'))
            modelfile = self.myconfig('model')
            classifier = NudeClassifier(modelfile)

        if os.path.isabs(path):
            relpath = relative_path(path, self.myconfig('casedir'))
        else:
            relpath = path

        previews = list(self.from_module.run(path))
        # if the previews could be created, the video cannot be parsed: return None
        if not previews or len(previews) == 0:
            return [dict(
                path=relpath,
                aiclassify=dict(classifier='NudeNet', results=dict(safe=None, unsafe=None), is_nude=None))
            ]

        # else, the video was parsed correctly: test each one of the previews.
        max_unsafe = 0
        min_safe = 0
        num_is_nude = 0
        preview_path = None
        for preview_image in previews[0]['preview']:
            # classify preview_image
            result = list(super().run(preview_image))[0]
            if result['aiclassify']['results']['unsafe'] is not None and result['aiclassify']['results']['unsafe'] > max_unsafe:
                max_unsafe = result['aiclassify']['results']['unsafe']
                min_safe = result['aiclassify']['results']['safe']
            if result['aiclassify']['is_nude']:
                num_is_nude += 1
                # if an image is unsafe: set the preview to this image
                preview_path = relative_path(preview_image, self.myconfig('casedir'))
        final_result = dict(classifier='NudeNet', results=dict(safe=min_safe, unsafe=max_unsafe), is_nude=None)
        if len(previews[0]['preview']) > 0:
            final_result['is_nude'] = (1.0 * num_is_nude / len(previews[0]['preview']) > float(self.myconfig('threshold_preview')))
            if preview_path is None:
                # if no preview path is already set, get the image in the middle
                preview_path = previews[0]['preview'][int(len(previews[0]['preview']) / 2)]
        return [dict(path=relpath, aiclassify=final_result, preview=preview_path)]


class GenerateVideoSnapshots(base.job.BaseModule):
    """ Generate snapshots for a video. These snapshots can be analysed later.

    This module depends on the external programs ``fmpeg`` and ``mediainfo``.

    Module description:
        - **path**: Absolute path of the video file. If it is not absolute, assume it is relative to the *casedir*.
        - **from_module**: ignored
        - **yields*: ``{path (relative to casedir), preview=[list of paths relative to casedir]}``

    Configuration:
        - **outdir**: the output directory for the snapshots.
    """
    def read_config(self):
        super().read_config()
        self.set_default_config('outdir', os.path.join(self.config.get('plugins.common', 'auxdir'), 'videosnapshots'))

    def run(self, path):
        self.check_params(path, check_path=True)
        output_dir = self.myconfig('outdir')
        check_directory(output_dir, create=True)

        if not os.path.isabs(path):
            path = os.path.join(self.myconfig('casedir'), path)

        try:
            frame_rate = self._snapshowFrequency(path)
            export_path = os.path.join(output_dir, relative_path(path, self.myconfig('casedir')))
            self.logger().debug('path=%s frame_rate=%s export_path=%s', path, frame_rate, export_path)

            check_directory(export_path, create=True)
            base.commands.run_command(r'ffmpeg -loglevel quiet -i "{}" -vf fps={} "{}"'.format(path, frame_rate, os.path.join(export_path, 'img%03d.jpg')))
            # subprocess.call(['ffmpeg', '-i', filename, '-vf', 'fps=%s' % frame_rate, r'img%03d.jpg'])
            return [dict(
                path=relative_path(path, self.myconfig('casedir')),
                preview=list(map(lambda p: relative_path(os.path.join(export_path, p), self.myconfig('casedir')), os.listdir(export_path))))]
        except Exception as exc:
            self.logger().warning('Cannot create snapshots from path=%s exc=%s', path, exc)
            return []

    def _snapshowFrequency(self, filepath):
        """
        Estimate the frequency to take snapshots

        Attrs:
            :filepath: The abosolute path of the video to test.

        Returns:
            The frequency to take snapshots, from '1/5' (1 snapshot every 5 seconds) to '1/60' (1 snapshot every 60 seconds)
        """
        nframes = base.commands.run_command(r'mediainfo --Output="Video;%FrameCount%" "{}"'.format(filepath), logger=self.logger())
        try:
            nframes = int(base.commands.run_command(r'mediainfo --Output="Video;%FrameCount%" "{}"'.format(filepath), logger=self.logger()).strip())
            #  nframes = base.commands.run_command(['mediainfo', r'--Output="Video;\%FrameCount\%"', filepath])
        except Exception:
            nframes = 7000  # default value

        if nframes < 1440:  # for vids less than 1 minute, takes snapshots every 5 secs
            return '1/5'
        elif nframes < 7200:  # for vids less than 5 minutes, takes snapshots every 10 secs
            return '1/10'
        elif nframes < 21600:  # for vids less than 15 minutes, takes snapshots every 20 secs
            return '1/20'
        elif nframes < 43200:  # for vids less than 30 minutes, takes snapshots every 30 secs
            return '1/30'
        return '1/60'  # for vids longer than 30 minutes, takes snapshots every minute
