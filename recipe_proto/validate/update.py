#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Automatically updates the .proto files in this directory."""

import base64
import json
import os
import re
import sys

import requests

BASE_URL = 'https://chromium.googlesource.com/infra/luci/luci-go'
LOG_URL = BASE_URL+'/+log/main/%s?format=JSON&n=1'
GO_MOD_URL = BASE_URL+'/+/%s/go.mod?format=TEXT'
PKG_URL = 'github.com/envoyproxy/protoc-gen-validate'


def fetch(url):
  print('Fetching ' + url, file=sys.stderr)
  resp = requests.get(url)
  if resp.status_code != 200:
    raise requests.HTTPError(resp.text)
  return resp.text


def main():
  """Automatically updates validate.proto in this directory."""
  # find ver
  log = fetch(LOG_URL % 'go.mod')
  commit = str(json.loads(log[4:])['log'][0]['commit'])
  mods = base64.b64decode(fetch(GO_MOD_URL % commit)).decode('utf8')
  ver = None
  for m in mods.split('\n'):
    if re.match(r'\s*' + PKG_URL, m):
      ver = m.split()[1]
      break
  if not ver:
    print('Missing %s in go.mod' % PKG_URL, file=sys.stderr)
    return

  proto = fetch('https://%s/raw/%s/validate/validate.proto' % (PKG_URL, ver))
  lic = fetch('https://%s/raw/%s/LICENSE' % (PKG_URL, ver))
  dest_path = os.path.dirname(os.path.abspath(__file__))
  with open(dest_path + '/validate.proto', 'w') as f:
    f.write(proto)
  with open(dest_path + '/VERSION', 'w') as f:
    print('# Generated by update.py. DO NOT EDIT.', file=f)
    f.write(ver)
  with open(dest_path + '/LICENSE', 'w') as f:
    f.write(lic)


if __name__ == '__main__':
  main()
