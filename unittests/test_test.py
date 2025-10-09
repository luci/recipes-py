#!/usr/bin/env vpython3
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


from __future__ import annotations

import argparse
import json
import os

from io import StringIO
from unittest import mock

from google.protobuf import json_format as jsonpb

# pylint: disable=import-error
import attr
import enum
import re

import test_env

from PB.recipe_engine.internal.test.runner import Outcome

from recipe_engine.internal.commands import test as test_parser
from recipe_engine.internal.commands.test import test_name

# pylint: disable=missing-docstring

class Common(test_env.RecipeEngineUnitTest):
  @attr.s(frozen=True)
  class JsonResult:
    text_output = attr.ib()
    data = attr.ib()

  def _run_test(self, *args, **kwargs):
    should_fail = kwargs.pop('should_fail', False)
    self.assertDictEqual(
        kwargs, {}, 'got additional unexpected kwargs: {!r}'.format(kwargs))

    json_out = self.tempfile()
    full_args = ['test'] + list(args) + ['--json', json_out]

    output, retcode = self.main.recipes_py(*full_args)
    expected_retcode = 1 if should_fail else 0
    self.assertEqual(
        retcode, expected_retcode,
        (
          '`recipes.py test {args}` had retcode '
          '{actual} != {expected}:\n{output}'
        ).format(
            args=' '.join(args),
            actual=retcode,
            expected=expected_retcode,
            output=output))
    with open(json_out, 'rb') as json_file:
      try:
        data = None
        results_data = json.load(json_file)
        if not isinstance(results_data, list):
          return self.JsonResult(output, results_data)
        for rd in results_data:
          for results in rd.get('test_results', {}).values():
            if 'diff' in results:
              results['diff']['lines'] = ['placeholder']
            for check in results.get('check', ()):
              check['lines'] = ['placeholder']
            if 'crash_mismatch' in results:
              results['crash_mismatch'] = ['placeholder']
            if 'bad_test' in results:
              results['bad_test'] = ['placeholder']
            if 'internal_error' in results:
              results['internal_error'] = ['placeholder']
            # We usually don't care about duration for our tests, especially
            # since it's pretty variable.
            if 'duration' in results:
              del results['duration']
          if 'coverage_percent' in rd:
            rd['coverage_percent'] = round(rd['coverage_percent'], 1)
          if 'unused_expectation_files' in rd:
            rd['unused_expectation_files'] = [
              os.path.relpath(fpath, self.main.path)
              for fpath in rd['unused_expectation_files']
            ]
          data = rd
      except Exception as ex:  # pylint: disable=broad-except
        if should_fail != 'crash':
          raise Exception(
              'failed to decode test json: {!r}\noutput:\n{}'.format(
                  ex, output))
        data = None
      return self.JsonResult(output, data)


  class OutcomeType(enum.Enum):
    diff = 1
    written = 2
    removed = 3
    check = 4
    crash = 5
    bad_test = 6
    internal_error = 7
    needs_infra_fail = 12


  def _outcome_json(self, per_test=None, coverage=100, uncovered_mods=(),
                    unused_expects=()):
    """Generates a JSON dict representing a runner.Outcome message.

    Args:
      * per_test (Dict[test name: str, Seq[OutcomeType]]) - Mapping of test name
        to a series of OutcomeTypes which that test had. `check` may be repeated
        multiple times to indicate multiple check failures.
      * coverage (float) - Percentage covered.
      * uncovered_mods (Seq[module name]) - modules which have NO possible test
        coverage.
      * unused_expects (Seq[file name]) - file paths relative to the main repo
        of unused expectation files (i.e. JSON files on disk without
        a corresponding test case).

    Returns a python dict which is the JSONPB representation of the Outcome.
    """
    ret = Outcome()

    if per_test is None:
      per_test = {'foo.basic': []}

    for test_name, outcome_types in (per_test or {}).items():
      results = ret.test_results[test_name]
      for type_ in outcome_types:
        if type_ == self.OutcomeType.diff:
          results.diff.lines[:] = ['placeholder']
        if type_ == self.OutcomeType.written:
          results.written = True
        if type_ == self.OutcomeType.removed:
          results.removed = True
        elif type_ == self.OutcomeType.check:
          results.check.add(lines=['placeholder'])
        elif type_ == self.OutcomeType.crash:
          results.crash_mismatch[:] = ['placeholder']
        elif type_ == self.OutcomeType.bad_test:
          results.bad_test[:] = ['placeholder']
        elif type_ == self.OutcomeType.internal_error:
          results.internal_error[:] = ['placeholder']
        elif type_ == self.OutcomeType.needs_infra_fail:
          results.global_warnings.append('expected SUCCESS, got INFRA_FAILURE')

    ret.coverage_percent = coverage
    ret.uncovered_modules.extend(uncovered_mods)
    ret.unused_expectation_files.extend(unused_expects)

    return jsonpb.MessageToDict(ret, preserving_proto_field_name=True)

  def setUp(self):
    super().setUp()
    self.deps = self.FakeRecipeDeps()
    self.main = self.deps.main_repo


