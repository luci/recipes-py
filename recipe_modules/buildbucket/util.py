# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime
import re
import urlparse

from .proto import common_pb2


# UTC datetime corresponding to zero Unix timestamp.
EPOCH = datetime.datetime.utcfromtimestamp(0)


def parse_http_host_and_path(url):
  parsed = urlparse.urlparse(url)
  if not parsed.scheme:
    parsed = urlparse.urlparse('https://' + url)
  if (parsed.scheme in ('http', 'https') and
      not parsed.params and
      not parsed.query and
      not parsed.fragment):
    return parsed.netloc, parsed.path
  return None, None


def parse_gitiles_repo_url(repo_url):
  host, project = parse_http_host_and_path(repo_url)
  assert host and project and '+' not in project.split('/'), (
      'invalid repo_url %s' % repo_url)
  project = project.strip('/')
  if project.startswith('a/'):
    project = project[len('a/'):]
  if project.endswith('.git'):
    project = project[:-len('.git')]
  return host, project


def is_sha1_hex(sha1):
  return sha1 and re.match('^[0-9a-f]{40}$', sha1)


def _parse_build_set(bs_string):
  """Parses a buildset string to GerritChange or GitilesCommit.

  A port of
  https://chromium.googlesource.com/infra/luci/luci-go/+/fe4e304639d11ca00537768f8bfbf20ffecf73e6/buildbucket/buildset.go#105
  """
  assert isinstance(bs_string, basestring)
  p = bs_string.split('/')
  if '' in p:
    return None

  n = len(p)

  if n == 5 and p[0] == 'patch' and p[1] == 'gerrit':
    return common_pb2.GerritChange(
        host=p[2],
        change=int(p[3]),
        patchset=int(p[4])
    )

  if n >= 5 and p[0] == 'commit' and p[1] == 'gitiles':
    if p[n-2] != '+' or not is_sha1_hex(p[n-1]):
      return None
    return common_pb2.GitilesCommit(
        host=p[2],
        project='/'.join(p[3:n-2]), # exclude plus
        id=p[n-1],
    )

  return None


def _parse_buildset_tags(tags):
  bs_prefix = 'buildset:'
  for t in tags:
    if t.startswith(bs_prefix):
      bs = _parse_build_set(t[len(bs_prefix):])
      if bs:
        yield bs


def timestamp_to_datetime(value):
  """Converts integer timestamp in microseconds since epoch to UTC datetime."""
  assert isinstance(value, (int, long, float)), value
  return EPOCH + datetime.timedelta(microseconds=value)
