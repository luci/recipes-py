# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import re

from .proto import common_pb2


def parse_gitiles_repo_url(repo_url):
  m = re.match(r'^(https?://)?([^/]+)/([^\+]+)$', repo_url)
  assert m, 'invalid repo_url %r' % repo_url
  host = m.group(2)
  project = m.group(3).rstrip('/')
  if project.startswith('a/'):
    project = project[len('a/'):]
  if project.endswith('.git'):
    project = project[:-len('.git')]
  return host, project


def parse_tag(tag):
  if isinstance(tag, common_pb2.StringPair):
    return tag
  k, v = tag.split(':', 1)
  return common_pb2.StringPair(key=k, value=v)
