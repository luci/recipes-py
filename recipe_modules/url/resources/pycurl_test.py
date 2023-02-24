#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Unit Tests for pycurl.py"""

import os
import requests
import sys
import unittest
from unittest import mock

import pycurl


class PyCurlTest(unittest.TestCase):
  def setUp(self):
    mock.patch('requests.Session').start()
    self.addCleanup(mock.patch.stopall)

  def testSuccess(self):
    requests.Session().get().status_code = requests.codes.ok
    requests.Session().get().iter_content.return_value = [
        b'ok',
    ]
    requests.Session().get().headers = {
        'Content-Length': 2,
    }

    code, total = pycurl._download('https://test/', os.devnull, None, 0, '')
    self.assertTrue(code == requests.codes.ok)
    self.assertTrue(total == 2)

  def testShortRead(self):
    requests.Session().get().status_code = requests.codes.ok
    requests.Session().get().iter_content.return_value = [
        b'short',
    ]
    requests.Session().get().headers = {
        'Content-Length': 6,
    }

    with self.assertRaises(ValueError) as context:
      pycurl._download('https://test/', os.devnull, None, 0, '')
    self.assertTrue('Expected content length:' in str(context.exception))


if __name__ == '__main__':
  if '-v' in sys.argv:
    logging.basicConfig(level=logging.DEBUG)
  unittest.main()