class TestList(Common):
  def test_list(self):
    with self.main.write_recipe('foo'):
      pass

    self.assertDictEqual(
        self._run_test('list').data,
        {'format': 1, 'tests': ['foo.basic']})


class TestRun(Common):
  def test_basic(self):
    with self.main.write_recipe('foo'):
      pass

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json())

  def test_expectation_failure_empty(self):
    with self.main.write_recipe('foo') as recipe:
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertDictEqual(result.data, self._outcome_json(per_test={
      'foo.basic': [self.OutcomeType.diff],
    }))

  def test_expectation_failure_stop(self):
    """Test the failfast flag '--stop'

    Introduces two expectation errors and checks that only one is reported.
    """
    with self.main.write_recipe('foo2') as recipe:
      del recipe.expectation['basic']
    with self.main.write_recipe('foo') as recipe:
      del recipe.expectation['basic']

    test_run = self._run_test('run', '--stop', should_fail=True)
    results = test_run.data['test_results']
    self.assertEqual(len(results), 1)
    self.assertEqual(list(list(results.values())[0].keys())[0], 'diff')

  def test_expectation_failure_empty_filter(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield api.test('basic')
        yield api.test('second')
      ''')

    self.assertDictEqual(
        self._run_test(
            'run', '--filter', 'foo.second', should_fail=True).data,
        self._outcome_json(per_test={
          'foo.second': [self.OutcomeType.diff],
        }, coverage=0))

    self.assertDictEqual(
        self._run_test('run', '--filter', 'foo.basic').data,
        self._outcome_json(coverage=0))

  def test_expectation_failure_different(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('api.step("test", ["echo", "bar"])')

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.diff],
        }))

  def test_expectation_pass(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('api.step("test", ["echo", "bar"])')
      recipe.expectation['basic'] = [
        {'cmd': ['echo', 'bar'], 'name': 'test'},
        {'name': '$result'},
      ]

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json())

  def test_recipe_not_covered(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('''
        bool_var = False
        if bool_var:
          a = 1
      ''')

    result = self._run_test('run', should_fail=True)
    self.assertDictEqual(
        result.data,
        self._outcome_json(coverage=88.9))

  def test_recipe_not_covered_filter(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('''
        if False:
          pass
      ''')

    self.assertDictEqual(
        self._run_test('run', '--filter', 'foo.*').data,
        self._outcome_json(coverage=0))

  def test_check_failure(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test('basic')
          + api.post_process(post_process.MustRun, 'bar')
        )
      ''')

    result = self._run_test('run', should_fail=True)
    self.assertIn('CHECK(FAIL)', result.text_output)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.check],
        }))

  @mock.patch('recipe_engine.internal.commands.test.'
              'fail_tracker.FailTracker.recent_fails')
  def test_check_failure_test_no_longer_exists(self, recent_fails_mock):
    recent_fails_mock.return_value = [
        'foo.nonexistent'
    ]
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield api.test('first')
        yield api.test('second')
        yield api.test('third')
      ''')

    result = self._run_test('train', should_fail=False)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.first': [self.OutcomeType.written],
          'foo.second': [self.OutcomeType.written],
          'foo.third': [self.OutcomeType.written],
        })
    )

  def test_check_failure_stop(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('baz')
      recipe.GenTests.write('''
        yield api.test('first') + api.post_process(lambda _c, _s: {})
        yield api.test('second')
        yield api.test('third')
      ''')

    result = self._run_test('train', '--stop', should_fail=True)
    self.assertEqual(
        1,
        str(result.text_output).count(
            'FAIL (recipe crashed in an unexpected way)'))


  def test_check_failure_filter(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test('basic')
          + api.post_process(post_process.MustRun, 'bar')
        )
      ''')

    result = self._run_test(
        'run', '--filter', 'foo.*', should_fail=True)
    self.assertIn('CHECK(FAIL)', result.text_output)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.check],
        }, coverage=0))

  def test_check_success(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test('basic')
          + api.post_check(lambda check, steps: check('bar' not in steps))
        )
      ''')

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json())

  def test_docs_change(self):
    with self.main.write_recipe('foo'):
      pass
    with open(self.main.path + '/recipes/foo.py', 'r+') as f:
      content = f.read()
      f.seek(0)
      f.write('# docstring\n' + content)

    self._run_test('run', should_fail=True)
    self.main.recipes_py('doc')
    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json())

  def test_docs_skipped_if_no_docs_in_config(self):
    with self.main.write_recipe('foo'):
      pass
    with open(self.main.path + '/recipes/foo.py', 'r+') as f:
      content = f.read()
      f.seek(0)
      f.write('# docstring\n' + content)

    with self.main.edit_recipes_cfg_pb2() as spec:
      spec.no_docs = True
    os.remove(os.path.join(self.main.path, 'README.recipes.md'))

    self._run_test('run', should_fail=False)

    self._run_test('train')
    self.assertFalse(self.main.exists('README.recipes.md'))

  def test_recipe_syntax_error(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('baz')
      recipe.GenTests.write('''
        yield api.test('basic') + api.post_process(lambda _c, _s: {})
      ''')

    result = self._run_test('run', should_fail=True)
    self.assertIn("NameError: name 'baz' is not defined", result.text_output)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.crash, self.OutcomeType.diff,
                        self.OutcomeType.needs_infra_fail],
        }))

  def test_recipe_module_uncovered(self):
    with self.main.write_module('foo') as mod:
      mod.api.write('''
        def foo(self):
          pass
      ''')

    result = self._run_test('run', should_fail=True)
    self.assertDictEqual(
        result.data,
        self._outcome_json(
            per_test={},
            coverage=92.3,
            uncovered_mods=['foo'],
        ))

  def test_recipe_module_syntax_error(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def foo(self):
          baz
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.foo()')
      recipe.GenTests.write('''
        yield api.test('basic') + api.post_process(lambda _c, _s: {})
      ''')
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertIn('NameError: name \'baz\' is not defined', result.text_output)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo_module:examples/full.basic': [self.OutcomeType.crash,
                                             self.OutcomeType.needs_infra_fail],
        }))

  def test_recipe_module_syntax_error_in_example(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def foo(self):
          pass
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('baz')
      recipe.GenTests.write('''
        yield api.test('basic') + api.post_process(lambda _c, _s: {})
      ''')
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertIn('NameError: name \'baz\' is not defined', result.text_output)
    self.assertIn('FATAL: Insufficient total coverage', result.text_output)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo_module:examples/full.basic': [self.OutcomeType.crash,
                                             self.OutcomeType.needs_infra_fail]
        }, coverage=95.0))

  def test_recipe_module_example_not_covered(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def foo(self):
          pass
      ''')
    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('''
        bool_var = False
        if bool_var:
          a = 1
      ''')
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertIn('FATAL: Insufficient total coverage', result.text_output)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo_module:examples/full.basic':
              [self.OutcomeType.diff],
        }, coverage=90.9))

  def test_recipe_module_uncovered_not_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.api.write('''
        def foo(self):
          pass
      ''')

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(coverage=92.3, per_test={}))

  def test_recipe_module_covered_by_recipe_not_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.api.write('''
        def bar(self):
          pass
      ''')

    with self.main.write_recipe('my_recipe') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.bar()')

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json(per_test={
          'my_recipe.basic': []
        }))

  def test_recipe_module_covered_by_recipe(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def bar(self):
          pass
      ''')

    with self.main.write_recipe('my_recipe') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.bar()')

    result = self._run_test('run', should_fail=True)
    self.assertDictEqual(
        result.data,
        self._outcome_json(
            per_test={
              'my_recipe.basic': [],
            },
            uncovered_mods=['foo_module'],
            coverage=95.0,
        ))

  def test_recipe_module_partially_covered_by_recipe_not_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE= True
      mod.api.write('''
        def foo(self):
          pass

        def bar(self):
          pass
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.bar()')

    with self.main.write_recipe('foo_recipe') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.foo()')

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json(per_test={
          'foo_module:examples/full.basic': [],
          'foo_recipe.basic': [],
        }))

  def test_recipe_module_partially_covered_by_recipe(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def foo(self):
          pass

        def bar(self):
          pass
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.bar()')

    with self.main.write_recipe('foo_recipe') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.foo()')

    result = self._run_test('run', should_fail=True)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo_module:examples/full.basic': [],
          'foo_recipe.basic': [],
        }, coverage=96.6))

  def test_recipe_module_test_expectation_failure_empty(self):
    with self.main.write_module('foo_module'):
      pass

    with self.main.write_recipe('foo_module', 'tests/foo') as recipe:
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo_module:tests/foo.basic': [self.OutcomeType.diff],
        }))

  def test_module_tests_unused_expectation_file_test(self):
    with self.main.write_module('foo_module'):
      pass

    with self.main.write_recipe('foo_module', 'tests/foo') as recipe:
      recipe.expectation['unused'] = [{'name': '$result'}]

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            per_test={'foo_module:tests/foo.basic': {}},
            unused_expects=[
              'recipe_modules/foo_module/tests/foo.expected/unused.json'
            ]))

  def test_slash_in_name(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('yield api.test("bar/baz")')
      del recipe.expectation['basic']
      recipe.expectation['bar/baz'] = [{'name': '$result'}]

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json(per_test={
          'foo.bar/baz': [],
        }))

  def test_api_uncovered(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.test_api.write('''
        def baz(self):
          pass
      ''')

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            coverage=92.3,
            per_test={},
        ))

  def test_api_uncovered_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.test_api.write('''
        def baz(self):
          pass
      ''')
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            uncovered_mods=['foo_module'],
            coverage=92.3,
            per_test={},
        ))

  def test_api_covered_by_recipe(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.test_api.write('''
        def baz(self):
          pass
      ''')

    with self.main.write_recipe('foo') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.GenTests.write('''
        api.foo_module.baz()
        yield api.test('basic')
      ''')

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json())

  def test_api_uncovered_by_recipe_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.test_api.write('''
        def baz(self):
          pass
      ''')

    with self.main.write_recipe('foo') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.GenTests.write('''
        api.foo_module.baz()
        yield api.test("basic")
      ''')

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            uncovered_mods=['foo_module'],
            coverage=95.2,
        ))

  def test_api_covered_by_example(self):
    with self.main.write_module('foo_module') as mod:
      mod.test_api.write('''
        def baz(self):
          pass
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.GenTests.write('''
        api.foo_module.baz()
        yield api.test("basic")
      ''')

    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json(per_test={
          'foo_module:examples/full.basic': [],
        }))

  def test_duplicate(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield api.test("basic")
        yield api.test("basic")
      ''')

    self.assertIn(
        "Emitted test with duplicate name 'basic'",
        self._run_test('run', should_fail='crash').text_output)

  def test_duplicate_filename(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield api.test("bas_ic")
        yield api.test("bas/ic")
      ''')

    self.assertIn(
        "Emitted test 'bas/ic' which maps to the same JSON file as 'bas_ic'",
        self._run_test('run', should_fail='crash').text_output)

  def test_unused_expectation_file(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')
    self.assertTrue(self.main.is_file(expectation_file))
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            unused_expects=['recipes/foo.expected/unused.json']))

  def test_unused_expectation_file_from_deleted_recipe(self):
    expectation_file = 'recipes/deleted.expected/stale.json'
    with self.main.write_file(expectation_file):
      pass
    self.assertTrue(self.main.is_file(expectation_file))
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            per_test={}, coverage=0, unused_expects=[expectation_file]))

  def test_ignores_expectation_files_in_invalid_directories(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('yield api.test("basic")')
    # Some recipe repos use expectation files to test their resource scripts,
    # and we shouldn't consider those to be recipe expectation files.
    expectation_file = 'recipe_modules/foo/resources/bar/baz.expected/quux.json'
    with self.main.write_file(expectation_file):
      pass
    self.assertTrue(self.main.is_file(expectation_file))
    self.assertDictEqual(self._run_test('run').data, self._outcome_json())

  def test_drop_expectation(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(lambda _c, _s: {}))
      ''')
      del recipe.expectation['basic']
      expectation_file = os.path.join(recipe.expect_path, 'basic.json')
    result = self._run_test('run')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(result.data, self._outcome_json())

  def test_drop_expectation_diff(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(lambda _c, _s: {}))
      ''')
      expectation_file = os.path.join(recipe.expect_path, 'basic.json')
    result = self._run_test('run', should_fail=True)
    self.assertTrue(self.main.is_file(expectation_file))
    self.assertDictEqual(
        result.data,
        self._outcome_json(
            per_test={'foo.basic': [self.OutcomeType.diff]},
        ))

  def test_unused_expectation_preserves_owners(self):
    with self.main.write_recipe('foo') as recipe:
      owners_file = os.path.join(recipe.expect_path, 'OWNERS')
    with self.main.write_file(owners_file):
      pass
    self.assertTrue(self.main.is_file(owners_file))
    self.assertDictEqual(self._run_test('run').data, self._outcome_json())

  def test_config_covered_by_recipe(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.config.write('''
        def BaseConfig(**_kwargs):
          return ConfigGroup(bar=Single(str))
        config_ctx = config_item_context(BaseConfig)
        @config_ctx()
        def bar_config(c):
          c.bar = "gazonk"
      ''')
    with self.main.write_recipe('foo') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.set_config("bar_config")')
    self.assertDictEqual(self._run_test('run').data, self._outcome_json())

  def test_config_covered_by_recipe_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.config.write('''
        def BaseConfig(**_kwargs):
          return ConfigGroup(bar=Single(str))
        config_ctx = config_item_context(BaseConfig)
        @config_ctx()
        def bar_config(c):
          c.bar = "gazonk"
      ''')
    with self.main.write_recipe('foo') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.set_config("bar_config")')
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            coverage=92.6,
            uncovered_mods=['foo_module'],
        ))

  def test_config_covered_by_example(self):
    with self.main.write_module('foo_module') as mod:
      mod.config.write('''
        def BaseConfig(**_kwargs):
          return ConfigGroup(bar=Single(str))
        config_ctx = config_item_context(BaseConfig)
        @config_ctx()
        def bar_config(c):
          c.bar = "gazonk"
      ''')
    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.set_config("bar_config")')
    self.assertDictEqual(
        self._run_test('run').data,
        self._outcome_json(per_test={
          'foo_module:examples/full.basic': [],
        }))


class TestTrain(Common):
  def test_module_tests_unused_expectation_file_train(self):
    with self.main.write_module('foo_module'):
      pass

    with self.main.write_recipe('foo_module', 'examples/foo') as recipe:
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')

    result = self._run_test('train')
    self.assertFalse(os.path.exists(expectation_file))
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo_module:examples/foo.basic': [],
        }))

  def test_module_tests_unused_expectation_file_deleted_even_on_failure(self):
    with self.main.write_module('foo_module'):
      pass

    with self.main.write_recipe('foo_module', 'tests/foo') as recipe:
      recipe.RunSteps.write('raise ValueError("boom")')
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')

    result = self._run_test('train', should_fail=True)
    self.assertFalse(self.main.is_file(expectation_file))
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo_module:tests/foo.basic': [
            self.OutcomeType.written,
            self.OutcomeType.crash,
            self.OutcomeType.needs_infra_fail
          ],
        }))

  def test_basic(self):
    with self.main.write_recipe('foo'):
      pass
    self.assertDictEqual(self._run_test('train').data, self._outcome_json())

  def test_missing(self):
    with self.main.write_recipe('foo') as recipe:
      del recipe.expectation['basic']
      expect_dir = recipe.expect_path

    self.assertFalse(self.main.exists(expect_dir))
    self.assertDictEqual(
        self._run_test('train').data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.written],
        }))
    expect_path = os.path.join(expect_dir, 'basic.json')
    self.assertTrue(self.main.is_file(expect_path))
    self.assertListEqual(
        json.loads(self.main.read_file(expect_path)),
        [{'name': '$result'}])

  def test_diff(self):
    # 1. Initial state: recipe expectations are passing.
    with self.main.write_recipe('foo') as recipe:
      expect_path = os.path.join(recipe.expect_path, 'basic.json')
    self.assertDictEqual(self._run_test('run').data, self._outcome_json())

    # 2. Change the recipe and verify tests would fail.
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('api.step("test", ["echo", "bar"])')

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.diff],
        }))

    # 3. Make sure training the recipe succeeds and produces correct results.
    result = self._run_test('train')
    self.assertListEqual(
        json.loads(self.main.read_file(expect_path)), [{
            'cmd': ['echo', 'bar'],
            'name': 'test'
        }, {
            'name': '$result'
        }])
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.written],
        }))

  def test_invalid_json(self):
    # 1. Initial state: recipe expectations are passing.
    with self.main.write_recipe('foo') as recipe:
      expect_path = os.path.join(recipe.expect_path, 'basic.json')
    self.assertDictEqual(self._run_test('run').data, self._outcome_json())

    # 2. Change the expectation and verify tests would fail.
    with self.main.write_file(expect_path) as fil:
      fil.write('''
        not valid JSON
        <<<<<
        merge conflict
        >>>>>
      ''')
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.diff],
        }))

    # 3. Make sure training the recipe succeeds and produces correct results.
    result = self._run_test('train')
    self.assertListEqual(
        json.loads(self.main.read_file(expect_path)), [{
            'name': '$result'
        }])
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.written],
        }))

  def test_checks_coverage_without_any_label(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('''
        bool_var = False
        if bool_var:
          a = 1
      ''')
    result = self._run_test('train', should_fail=True)
    self.assertIn('Ran 1 tests in', result.text_output)
    self.assertDictEqual(result.data, self._outcome_json(coverage=88.9))

  def test_runs_checks(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(post_process.MustRun, "bar"))
      ''')
    result = self._run_test('train', should_fail=True)
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.check],
        }))

  def test_unused_expectation_file(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')
    result = self._run_test('train')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(result.data, self._outcome_json())

  def test_unused_expectation_file_with_filter(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('yield api.test("basic")')
    with self.main.write_recipe('bar') as recipe:
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')
    self.assertTrue(self.main.is_file(expectation_file))
    result = self._run_test('train', '--filter', 'foo.basic')
    self.assertDictEqual(result.data, self._outcome_json(coverage=0))
    # Even though the expectation file is unused, we should ignore it (don't
    # delete it) if its recipe isn't included in the filter.
    self.assertTrue(self.main.is_file(expectation_file))

  def test_unused_expectation_file_from_deleted_recipe(self):
    expectation_file = 'recipes/deleted.expected/stale.json'
    with self.main.write_file(expectation_file):
      pass
    self.assertTrue(self.main.is_file(expectation_file))
    result = self._run_test('train')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(result.data,
                         self._outcome_json(per_test={}, coverage=0))

  def test_drop_expectation(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(lambda _c, _s: {}))
      ''')
      expectation_file = os.path.join(recipe.expect_path, 'basic.json')
    self.assertTrue(self.main.is_file(expectation_file))
    result = self._run_test('train')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(
        result.data,
        self._outcome_json(per_test={
          'foo.basic': [self.OutcomeType.removed],
        }))

  def test_unused_expectation_preserves_owners(self):
    with self.main.write_recipe('foo') as recipe:
      owners_file = os.path.join(recipe.expect_path, 'OWNERS')
    with self.main.write_file(owners_file):
      pass
    result = self._run_test('train')
    self.assertTrue(self.main.is_file(owners_file))
    self.assertDictEqual(result.data, self._outcome_json())

  def test_config_uncovered(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.config.write('''
        def BaseConfig(**_kwargs):
          return ConfigGroup(bar=Single(str))
        config_ctx = config_item_context(BaseConfig)
      ''')
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(coverage=94.1, per_test={}))

  def test_config_uncovered_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.config.write('''
        def BaseConfig(**_kwargs):
          return ConfigGroup(bar=Single(str))
        config_ctx = config_item_context(BaseConfig)
      ''')
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._outcome_json(
            coverage=94.1,
            per_test={},
            uncovered_mods=['foo_module'],
        ))


class TestFilter(test_env.RecipeEngineUnitTest):
  def test_empty_filter(self):
    filt = test_name.Filter()
    self.assertFalse(filt)

    self.assertTrue(filt.recipe_name('something'))
    self.assertTrue(filt.recipe_name('module:tests/other'))

    self.assertTrue(filt.full_name('something.test_case'))
    self.assertTrue(filt.recipe_name('module:tests/other.test_case'))

  def test_recipe_only_filter(self):
    filt = test_name.Filter()
    filt.append('something')
    filt.append('completely_different')

    self.assertTrue(filt.recipe_name('something'))
    self.assertTrue(filt.recipe_name('completely_different'))
    self.assertFalse(filt.recipe_name('module:tests/other'))

    self.assertTrue(filt.full_name('something.test_case'))
    self.assertFalse(filt.recipe_name('module:tests/other.test_case'))

    self.assertTrue(filt.recipe_name('something_else'))

  def test_full_name_filter(self):
    filt = test_name.Filter()
    filt.append('something.*specific')

    self.assertTrue(filt.recipe_name('something'))
    self.assertFalse(filt.recipe_name('completely_different'))
    self.assertFalse(filt.recipe_name('module:tests/other'))

    self.assertTrue(filt.full_name('something.oddly_specific'))
    self.assertTrue(filt.full_name('something.mildly_specific'))
    self.assertFalse(filt.full_name('something.test_case'))
    self.assertFalse(filt.recipe_name('module:tests/other.test_case'))


if __name__ == '__main__':
  test_env.main()
