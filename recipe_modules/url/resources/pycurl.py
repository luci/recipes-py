#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

# NOTE: This was imported from Chromium's "tools/build" at revision:
# 65976b6e2a612439681dc42830e90dbcdf550f40

import argparse
import json
import logging
import os
import sys
import time

import requests
import requests.adapters
import requests.exceptions
import requests.models
from requests.packages.urllib3.util.retry import Retry


# Size of chunks (4MiB).
CHUNK_SIZE = 1024 * 1024 * 4


def _download(url, outfile, headers, transient_retry, strip_prefix):
  s = requests.Session()
  retry = None
  if transient_retry > 0:
    # See http://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html
    retry = Retry(
      total=transient_retry,
      connect=5,
      read=5,
      redirect=5,
      status_forcelist=range(500, 600),
      backoff_factor=0.2,
      raise_on_status=False,
    )
    print retry
    s.mount(url, requests.adapters.HTTPAdapter(max_retries=retry))


  logging.info('Connecting to %s ...', url)
  r = s.get(url, headers=headers, stream=True)
  if r.status_code != requests.codes.ok:
    r.raise_for_status()

  if outfile:
    fd = open(outfile, 'wb')
  else:
    fd = sys.stdout

  total = 0
  with fd:
    logging.info('Downloading %s ...', url)
    loaded_prefix = ''
    for chunk in r.iter_content(CHUNK_SIZE):
      total += len(chunk)

      if strip_prefix:
        remaining_prefix = strip_prefix[len(loaded_prefix):]
        round_prefix = chunk[:len(remaining_prefix)]
        loaded_prefix += round_prefix
        if round_prefix != remaining_prefix[:len(round_prefix)]:
          raise ValueError(
              'Expected prefix was not observed: %r != %r...' % (
              loaded_prefix, strip_prefix))
        chunk = chunk[len(loaded_prefix):]
        if not chunk:
          continue

      fd.write(chunk)
      logging.info('Downloaded %.1f MB so far', total / 1024 / 1024)
  return r.status_code, total


def main():
  parser = argparse.ArgumentParser(
      description='Get a url and print its document.',
      prog='./runit.py pycurl.py')
  parser.add_argument('--url', required=True, help='the url to fetch')
  parser.add_argument('--status-json', metavar='PATH', required=True,
      help='Write HTTP status result JSON. If set, all complete HTTP '
           'responses will exit with 0, regardless of their status code.')

  parser.add_argument('--transient-retry', type=int, default=10,
      help='Number of retry attempts (with exponential backoff) to make on '
           'transient failure (default is %(default)s).')
  parser.add_argument('--headers-json', type=argparse.FileType('r'),
      help='A json file containing any headers to include with the request.')
  parser.add_argument('--outfile', help='write output to this file')
  parser.add_argument('--strip-prefix', action='store', type=json.loads,
      help='Expect this string at the beginning of the response, and strip it.')

  args = parser.parse_args()

  headers = None
  if args.headers_json:
    headers = json.load(args.headers_json)

  if args.strip_prefix and len(args.strip_prefix) > CHUNK_SIZE:
    raise ValueError('Prefix length (%d) must be <= chunk size (%d)' % (
        len(args.strip_prefix), CHUNK_SIZE))

  status = {}
  try:
    status_code, size = _download(
        args.url, args.outfile, headers, args.transient_retry,
        args.strip_prefix)
    status = {
      'status_code': status_code,
      'success': True,
      'size': size,
    }
  except requests.HTTPError as e:
    body = e.response.text
    status = {
      'status_code': e.response.status_code,
      'success': False,
      'size': len(body),
      'error_body': body,
    }

  with open(args.status_json, 'w') as fd:
    json.dump(status, fd)
  return 0


if __name__ == '__main__':
  logging.basicConfig()
  logging.getLogger().setLevel(logging.INFO)
  logging.getLogger("requests").setLevel(logging.DEBUG)
  sys.exit(main())


##
# The following section is read by "vpython" and used to construct the
# VirtualEnv for this tool.
#
# These imports were lifted from "/bootstrap/venv.cfg".
##
# [VPYTHON:BEGIN]
#
# wheel: <
#   name: "infra/python/wheels/cryptography/${platform}_${py_version}_${py_abi}"
#   version: "version:1.8.1"
# >
#
# wheel: <
#   name: "infra/python/wheels/appdirs-py2_py3"
#   version: "version:1.4.3"
# >
#
# wheel: <
#   name: "infra/python/wheels/asn1crypto-py2_py3"
#   version: "version:0.22.0"
# >
#
# wheel: <
#   name: "infra/python/wheels/enum34-py2"
#   version: "version:1.1.6"
# >
#
# wheel: <
#   name: "infra/python/wheels/cffi/${platform}_${py_version}_${py_abi}"
#   version: "version:1.10.0"
# >
#
# wheel: <
#   name: "infra/python/wheels/idna-py2_py3"
#   version: "version:2.5"
# >
#
# wheel: <
#   name: "infra/python/wheels/ipaddress-py2"
#   version: "version:1.0.18"
# >
#
# wheel: <
#   name: "infra/python/wheels/packaging-py2_py3"
#   version: "version:16.8"
# >
#
# wheel: <
#   name: "infra/python/wheels/pyasn1-py2_py3"
#   version: "version:0.2.3"
# >
#
# wheel: <
#   name: "infra/python/wheels/pycparser-py2_py3"
#   version: "version:2.17"
# >
#
# wheel: <
#   name: "infra/python/wheels/pyopenssl-py2_py3"
#   version: "version:17.0.0"
# >
#
# wheel: <
#   name: "infra/python/wheels/pyparsing-py2_py3"
#   version: "version:2.2.0"
# >
#
# wheel: <
#   name: "infra/python/wheels/setuptools-py2_py3"
#   version: "version:34.3.2"
# >
#
# wheel: <
#   name: "infra/python/wheels/six-py2_py3"
#   version: "version:1.10.0"
# >
#
# wheel: <
#   name: "infra/python/wheels/requests-py2_py3"
#   version: "version:2.13.0"
# >
#
# [VPYTHON:END]
##
