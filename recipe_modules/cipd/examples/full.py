# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from recipe_engine import post_process
from recipe_engine.config import List, Single, ConfigList, ConfigGroup
from recipe_engine.recipe_api import Property

from PB.recipe_modules.recipe_engine.cipd.examples import full as full_pb

DEPS = [
  'buildbucket',
  'cipd',
  'json',
  'path',
  'platform',
  'properties',
  'step',
]

INLINE_PROPERTIES_PROTO = """
message PackageDir {
  string path = 1;
  repeated string exclusions = 2;
}

message InputProperties {
  bool use_pkg = 1;
  repeated string pkg_files = 2;
  repeated PackageDir pkg_dirs = 3;
  map<string, string> pkg_vars = 4;
  repeated string ver_files = 5;
  string install_mode = 6;
  repeated string refs = 7;
  map<string, string> tags = 8;
  repeated string metadata = 9;
  int32 max_threads = 10;
}
"""

PROPERTIES = full_pb.InputProperties


def RunSteps(api, props: full_pb.InputProperties):
  package_name = 'public/package/${platform}'
  package_instance_id = '7f751b2237df2fdf3c1405be00590fefffbaea2d'
  ensure_file = api.cipd.EnsureFile()
  ensure_file.add_package(package_name, package_instance_id)

  # Prepare some phony metadata for test cases.
  md = [
      api.cipd.Metadata(key='md_%d' % i, value=v)
      for i, v in enumerate(props.metadata)
  ]

  cipd_root = api.path.start_dir / 'packages'
  # Some packages don't require credentials to be installed or queried.
  api.cipd.ensure(cipd_root, ensure_file)
  api.cipd.ensure_file_resolve(ensure_file)
  with api.cipd.cache_dir(api.path.mkdtemp()):
    result = api.cipd.search(package_name,
                             tag='git_revision:40-chars-long-hash')
  r = api.cipd.describe(package_name, version=result[0].instance_id)
  api.step(
      'describe response', cmd=None).presentation.logs['parsed'] = (
          api.json.dumps(r._asdict(), indent=2).splitlines())


  # Others do, so provide creds first.
  private_package_name = 'private/package/${platform}'
  #packages[private_package_name] = 'latest'
  ensure_file.add_package(private_package_name, 'latest', subdir='private')
  api.cipd.max_threads = props.max_threads or None
  api.cipd.ensure(cipd_root, ensure_file, name='ensure private package')
  result = api.cipd.search(private_package_name, tag='key:value')
  api.cipd.describe(private_package_name,
                    version=result[0].instance_id,
                    test_data_tags=['custom:tagged', 'key:value'],
                    test_data_refs=['latest'])
  api.cipd.describe('default/test/data',
                    version=result[0].instance_id)

  # examples of describe calls returning empty results
  for ver in ('ref', 'tag:1.2.3', 'hash'*10):
    try:
      api.cipd.describe('empty/pkg', version=ver, test_data_tags=(),
                        test_data_refs=())
      assert False, "Previous step should have failed" # pragma: no cover
    except api.step.StepFailure:
      pass

  # Check if we have READER, WRITER and OWNER roles for public/package path.
  api.cipd.acl_check('public/package', reader=True, writer=True, owner=True)

  # Build & register new package version.
  api.cipd.build('fake-input-dir', 'fake-package-path', 'infra/fake-package')
  api.cipd.build('fake-input-dir', 'fake-package-path', 'infra/fake-package',
                 compression_level=9, install_mode='copy',
                 preserve_mtime=True, preserve_writable=True)
  api.cipd.register('infra/fake-package', 'fake-package-path',
                    refs=props.refs, tags=props.tags, metadata=md)

  # Create (build & register).
  if props.use_pkg:
    root = api.path.start_dir / 'some_subdir'
    pkg = api.cipd.PackageDefinition(
        'infra/fake-package',
        root,
        props.install_mode or '',
        preserve_mtime=True,
        preserve_writable=True)
    for fullpath in props.pkg_files:
      pkg.add_file(api.path.abs_to_path(fullpath))
    pkg.add_dir(root)
    for obj in props.pkg_dirs:
      pkg.add_dir(api.path.abs_to_path(obj.path), list(obj.exclusions))
    for pth in props.ver_files:
      pkg.add_version_file(pth)

    api.cipd.build_from_pkg(pkg, 'fake-package-path')
    api.cipd.register('infra/fake-package', 'fake-package-path',
                      refs=props.refs, tags=props.tags, metadata=md,
                      verification_timeout='10m')

    api.cipd.create_from_pkg(pkg, refs=props.refs, tags=props.tags, metadata=md)
  else:
    api.cipd.build_from_yaml(api.path.start_dir / 'fake-package.yaml',
                             'fake-package-path', pkg_vars=props.pkg_vars,
                             compression_level=9)
    api.cipd.register('infra/fake-package', 'fake-package-path',
                      refs=props.refs, tags=props.tags, metadata=md)

    api.cipd.create_from_yaml(api.path.start_dir / 'fake-package.yaml',
                              refs=props.refs, tags=props.tags, metadata=md,
                              pkg_vars=props.pkg_vars, compression_level=9,
                              verification_timeout='20m')

  # Set tag or ref of an already existing package.
  api.cipd.set_tag('fake-package',
                   version='long/weird/ref/which/doesn/not/fit/into/40chars',
                   tags={'dead': 'beaf', 'more': 'value'})
  api.cipd.set_ref('fake-package', version='latest', refs=['any', 'some'])
  # Search by the new tag.
  api.cipd.search('fake-package/${platform}', tag='dead:beaf')
  # Get the instances
  api.cipd.instances('fake-package/${platform}', limit=3)

  # Set metadata.
  api.cipd.set_metadata('fake-package', version='latest', metadata=[
      api.cipd.Metadata(key='key1', value='val1'),
      api.cipd.Metadata(key='key1', value='val2', content_type='text/plain'),
      api.cipd.Metadata(
          key='key2',
          value_from_file=api.path.start_dir / 'val1.json',
      ),
      api.cipd.Metadata(
          key='key2',
          value_from_file=api.path.start_dir / 'val2.json',
          content_type='application/json',
      ),
  ])

  # Fetch a raw package
  api.cipd.pkg_fetch(api.path.start_dir / 'fetched_pkg',
                     'fake-package/${platform}', 'some:tag')

  # Deploy a raw package
  api.cipd.pkg_deploy(
    api.path.start_dir / 'raw_root',
    api.path.start_dir / 'fetched_pkg')

  api.cipd.ensure(
      cipd_root,
      api.path.start_dir / 'cipd.ensure',
      name='ensure with existing file')
  api.cipd.ensure_file_resolve(
      api.path.start_dir / 'cipd.ensure',
      name='ensure-file-resolve with existing file')

  # Install a tool using the high-level helper function. This operation should
  # be idempotent, so subsequent attempts should not re-install the package.
  for _ in range(2):
    api.cipd.ensure_tool('infra/some_exe/${platform}', 'latest')

  # We install another tool from the same package; this shouldn't run another
  # install step, since the base package is the same..
  api.cipd.ensure_tool('infra/some_exe/${platform}', 'latest', 'other/path')

  # Install a tool using the high-level helper function, where the executable
  # isn't in the root of the package.
  exe = api.cipd.ensure_tool('some/some_exe/package/${platform}', 'latest',
                             executable_path='bin/some_exe')
  api.step('run some_exe', [exe, '-opt'])


