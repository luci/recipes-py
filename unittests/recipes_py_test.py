#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64
import json
import unittest

import repo_test_util

import recipes
from recipe_engine import arguments_pb2
from google.protobuf import json_format as jsonpb


class TestOperationalArgs(unittest.TestCase):

  def test_operational_arg_parsing(self):
    # For convenience, we'll define the JSONPB data as a Python dict that we
    # will then dump into JSON.
    op_args = jsonpb.Parse(json.dumps({
      'properties': {'property': {
        'a': {'s': 'Hello'},
        'b': {'int': -12345},
        'c': {'uint': 12345},
        'd': {'d': 3.14159},
        'e': {'b': True},
        'f': {'data': base64.b64encode('\x60\x0d\xd0\x65')},
        'g': {'map': {
          'property': {
            'foo': {'s': 'FOO!'},
            'bar': {'map': {
              'property': {
                'baz': {'s': 'BAZ!'},
              },
            }},
          }},
        },
        'h': {'list': {
          'property': [
            {'s': 'foo'},
            {'s': 'bar'},
            {'s': 'baz'},
          ],
        }},
      }},
      'annotationFlags': {
        'emitTimestamp': True,
      },
    }), arguments_pb2.Arguments())

    self.assertEqual(
        recipes._op_properties_to_dict(op_args.properties.property),
        {
          u'a': u'Hello',
          u'b': -12345L,
          u'c': 12345L,
          u'd': 3.14159,
          u'e': True,
          u'f': '\x60\x0d\xd0\x65',
          u'g': {
            u'foo': u'FOO!',
            u'bar': {
              u'baz': u'BAZ!',
            },
          },
          u'h': [
            u'foo',
            u'bar',
            u'baz',
          ],
        })


if __name__ == '__main__':
  result = unittest.main()
