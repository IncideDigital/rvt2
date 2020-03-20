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

import json
import os
import ast
import base.job
import base.commands
import base.config
import keras
import numpy
from keras.applications.inception_v3 import InceptionV3
from keras.preprocessing.image import load_img
from keras.preprocessing.image import img_to_array
from keras.applications.inception_v3 import preprocess_input
from keras.applications.inception_v3 import decode_predictions


def load_plugin(config):
    # Importing nudenet resets the logging system. Configure it again
    base.config.configure_logging(config)
    import logging
    logging.getLogger(__name__).info('Logging system reseted')


class AIClassify(base.job.BaseModule):
    """ Classify images using a classifier model, grouping classes.

    Module description:
        - **path**: A path to send to from_module.
        - **from_module**: Module that should return dictionaries with 'path' field containing an image file.
        - **yields*: ``{path:relative_to_casedir, aiclassify{classifier, results[], accumulative_probability}, preview}``
    """

    def run(self, path):
        """ Classify images in categories using a model """

        self.model = self.myconfig('model')
        self.threshold = float(self.myconfig('threshold'))
        self.min_threshold = float(self.myconfig('min_threshold'))
        self.max_items = self.myconfig('max_items')

        # if there is not a classifier, create it. This takes a long time, so create only one classifier (global variable)
        self.__load_model_conf()

        for image in self.from_module.run(path):
            img = os.path.join(self.myconfig('casedir'), image['path'])
            try:
                r, acc = self.predict(self.classifier, img)
            except Exception as exc:
                self.logger().info(exc)
                continue

            result = dict(path=image['path'], aiclassify=dict(classifier=self.model, classification=r, prob=acc), preview=image['path'])
            yield result

    def predict(self, model, image_path):
        '''
            inputs:
                image_paths: list of image paths or can be a string too (for single image)
        '''

        image = load_img(image_path, target_size=self.image_size)
        image = img_to_array(image)
        image = image.reshape((1, image.shape[0], image.shape[1], image.shape[2]))
        image = preprocess_input(image)
        model_preds = model.predict(image)
        sort_index_preds = numpy.flip(numpy.argsort(model_preds))[0]

        accumulate = 0.
        res = []
        if self.model == 'InceptionV3':
            pr = decode_predictions(model_preds, top=int(self.max_items))[0]
            accumulate = 0.
            for i in pr:
                if i[2] < self.min_threshold:
                    return res, accumulate
                accumulate += i[2]
                res.append(i[1])
                if accumulate > self.threshold:
                    return res, accumulate
            return res, accumulate
        for i in sort_index_preds:
            if model_preds[0][i] < self.min_threshold:
                return res, accumulate
            accumulate += model_preds[0][i]
            res.append(self.categories[i])
            if accumulate > self.threshold:
                return res, accumulate

    def __load_model_conf(self):
        text = ''
        conf_file = self.myconfig('models_conf')
        with open(conf_file, 'r') as cfg:
            text = cfg.read()
        content = json.loads(text)
        try:
            if self.model in content.keys():
                self.classifier = keras.models.load_model(os.path.join(self.myconfig('modelsdir'), content[self.model]['classifier']))
                self.categories = content[self.model]['categories']
                self.image_size = ast.literal_eval(content[self.model]['img_size'])
            else:
                self.logger().warning("AI model %s not found. Loading Inception V3" % self.model)
                self.classifier = InceptionV3()
                self.model = "InceptionV3"
                self.image_size = (299, 299)
        except Exception:
            raise Exception("Error loading {} model".format(self.model))