def GenTests(api):
  def properties(
      use_pkg: bool = False,
      pkg_files: Sequence[str] = (),
      pkg_dirs: Sequence[full_pb.PackageDir] = (),
      pkg_vars: Mapping[str, str] | None = None,
      ver_files: Sequence[str] = (),
      install_mode: Literal['copy', 'symlink', ''] | None = None,
      refs: Sequence[str] = ('fake-ref-1', 'fake-ref-2'),
      tags: Mapping[str, str] | Sequence[tuple[str, str]] = (
          ('fake_tag_1', 'fake_value_1'),
          ('fake_tag_2', 'fake_value_2'),
      ),
      metadata: Sequence[str] = ('v1', 'v2'),
      max_threads: int | None = None,
  ) -> full_pb.InputProperties:
    props = full_pb.InputProperties(
        use_pkg=use_pkg,
        pkg_files=pkg_files,
        pkg_dirs=pkg_dirs,
        pkg_vars=pkg_vars or {},
        ver_files=ver_files,
        install_mode=install_mode or '',
        refs=refs,
        tags=dict(tags),
        metadata=metadata,
        max_threads=max_threads,
    )
    return api.properties(props)

  yield api.test(
      'basic',
      api.buildbucket.ci_build(),
      api.platform('linux', 64),
      properties(),
  )

  yield api.test(
      'mac64',
      api.buildbucket.ci_build(),
      api.platform('mac', 64),
      properties(),
  )

  yield api.test(
      'win64',
      api.buildbucket.ci_build(),
      api.platform('win', 64),
      properties(),
  )

  yield api.test(
      'max-threads',
      api.platform('linux', 64),
      properties(max_threads=2),
  )

  yield api.test(
      'describe-failed',
      api.platform('linux', 64),
      properties(),
      api.override_step_data(
          'cipd describe public/package/${platform}',
          api.cipd.example_error(
              'package "public/package/linux-amd64-ubuntu14_04" not registered',
          )),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'describe-many-instances',
      api.platform('linux', 64),
      properties(),
      api.override_step_data(
          'cipd search fake-package/${platform} dead:beaf',
          api.cipd.example_search(
              'public/package/linux-amd64-ubuntu14_04',
              instances=3
          )),
  )

  yield api.test(
      'search-empty-result',
      api.platform('linux', 64),
      properties(),
      api.override_step_data(
          'cipd search fake-package/${platform} dead:beaf',
          api.json.output({'result': None})
      ),
  )

  yield api.test(
      'basic_pkg',
      properties(
          use_pkg=True,
          pkg_files=[
            '[START_DIR]/some_subdir/a/path/to/file.py',
            '[START_DIR]/some_subdir/some_config.cfg',
          ],
          pkg_dirs=[
            {
              'path': '[START_DIR]/some_subdir/directory',
            },
            {
              'path': '[START_DIR]/some_subdir/other_dir',
              'exclusions': [
                r'.*\.pyc',
              ]
            },
          ],
          ver_files=['.versions/file.cipd_version'],
          install_mode='symlink',
      ),
  )

  yield api.test(
      'pkg_bad_verfile',
      properties(
          use_pkg=True,
          ver_files=['a', 'b'],
          install_mode='copy',
      ),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdownRE,
          r"add_version_file\(\) may only be used once.",
      ),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'pkg_bad_mode',
      properties(
          use_pkg=True,
          install_mode='',
      ),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          # SummaryMarkdownRE for py2/3 compatibility to be flexible about a
          # trailing comma in repr() for exceptions:
          # https://bugs.python.org/issue30399.
          post_process.SummaryMarkdownRE,
          r"invalid value for install_mode: ''",
      ),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'pkg_bad_file',
      properties(
          use_pkg=True,
          pkg_files=[
            '[START_DIR]/a/path/to/file.py',
          ],
          install_mode='copy',
      ),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          # SummaryMarkdownRE for py2/3 compatibility to be flexible about a
          # trailing comma in repr() for exceptions:
          # https://bugs.python.org/issue30399.
          post_process.SummaryMarkdownRE,
          r"path Path\(\[START_DIR\], 'a', 'path', 'to', 'file.py'\) is not "
          r"the package root Path\(\[START_DIR\], 'some_subdir'\) and not a "
          r"child thereof",
      ),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'basic_with_pkg_vars',
      properties(
          pkg_vars = {
            'pkg_var_1': 'pkg_val_1',
            'pkg_var_2': 'pkg_val_2',
          }
      )
  )

  yield api.test(
      'basic_with_no_refs_or_tags_or_md',
      properties(
          refs=[],
          tags={},
          metadata=[],
      ),
  )
