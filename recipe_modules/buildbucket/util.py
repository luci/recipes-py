# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime
import re
import urlparse

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


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
  if not (host and project and '+' not in project.split('/')):
    raise ValueError('invalid repo_url %s' % (repo_url,))
  project = project.strip('/')
  if project.startswith('a/'):
    project = project[len('a/'):]
  if project.endswith('.git'):
    project = project[:-len('.git')]
  return host, project


def is_sha1_hex(sha1):
  return sha1 and re.match('^[0-9a-f]{40}$', sha1)


def tags(**tags):
  """Helper method to generate a list of StringPair messages.

  This method is useful to prepare tags argument for ci/try_build above and
  schedule methods in the api.py.

  Args:
  * tags: Dict mapping keys to values. A value can be a list of values in
    which case multiple tags for the same key will be created.

  Returns:
    List of common_pb2.StringPair messages.
  """
  messages = []
  for key, values in tags.iteritems():
    if not isinstance(values, list):
      values = [values]
    for value in values:
      messages.append(common_pb2.StringPair(key=key, value=value))
  return messages
