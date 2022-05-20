# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from future.utils import iteritems

from recipe_engine import recipe_test_api

from .api import EnsureFile


class CIPDTestApi(recipe_test_api.RecipeTestApi):

  EnsureFile = EnsureFile

  def make_resolved_package(self, v):
    return v.replace('${platform}', 'resolved-platform')

  def make_resolved_version(self, v):
    if not v:
      return '40-chars-fake-of-the-package-instance_id'
    if len(v) == 40:
      return v
    # Truncate or pad to 40 chars.
    prefix = 'resolved-instance_id-of-'
    if len(v) + len(prefix) >= 40:
      return '%s%s' % (prefix, v[:40-len(prefix)])
    return '%s%s%s' % (prefix, v, '-' * (40 - len(prefix) - len(v)))

  def make_pin(self, package_name, version=None):
    return {
        'package': self.make_resolved_package(package_name),
        'instance_id': self.make_resolved_version(version),
    }

  def _resultify(self, result, error=None, retcode=None):
    dic = {'result': result}
    if error:
      dic['error'] = error
    return self.m.json.output(dic, retcode=retcode)

  def example_error(self, error, retcode=None):
    return self._resultify(
        result=None,
        error=error,
        retcode=1 if retcode is None else retcode)

  def example_acl_check(self, package_path, check=True):
    return self._resultify(check)

  def example_build(self, package_name, version=None):
    return self._resultify(self.make_pin(package_name, version))

  example_register = example_build
  example_pkg_fetch = example_build
  example_pkg_deploy = example_build

  def example_ensure(self, ensure_file):
    return self._resultify({
        subdir or '': [self.make_pin(name, version)
                       for name, version in sorted(packages)]
        for subdir, packages in iteritems(ensure_file.packages)
    })

  def example_ensure_file_resolve(self, ensure_file):
    return self._resultify({
        subdir or '': [{
            'package': self.make_resolved_package(name),
            'pin': self.make_pin(name, version)}
            for name, version in sorted(packages)]
        for subdir, packages in iteritems(ensure_file.packages)
    })

  def example_set_tag(self, package_name, version):
    return self._resultify([{
        'package': package_name,
        'pin': self.make_pin(package_name, version)
    }])

  def example_set_metadata(self, package_name, version):
    return self._resultify([{
        'package': package_name,
        'pin': self.make_pin(package_name, version)
    }])

  def example_set_ref(self, package_name, version):
    return self._resultify({'': [{
        'package': package_name,
        'pin': self.make_pin(package_name, version)
    }]})

  def example_search(self, package_name, instances=None):
    if instances is None:
      # Return one instance by default.
      return self._resultify([self.make_pin(package_name)])
    if isinstance(instances, int):
      instances = ['instance_id_%i' % (i+1) for i in range(instances)]
    return self._resultify([self.make_pin(package_name, instance)
                           for instance in instances])

  def example_describe(self, package_name, version=None,
                       test_data_refs=None, test_data_tags=None,
                       user='user:44-blablbla@developer.gserviceaccount.com',
                       tstamp=1446574210):
    assert not test_data_tags or all(':' in tag for tag in test_data_tags)

    if test_data_tags is None:
      test_data_tags = [
        'buildbot_build:some.waterfall/builder/1234',
        'git_repository:https://chromium.googlesource.com/some/repo',
        'git_revision:397a2597cdc237f3026e6143b683be4b9ab60540',
      ]

    if test_data_refs is None:
      test_data_refs = ['latest']

    # If user explicitly put empty tags/refs (i.e. ())
    if not test_data_refs and not test_data_tags:
      # quick and dirty version differentiation
      if ':' in version:
        return self._resultify(None, error='no such tag', retcode=1)
      if len(version) == 44 or len(version) == 40:
        return self._resultify(None, error='no such instance', retcode=1)
      return self._resultify(None, error='no such ref', retcode=1)

    return self._resultify({
        'pin': self.make_pin(package_name, version),
        'registered_by': user,
        'registered_ts': tstamp,
        'refs': [
          {
            'ref': ref,
            'modified_by': user,
            'modified_ts': tstamp,
            'instance_id': self.make_resolved_version(ref),
          }
          for ref in test_data_refs
        ],
        'tags': [
          {
            'tag': tag,
            'registered_by': user,
            'registered_ts': tstamp,
          }
          for tag in test_data_tags
        ],
    })

  def example_instances(self, package_name, limit=None,
                        user='user:44-blablbla@developer.gserviceaccount.com',
                        tstamp=1446574210):
    # Return two instances by default.
    limit = limit or 2
    instances =[]
    for i in range(limit):
      instance = {
          'pin': self.make_pin(package_name, 'instance_id_%i' % (i+1)),
          'registered_by': user,
          'registered_ts': tstamp-i-1,
      }
      # Add "latest" ref to the first instance
      if i == 0:
        instance['refs'] = ['latest']
      instances.append(instance)
    return self._resultify({'instances': instances})
