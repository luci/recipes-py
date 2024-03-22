# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from future.moves.urllib.parse import urlparse, urlunparse
from past.builtins import basestring

import re

from google.protobuf.message import Message as PBMessage
from google.protobuf import json_format as jsonpb

from recipe_engine import recipe_test_api

class PropertiesTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, *proto_msgs, **kwargs):
    """Sets property data for this test case.

    You may pass a list of protobuf messages to use; their JSONPB
    representations will be merged together with `dict.update`.

    You may also pass explicit key/value pairs; these will be merged into
    properties at the top level with `dict.update`.
    """
    ret = self.test(None)

    for msg in proto_msgs:
      if not isinstance(msg, PBMessage):
        raise ValueError(
            'Positional arguments for api.properties must be protobuf messages.'
            ' Got: %r (type %r)' % (msg, type(msg)))
      ret.properties.update(**jsonpb.MessageToDict(
          msg, preserving_proto_field_name=True))

    for key, value in kwargs.items():
      if isinstance(value, PBMessage):
        value = jsonpb.MessageToDict(value, preserving_proto_field_name=True)
      # TODO(iannucci): recursively validate type of value to be all JSONish
      # types.
      # TODO(iannucci): recursively convert Path instances to string here.
      ret.properties[key] = value

    return ret

  def environ(self, *proto_msgs, **kwargs):
    """Sets environment data for this test case."""
    ret = self.test(None)

    to_apply = []

    for msg in proto_msgs:
      if not isinstance(msg, PBMessage):
        raise ValueError(
            'Positional arguments for api.properties must be protobuf messages.'
            ' Got: %r (type %r)' % (msg, type(msg)))
      to_apply.append(jsonpb.MessageToDict(
          msg, preserving_proto_field_name=True))

    to_apply.append(kwargs)

    for dictionary in to_apply:
      for key, value in dictionary.items():
        if not isinstance(value, (int, float, basestring)):
          raise ValueError(
              'Environment values must be int, float or string. '
              'Got: %r=%r (type %r)' % (key, value, type(value)))
        ret.environ[key] = str(value)

    return ret

  def generic(self, **kwargs):
    """DEPRECATED. Use `api.buildbucket.generic_build` instead.

    Merge kwargs into a typical buildbot properties blob, and return the blob.
    """
    ret = self(
        blamelist=['cool_dev1337@chromium.org', 'hax@chromium.org'],
        bot_id='test_bot',
        buildbotURL='http://c.org/p/cr/',
        buildername='TestBuilder',
        buildnumber=571,
        mastername='chromium.testing.master',
        slavename='TestSlavename',  # TODO(nodir): remove, in favor of bot_id
        workdir='/path/to/workdir/TestSlavename',
    )
    ret.properties.update(kwargs)
    return ret

  def scheduled(self, **kwargs):
    """DEPRECATED. Use `api.buildbucket.ci_build` instead.

    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a gitpoller/scheduler, and return the blob.
    """
    return self.git_scheduled(**kwargs)

  def git_scheduled(self, **kwargs):
    """DEPRECATED. Use `api.buildbucket.ci_build` instead.

    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a gitpoller/scheduler, and return the blob.
    """
    ret = self.generic(
        branch='master',
        project='',
        repository='https://chromium.googlesource.com/chromium/src.git',
        revision='c14d891d44f0afff64e56ed7c9702df1d807b1ee',
    )
    ret.properties.update(kwargs)
    return ret

  def tryserver(self, **kwargs):
    """DEPRECATED. Use `api.buildbucket.ci_build` instead.

    Simulates Buildbot tryserver build.
    """
    project = (
        kwargs.pop('gerrit_project', None) or
        kwargs.pop('project', 'chromium/src'))
    gerrit_url = kwargs.pop('gerrit_url', None)
    git_url = kwargs.pop('git_url', None)
    if not gerrit_url and not git_url:
      gerrit_url = 'https://chromium-review.googlesource.com'
      git_url = 'https://chromium.googlesource.com/' + project
    elif gerrit_url and not git_url:
      parsed = list(urlparse(gerrit_url))
      m = re.match(r'^((\w+)(-\w+)*)-review.googlesource.com$', parsed[1])
      if not m: # pragma: no cover
        raise AssertionError('Can\'t guess git_url from gerrit_url "%s", '
                             'specify it as extra kwarg' % parsed[1])
      parsed[1] = m.group(1) + '.googlesource.com'
      parsed[2] = project
      git_url = urlunparse(parsed)
    elif git_url and not gerrit_url:
      parsed = list(urlparse(git_url))
      m = re.match(r'^((\w+)(-\w+)*).googlesource.com$', parsed[1])
      if not m: # pragma: no cover
        raise AssertionError('Can\'t guess gerrit_url from git_url "%s", '
                             'specify it as extra kwarg' % parsed[1])
      parsed[1] = m.group(1) + '-review.googlesource.com'
      gerrit_url = urlunparse(parsed[:2] + [''] * len(parsed[2:]))
    assert project
    assert git_url
    assert gerrit_url
    # Support old and new style patch{set,issue} specification.
    patch_issue = int(kwargs.pop('issue', kwargs.pop('patch_issue', 456789)))
    patch_set = int(kwargs.pop('patchset', kwargs.pop('patch_set', 12)))
    # Note that new Gerrit patch properties all start with 'patch_' prefix.
    ret = self.generic(
        patch_storage='gerrit',
        patch_gerrit_url=gerrit_url,
        patch_project=project,
        patch_branch='master',
        patch_issue=patch_issue,
        patch_set=patch_set,
        patch_repository_url=git_url,
        patch_ref='refs/changes/%2d/%d/%d' % (
            patch_issue % 100, patch_issue, patch_set)
    )
    ret.properties.update(kwargs)
    return ret
