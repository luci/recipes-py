# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import re
import urlparse

from recipe_engine import recipe_test_api

class PropertiesTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, **kwargs):
    ret = self.test(None)
    ret.properties.update(kwargs)
    return ret

  def generic(self, **kwargs):
    """
    Merge kwargs into a typical buildbot properties blob, and return the blob.
    """
    ret = self(
        blamelist=['cool_dev1337@chromium.org', 'hax@chromium.org'],
        buildbotURL='http://c.org/p/cr/',
        buildername='TestBuilder',
        buildnumber=571,
        mastername='chromium.testing.master',
        slavename='TestSlavename',
        workdir='/path/to/workdir/TestSlavename',
    )
    ret.properties.update(kwargs)
    return ret

  def scheduled(self, **kwargs):
    """
    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a chrome/trunk svn scheduler, and return the blob.
    """
    ret = self.generic(
        branch='TestBranch',
        project='',
        repository='svn://svn-mirror.golo.chromium.org/chrome/trunk',
        revision='204787',
    )
    ret.properties.update(kwargs)
    return ret

  def git_scheduled(self, **kwargs):
    """
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

  def _gerrit_tryserver(self, **kwargs):
    # Call it through self.tryserver with (gerrit_project='infra/infra').
    project = kwargs.pop('gerrit_project')
    gerrit_url = kwargs.pop('gerrit_url', None)
    git_url = kwargs.pop('git_url', None)
    if not gerrit_url and not git_url:
      gerrit_url = 'https://chromium-review.googlesource.com'
      git_url = 'https://chromium.googlesource.com/' + project
    elif gerrit_url and not git_url:
      parsed = list(urlparse.urlparse(gerrit_url))
      m = re.match(r'^((\w+)(-\w+)*)-review.googlesource.com$', parsed[1])
      if not m: # pragma: no cover
        raise AssertionError('Can\'t guess git_url from gerrit_url "%s", '
                             'specify it as extra kwarg' % parsed[1])
      parsed[1] = m.group(1) + '.googlesource.com'
      parsed[2] = project
      git_url = urlparse.urlunparse(parsed)
    elif git_url and not gerrit_url:
      parsed = list(urlparse.urlparse(git_url))
      m = re.match(r'^((\w+)(-\w+)*).googlesource.com$', parsed[1])
      if not m: # pragma: no cover
        raise AssertionError('Can\'t guess gerrit_url from git_url "%s", '
                             'specify it as extra kwarg' % parsed[1])
      parsed[1] = m.group(1) + '-review.googlesource.com'
      gerrit_url = urlparse.urlunparse(parsed[:2] + [''] * len(parsed[2:]))
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

  def tryserver(self, **kwargs):
    """
    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a rietveld tryjob on the tryserver, and return the blob.

    If gerrit_project is given, generated properties for tryjobs for Gerrit
    patches as if they were scheduled by CQ. In this case, gerrit_url and
    git_url could be used to customize expectations.
    """
    if kwargs.get('gerrit_project') is not None:
      return self._gerrit_tryserver(**kwargs)
    ret = self.generic(
        branch='',
        issue=12853011,
        patchset=1,
        project='chrome',
        repository='',
        requester='commit-bot@chromium.org',
        revision='HEAD',
        rietveld='https://codereview.chromium.org',
        patch_project='chromium',
    )
    ret.properties.update(kwargs)
    return ret
