# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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

  def tryserver(self, **kwargs):
    """
    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a rietveld tryjob on the tryserver, and return the blob.
    """
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
    Merge kwargs into a typical buildbot properties blob for a job fired off
    by a gerrit tryjob on the tryserver, and return the blob.

    Arguments:
      full_project_name: (required) name of the project in Gerrit.
      gerrit_host: hostname of the gerrit server.
    """
    gerrit_host = gerrit_host or 'chromium.googlesource.com'
    ret = self.generic(
        branch='',
        category='cq',
        gerrit='https://%s' % gerrit_host,
        patch_storage='gerrit',
        project=full_project_name,
        patch_project=full_project_name,
        reason='CQ',
        repository='https://%s/%s' % (gerrit_host, full_project_name),
        requester='commit-bot@chromium.org',
        revision='HEAD',
    )
    ret.properties.update({
        'event.change.id': u'infra%2Finfra~master~Ideadbeaf',
        'event.change.number': 338811,
        'event.change.url': u'https://chromium-review.googlesource.com/#/c/338811',
        'event.patchSet.ref': u'refs/changes/11/338811/3',
    })
    ret.properties.update(kwargs)
    return ret
