# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from recipe_engine import recipe_test_api

# TODO: make a real test api

class BuildbucketTestApi(recipe_test_api.RecipeTestApi):

  def ci_build(
      self,
      project='project',
      bucket='ci',  # shortname.
      builder='builder',
      tags=None,
      git_repo=None,
      revision='2d72510e447ab60a9728aeea2362d8be2cbd7789',
      hostname='cr-buildbucket.appspot.com'):
    """Emulate typical buildbucket CI build scheduled by luci-scheduler.

    Usage:

        yield (api.test('basic') +
               api.buildbucket.ci_build(project='my-proj', builder='win'))
    """
    if git_repo is None:  # pragma: no cover
      if 'internal' in project:
        git_repo = 'chrome-internal.googlesource.com/' + project
      else:
        git_repo = 'chromium.googlesource.com/' + project
    else:
      if git_repo.startswith('https://'):
        git_repo = git_repo[len('https://'):]
      if git_repo.endswith('.git'):
        git_repo = git_repo[:-len('.git')]
    tags = list(tags) if tags else []
    tags.extend([
      'user_agent:luci-scheduler',
      'scheduler_invocation_id:9110941813804031728',
      'builder:' + builder,
      'gitiles_ref:refs/heads/master',
      'buildset:commit/gitiles/%s/+/%s' % (git_repo.rstrip('/'), revision),
    ])
    return self.m.properties(buildbucket={
      'build': {
        'bucket': 'luci.%s.%s' % (project, bucket),
        'created_by': 'user:luci-scheduler@appspot.gserviceaccount.com',
        'created_ts': 1527292217677440,
        'id': '8945511751514863184',
        'project': project,
        'tags': tags,
      },
    })

  def try_build(
      self,
      project='project',
      bucket='try',  # shortname.
      builder='builder',
      tags=None,
      gerrit_host=None,
      change_number=123456,
      patch_set=7,
      hostname='cr-buildbucket.appspot.com'):
    """Emulate typical buildbucket try build scheduled by CQ.

    Usage:

        yield (api.test('basic') +
               api.buildbucket.try_build(project='my-proj', builder='win'))
    """
    if gerrit_host is None:
      if 'internal' in project:  # pragma: no cover
        gerrit_host = 'chrome-internal-review.googlesource.com'
      else:
        gerrit_host = 'chromium-review.googlesource.com'
    tags = list(tags) if tags else []
    tags.extend([
      'user_agent:cq',
      'builder:' + builder,
      'buildset:patch/gerrit/%s/%d/%d' % (
          gerrit_host.rstrip('/'), change_number, patch_set),
    ])
    return self.m.properties(buildbucket={
      'build': {
        'bucket': 'luci.%s.%s' % (project, bucket),
        'created_by': 'user:commit-bot@chromium.org',
        'created_ts': 1527292217677440,
        'id': '8945511751514863184',
        'project': project,
        'tags': tags,
      },
    })

  def simulated_buildbucket_output(self, additional_build_parameters):
    buildbucket_output = {
        'build':{
          'parameters_json': json.dumps(additional_build_parameters)
        }
    }
    return self.step_data(
        'buildbucket.get',
        stdout=self.m.raw_io.output_text(json.dumps(buildbucket_output)))
