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
    # Pop old style values from kwargs.
    patch_issue = int(kwargs.pop('issue', 456789))
    patch_set = int(kwargs.pop('patchset', 12))
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

  def tryserver_gerrit(self, full_project_name, gerrit_host=None, **kwargs):
    """
    DEPRECATED. Use tryserver(gerrit_project='infra/infra') instead.

    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a gerrit tryjob on the tryserver, and return the blob.

    Arguments:
      full_project_name: (required) name of the project in Gerrit.
      gerrit_host: hostname of the gerrit server.
        Example: chromium-review.googlesource.com.
    """
    # TODO(tandrii): remove this method.
    gerrit_host = gerrit_host or 'chromium-review.googlesource.com'
    parts = gerrit_host.split('.')
    assert parts[0].endswith('-review')
    parts[0] = parts[0][:-len('-review')]
    repository = 'https://%s/%s' % ('.'.join(parts), full_project_name)

    ret = self.generic(
        branch='',
        category='cq',
        gerrit='https://%s' % gerrit_host,
        patch_storage='gerrit',
        project=full_project_name,
        patch_project=full_project_name,
        reason='CQ',
        repository=repository,
        requester='commit-bot@chromium.org',
        revision='HEAD',
    )
    ret.properties.update({
        'event.change.id': u'%s~master~Ideadbeaf' %
            (full_project_name.replace('/', '%2F')),
        'event.change.number': 338811,
        'event.change.url': u'https://%s/#/c/338811' % gerrit_host,
        'event.patchSet.ref': u'refs/changes/11/338811/3',
    })
    ret.properties.update(kwargs)
    return ret
