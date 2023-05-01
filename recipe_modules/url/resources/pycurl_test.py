#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Unit Tests for pycurl.py"""

import io
import os
import requests
import sys
import tempfile
import unittest
from unittest import mock

import pycurl


class PyCurlTest(unittest.TestCase):
  def setUp(self):
    mock.patch('requests.Session').start()
    self.addCleanup(mock.patch.stopall)

  def testSuccess(self):
    r = requests.Session().get()
    r.status_code = requests.codes.ok
    r.headers = {'Content-Length': '2'}
    r.raw = io.BytesIO(b'ok')
    r.iter_content.return_value  = r.raw

    code, total = pycurl._download('https://test/', os.devnull, None, 0, '')
    self.assertTrue(code == requests.codes.ok)
    self.assertTrue(total == 2)

  def testShortRead(self):
    r = requests.Session().get()
    r.status_code = requests.codes.ok
    r.headers = {'Content-Length': '6'}
    r.raw = io.BytesIO(b'short')
    r.iter_content.return_value  = r.raw

    with self.assertRaises(ValueError) as context:
      pycurl._download('https://test/', os.devnull, None, 0, '')
    self.assertTrue('Expected content length:' in str(context.exception))

  def testInvalidContentLength(self):
    r = requests.Session().get()
    r.status_code = requests.codes.ok
    r.headers = {'Content-Length': 'abc'}
    r.raw = io.BytesIO(b'anything')
    r.iter_content.return_value  = r.raw

    with self.assertRaises(ValueError) as context:
      pycurl._download('https://test/', os.devnull, None, 0, '')
    self.assertTrue('invalid literal for int()' in str(context.exception))

  def testWithoutContentLength(self):
    r = requests.Session().get()
    r.status_code = requests.codes.ok
    r.headers = {}
    r.raw = io.BytesIO(b'anything')
    r.iter_content.return_value  = r.raw

    code, total = pycurl._download('https://test/', os.devnull, None, 0, '')
    self.assertTrue(code == requests.codes.ok)
    self.assertTrue(total == 8)

  def testStripPrefix(self):
    r = requests.Session().get()
    r.status_code = requests.codes.ok
    r.headers = {}
    r.raw = io.BytesIO(b")]}'\nok")
    r.iter_content.return_value = r.raw

    outfile = tempfile.NamedTemporaryFile()
    code, total = pycurl._download('https://test/', outfile.name, None, 0,
                                   ")]}'\n")
    self.assertTrue(outfile.read(), b'ok')


if __name__ == '__main__':
  if '-v' in sys.argv:
    logging.basicConfig(level=logging.DEBUG)
  unittest.main()
