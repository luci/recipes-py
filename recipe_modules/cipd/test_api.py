# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class CIPDTestApi(recipe_test_api.RecipeTestApi):

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
        'package': package_name.replace('${platform}', 'resolved-platform'),
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
        for subdir, packages in ensure_file.packages.iteritems()
    })

  def example_set_tag(self, package_name, version):
    return self._resultify({'': [{
        'package': package_name,
        'pin': self.make_pin(package_name, version)
    }]})

  example_set_ref = example_set_tag

  def example_search(self, package_name, instances=None):
    if instances is None:
      # Return one instance by default.
      return self._resultify([self.make_pin(package_name)])
    if isinstance(instances, int):
      instances = ['instance_id_%i' % (i+1) for i in xrange(instances)]
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
