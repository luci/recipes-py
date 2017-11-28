# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Module imported by other tests to automatically install a consistent test
environment.

This consists largely of system path manipulation.
"""

import hashlib
import struct
import unittest

try:
  from recipe_engine import env
except ImportError:
  import os
  import sys

  BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
      os.path.abspath(__file__)))))
  sys.path.insert(0, BASE_DIR)

  from recipe_engine import env

from recipe_engine.autoroll_impl.commit_list import CommitMetadata, CommitList
from recipe_engine import package_pb2

class BaseCommitTest(unittest.TestCase):
  def __init__(self, *args, **kwargs):
    super(BaseCommitTest, self).__init__(*args, **kwargs)
    self.cm_counter = 0
    self.cm_timestamp = 0

  def setUp(self):
    self.cm_counter = 0
    self.cm_timestamp = 1501807893

  def cm(self, pid='pid', deps=(), revision=None,
         author_email='author@example.com', commit_timestamp=None,
         message_lines=('message', 'lines'), roll_candidate=False):

    spec = package_pb2.Package(
      api_version=2,
      project_id=pid,
      canonical_repo_url='https://git.example.com/%s.git' % pid,
    )
    for commit in deps:
      pid = commit.spec.project_id
      spec.deps[pid].url = commit.spec.canonical_repo_url
      spec.deps[pid].revision = commit.revision

    if revision is None:
      revision = hashlib.sha1(struct.pack('!Q', self.cm_counter)).hexdigest()
      self.cm_counter += 1

    if commit_timestamp is None:
      commit_timestamp = self.cm_timestamp
      self.cm_timestamp += 60 * (int(revision[:2], 16)+1)

    return CommitMetadata(revision, author_email, commit_timestamp,
                          message_lines, spec, roll_candidate)

  def cl(self, count):
    return CommitList([self.cm() for _ in xrange(count)])
