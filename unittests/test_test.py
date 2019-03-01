#!/usr/bin/env vpython
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import argparse
import json
import os
import subprocess

from cStringIO import StringIO

from google.protobuf import json_format as jsonpb

# pylint: disable=import-error
import attr
import mock

import test_env

from recipe_engine.internal.commands import test as test_parser
from PB.recipe_engine.test_result import TestResult

CheckFailure = TestResult.CheckFailure


class Common(test_env.RecipeEngineUnitTest):
  @attr.s(frozen=True)
  class JsonResult(object):
    text_output = attr.ib()
    data = attr.ib()

  def _run_test(self, *args, **kwargs):
    should_fail = kwargs.pop('should_fail', False)
    self.assertDictEqual(
        kwargs, {}, 'got additional unexpectd kwargs: {!r}'.format(kwargs))

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
        data = json.load(json_file)
      except Exception as ex:
        if should_fail != 'crash':
          raise Exception(
              'failed to decode test json: {!r}\noutput:\n{}'.format(
                  ex, output))
        data = None
      return self.JsonResult(output, data)

  def _result_json(self, coverage=None, diff=(), crash=(), internal=(),
                        check=None, unused_expect=(), uncovered_mods=()):
    """Generates a JSON dict representing a test_result_pb2.TestResult message.

    Args:
      * coverage (Dict[relative path, List[uncovered line nums]])
      * diff (Seq[test name]) - Tests which had diff failures.
      * crash (Seq[test name]) - Tests which had crashes.
      * internal (Seq[test name]) - Tests which had internal failures.
      * check (Dict[test name, Seq[CheckFailure]]) - Mapping of tests which had
        check failures to details about those check failures. Use the
        test_result_pb2.TestResult.CheckFailure message as the value.
      * unused_expect (Seq[relative path]) - The list of relative paths to
        expectation files which were unused.
      * uncovered_mods (Seq[foo_module]) - The list of module names which aren't
        covered by tests.

    Returns a python dict which is the JSONPB representation of the TestResult.
    """
    # TODO(iannucci): this result proto is unnecessarially convoluted.
    ret = TestResult(version=1, valid=True)

    for path, uncovered_lines in (coverage or {}).iteritems():
      path = os.path.join(self.main.path, path)
      ret.coverage_failures[path].uncovered_lines.extend(uncovered_lines)

    for test_name in diff:
      ret.test_failures[test_name].failures.add().diff_failure.SetInParent()

    for test_name in crash:
      ret.test_failures[test_name].failures.add().crash_failure.SetInParent()

    for test_name in internal:
      ret.test_failures[test_name].failures.add().internal_failure.SetInParent()

    for test_name, failures in (check or {}).iteritems():
      for failure in failures:
        check_fail = ret.test_failures[test_name].failures.add().check_failure
        check_fail.CopyFrom(failure)
        check_fail.filename = os.path.join(
            self.main.path, check_fail.filename)

    for relpath in unused_expect:
      ret.unused_expectations.append(
          os.path.join(self.main.path, relpath))

    ret.uncovered_modules.extend(uncovered_mods)

    return jsonpb.MessageToDict(ret, preserving_proto_field_name=True)

  def setUp(self):
    super(Common, self).setUp()
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

    self.assertDictEqual(self._run_test('run').data, self._result_json())

  def test_expectation_failure_empty(self):
    with self.main.write_recipe('foo') as recipe:
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertNotIn('FATAL: Insufficient coverage', result.text_output)
    self.assertNotIn('CHECK(FAIL)', result.text_output)
    self.assertIn('foo.basic failed', result.text_output)
    self.assertDictEqual(result.data, self._result_json(diff=['foo.basic']))

  def test_expectation_failure_empty_filter(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield api.test('basic')
        yield api.test('second')
      ''')

    self.assertDictEqual(
        self._run_test(
            'run', '--filter', 'foo.second', should_fail=True).data,
        self._result_json(diff=['foo.second']))

    self.assertDictEqual(
        self._run_test('run', '--filter', 'foo.basic').data,
        self._result_json())

  def test_expectation_failure_different(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('api.step("test", ["echo", "bar"])')

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._result_json(diff=['foo.basic']))

  def test_expectation_pass(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('api.step("test", ["echo", "bar"])')
      recipe.expectation['basic'] = [
        {'cmd': ['echo', 'bar'], 'name': 'test'},
        {'name': '$result', 'jsonResult': None},
      ]

    self.assertDictEqual(self._run_test('run').data, self._result_json())

  def test_recipe_not_covered(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('''
        if False:
          pass
      ''')

    result = self._run_test('run', should_fail=True)
    self.assertIn('FATAL: Insufficient coverage', result.text_output)
    self.assertNotIn('CHECK(FAIL)', result.text_output)
    self.assertNotIn('foo.basic failed', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(coverage={'recipes/foo.py': [10]}))

  def test_recipe_not_covered_filter(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('''
        if False:
          pass
      ''')

    self.assertDictEqual(
        self._run_test('run', '--filter', 'foo.*').data,
        self._result_json())

  def test_check_failure(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test('basic')
          + api.post_process(post_process.MustRun, 'bar')
        )
      ''')

    result = self._run_test('run', should_fail=True)
    self.assertNotIn('FATAL: Insufficient coverage', result.text_output)
    self.assertIn('CHECK(FAIL)', result.text_output)
    self.assertIn('foo.basic failed', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(check={
          'foo.basic': [CheckFailure(
              func='MustRun',
              args=["'bar'"],
              filename='recipes/foo.py',
              lineno=13,
          )]
        }))

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
    self.assertNotIn('FATAL: Insufficient coverage', result.text_output)
    self.assertIn('CHECK(FAIL)', result.text_output)
    self.assertIn('foo.basic failed', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(check={
          'foo.basic': [CheckFailure(
              func='MustRun',
              args=["'bar'"],
              filename='recipes/foo.py',
              lineno=13,
          )]
        }))

  def test_check_success(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test('basic')
          + api.post_process(post_process.DoesNotRun, 'bar')
        )
      ''')

    self.assertDictEqual(self._run_test('run').data, self._result_json())

  def test_recipe_syntax_error(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('baz')

    result = self._run_test('run', should_fail=True)
    self.assertIn(
        ('line 9, in RunSteps\n    baz\n'
         'NameError: global name \'baz\' is not defined'),
        result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(
            crash=['foo.basic'],
            coverage={'recipes/foo.py': [9]},
            unused_expect=[
              'recipes/foo.expected',
              'recipes/foo.expected/basic.json',
            ]
        ))

  def test_recipe_module_uncovered(self):
    with self.main.write_module('foo'):
      pass

    result = self._run_test('run', should_fail=True)
    self.assertIn(
        'The following modules lack test coverage: foo',
        result.text_output)
    self.assertDictEqual(result.data, self._result_json(uncovered_mods=['foo']))

  def test_recipe_module_syntax_error(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def foo(self):
          baz
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('api.foo_module.foo()')
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertIn('NameError: global name \'baz\' is not defined',
                  result.text_output)
    self.assertIn('FATAL: Insufficient coverage', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(
            crash=['foo_module:examples/full.basic'],
            coverage={
              'recipe_modules/foo_module/api.py': [8],
              'recipe_modules/foo_module/examples/full.py': [9],
            },
        ))

  def test_recipe_module_syntax_error_in_example(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def foo(self):
          pass
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('baz')
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertIn('NameError: global name \'baz\' is not defined',
                  result.text_output)
    self.assertIn('FATAL: Insufficient coverage', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(
            crash=['foo_module:examples/full.basic'],
            coverage={
              'recipe_modules/foo_module/api.py': [8],
              'recipe_modules/foo_module/examples/full.py': [9],
            }
        ))

  def test_recipe_module_example_not_covered(self):
    with self.main.write_module('foo_module') as mod:
      mod.api.write('''
        def foo(self):
          pass
      ''')

    with self.main.write_recipe('foo_module', 'examples/full') as recipe:
      recipe.DEPS = ['foo_module']
      recipe.RunSteps.write('''
        if False:
          pass
      ''')
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertIn('FATAL: Insufficient coverage', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(
            coverage={
              'recipe_modules/foo_module/api.py': [8],
              'recipe_modules/foo_module/examples/full.py': [10],
            },
            diff=['foo_module:examples/full.basic']
        ))

  def test_recipe_module_uncovered_not_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True

    self.assertDictEqual(self._run_test('run').data, self._result_json())

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

    self.assertDictEqual(self._run_test('run').data, self._result_json())

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
    self.assertIn('The following modules lack test coverage: foo_module',
                  result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(
            coverage={'recipe_modules/foo_module/api.py': [8]},
            uncovered_mods=['foo_module'],
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

    self.assertDictEqual(self._run_test('run').data, self._result_json())

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
    self.assertIn('FATAL: Insufficient coverage', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(
            coverage={'recipe_modules/foo_module/api.py': [8]},
        ))

  def test_recipe_module_test_expectation_failure_empty(self):
    with self.main.write_module('foo_module'):
      pass

    with self.main.write_recipe('foo_module', 'tests/foo') as recipe:
      del recipe.expectation['basic']

    result = self._run_test('run', should_fail=True)
    self.assertDictEqual(
        result.data,
        self._result_json(diff=['foo_module:tests/foo.basic']))

  def test_module_tests_unused_expectation_file_test(self):
    with self.main.write_module('foo_module'):
      pass

    with self.main.write_recipe('foo_module', 'tests/foo') as recipe:
      recipe.expectation['unused'] = [{'name': '$result', 'jsonResult': None}]

    result = self._run_test('run', should_fail=True)
    self.assertIn('FATAL: unused expectations found:', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(unused_expect=[
          'recipe_modules/foo_module/tests/foo.expected/unused.json'
        ]))

  def test_slash_in_name(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('yield api.test("bar/baz")')
      del recipe.expectation['basic']
      recipe.expectation['bar/baz'] = [{'name': '$result', 'jsonResult': None}]

    self.assertDictEqual(self._run_test('run').data, self._result_json())

  def test_api_uncovered(self):
    with self.main.write_module('foo_module') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.test_api.write('''
        def baz(self):
          pass
      ''')

    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._result_json(
            coverage={'recipe_modules/foo_module/test_api.py': [8]},
        ))

  def test_api_uncovered_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.test_api.write('''
        def baz(self):
          pass
      ''')
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._result_json(
            coverage={'recipe_modules/foo_module/test_api.py': [8]},
            uncovered_mods=['foo_module']
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

    self.assertDictEqual(self._run_test('run').data, self._result_json())

  def test_api_covered_by_recipe_strict(self):
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
        self._result_json(
            coverage={'recipe_modules/foo_module/test_api.py': [8]},
            uncovered_mods=['foo_module'],
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

    self.assertDictEqual(self._run_test('run').data, self._result_json())

  def test_duplicate(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.GenTests.write('''
        yield api.test("basic")
        yield api.test("basic")
      ''')

    self.assertIn(
        'Exception: While generating results for \'foo\': '
            'ValueError: Duplicate test found: basic',
        self._run_test('run', should_fail='crash').text_output)

  def test_unused_expectation_file(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')
    result = self._run_test('run', should_fail=True)
    self.assertIn('FATAL: unused expectations found', result.text_output)
    self.assertTrue(self.main.is_file(expectation_file))
    self.assertDictEqual(
        result.data,
        self._result_json(
            unused_expect=['recipes/foo.expected/unused.json']))

  def test_unused_expectation_dir(self):
    with self.main.write_recipe('foo') as recipe:
      extra_file = os.path.join(recipe.expect_path, 'dir', 'wat')
      with self.main.write_file(extra_file):
        pass
    result = self._run_test('run')
    self.assertTrue(self.main.is_file(extra_file))
    self.assertDictEqual(result.data, self._result_json())

  def test_drop_expectation(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(post_process.DropExpectation))
      ''')
      del recipe.expectation['basic']
      expectation_file = os.path.join(recipe.expect_path, 'basic.json')
    result = self._run_test('run')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(result.data, self._result_json())

  def test_drop_expectation_unused(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(post_process.DropExpectation))
      ''')
      expectation_file = os.path.join(recipe.expect_path, 'basic.json')
    result = self._run_test('run', should_fail=True)
    self.assertIn('FATAL: unused expectations found', result.text_output)
    self.assertTrue(self.main.is_file(expectation_file))
    self.assertDictEqual(
        result.data,
        self._result_json(unused_expect=[
          'recipes/foo.expected',
          'recipes/foo.expected/basic.json',
        ]))

  def test_unused_expectation_preserves_owners(self):
    with self.main.write_recipe('foo') as recipe:
      owners_file = os.path.join(recipe.expect_path, 'OWNERS')
    with self.main.write_file(owners_file):
      pass
    result = self._run_test('run')
    self.assertTrue(self.main.is_file(owners_file))
    self.assertDictEqual(result.data, self._result_json())

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
    self.assertDictEqual(self._run_test('run').data, self._result_json())

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
        self._result_json(
            coverage={'recipe_modules/foo_module/config.py': [6, 10]},
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
    self.assertDictEqual(self._run_test('run').data, self._result_json())


class TestTrain(Common):
  def test_module_tests_unused_expectation_file_train(self):
    with self.main.write_module('foo_module') as mod:
      pass

    with self.main.write_recipe('foo_module', 'examples/foo') as recipe:
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')

    result = self._run_test('train')
    self.assertFalse(os.path.exists(expectation_file))
    self.assertDictEqual(self._result_json(), result.data)

  def test_module_tests_unused_expectation_file_stays_on_failure(self):
    with self.main.write_module('foo_module') as mod:
      pass

    with self.main.write_recipe('foo_module', 'tests/foo') as recipe:
      recipe.RunSteps.write('raise ValueErorr("boom")')
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')

    result = self._run_test('train', should_fail=True)
    self.assertTrue(self.main.is_file(expectation_file))
    self.assertDictEqual(
        self._result_json(
            coverage={'recipe_modules/foo_module/tests/foo.py': [9]},
            crash=['foo_module:tests/foo.basic'],
        ),
        result.data)

  def test_basic(self):
    with self.main.write_recipe('foo'):
      pass
    self.assertDictEqual(self._run_test('train').data, self._result_json())

  def test_missing(self):
    with self.main.write_recipe('foo') as recipe:
      del recipe.expectation['basic']
      expect_dir = recipe.expect_path

    self.assertFalse(self.main.exists(expect_dir))
    self.assertDictEqual(self._run_test('train').data, self._result_json())
    expect_path = os.path.join(expect_dir, 'basic.json')
    self.assertTrue(self.main.is_file(expect_path))
    self.assertListEqual(
        json.loads(self.main.read_file(expect_path)),
        [{'jsonResult': None, 'name': '$result'}])

  def test_diff(self):
    # 1. Initial state: recipe expectations are passing.
    with self.main.write_recipe('foo') as recipe:
      expect_path = os.path.join(recipe.expect_path, 'basic.json')
    self.assertDictEqual(self._run_test('run').data, self._result_json())

    # 2. Change the recipe and verify tests would fail.
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('api.step("test", ["echo", "bar"])')

    result = self._run_test('run', should_fail=True)
    self.assertIn('foo.basic failed', result.text_output)
    self.assertDictEqual(result.data, self._result_json(diff=['foo.basic']))

    # 3. Make sure training the recipe succeeds and produces correct results.
    result = self._run_test('train')
    self.assertListEqual(
        json.loads(self.main.read_file(expect_path)),
        [{u'cmd': [u'echo', u'bar'], u'name': u'test'},
         {u'jsonResult': None, u'name': u'$result'}])
    self.assertDictEqual(result.data, self._result_json())

  def test_invalid_json(self):
    # 1. Initial state: recipe expectations are passing.
    with self.main.write_recipe('foo') as recipe:
      expect_path = os.path.join(recipe.expect_path, 'basic.json')
    self.assertDictEqual(self._run_test('run').data, self._result_json())

    # 2. Change the expectation and verify tests would fail.
    with self.main.write_file(expect_path) as fil:
      fil.write('''
        not valid JSON
        <<<<<
        merge conflict
        >>>>>
      ''')
    result = self._run_test('run', should_fail=True)
    self.assertIn('foo.basic failed', result.text_output)
    self.assertDictEqual(result.data, self._result_json(diff=['foo.basic']))

    # 3. Make sure training the recipe succeeds and produces correct results.
    result = self._run_test('train')
    self.assertListEqual(
        json.loads(self.main.read_file(expect_path)),
        [{u'jsonResult': None, u'name': u'$result'}])
    self.assertDictEqual(result.data, self._result_json())

  def test_checks_coverage(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.RunSteps.write('''
        if False:
          pass
      ''')
    result = self._run_test('train', should_fail=True)
    self.assertIn('FATAL: Insufficient coverage', result.text_output)
    self.assertNotIn('CHECK(FAIL)', result.text_output)
    self.assertNotIn('foo.basic failed', result.text_output)
    self.assertDictEqual(
        result.data, self._result_json(coverage={'recipes/foo.py': [10]}))

  def test_runs_checks(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(post_process.MustRun, "bar"))
      ''')
    result = self._run_test('train', should_fail=True)
    self.assertNotIn('FATAL: Insufficient coverage', result.text_output)
    self.assertIn('CHECK(FAIL)', result.text_output)
    self.assertIn('foo.basic failed', result.text_output)
    self.assertDictEqual(
        result.data,
        self._result_json(check={
          'foo.basic': [CheckFailure(
              filename='recipes/foo.py', lineno=13, func='MustRun',
              args=["'bar'"])]
        }))

  def test_unused_expectation_file(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.expectation['unused'] = []
      expectation_file = os.path.join(recipe.expect_path, 'unused.json')
    result = self._run_test('train')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(result.data, self._result_json())

  def test_unused_expectation_dir(self):
    with self.main.write_recipe('foo') as recipe:
      extra_file = os.path.join(recipe.expect_path, 'dir', 'wat')
      with self.main.write_file(extra_file):
        pass
    result = self._run_test('train')
    self.assertTrue(self.main.is_file(extra_file))
    self.assertDictEqual(result.data, self._result_json())

  def test_drop_expectation(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(post_process.DropExpectation))
      ''')
      expectation_file = os.path.join(recipe.expect_path, 'basic.json')
    self.assertTrue(self.main.is_file(expectation_file))
    result = self._run_test('train')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(result.data, self._result_json())

  def test_drop_expectation_unused(self):
    with self.main.write_recipe('foo') as recipe:
      recipe.imports = ['from recipe_engine import post_process']
      recipe.GenTests.write('''
        yield (api.test("basic") +
          api.post_process(post_process.DropExpectation))
      ''')
      expectation_file = os.path.join(recipe.expect_path, 'basic.json')
    result = self._run_test('train')
    self.assertFalse(self.main.exists(expectation_file))
    self.assertDictEqual(result.data, self._result_json())

  def test_unused_expectation_preserves_owners(self):
    with self.main.write_recipe('foo') as recipe:
      owners_file = os.path.join(recipe.expect_path, 'OWNERS')
    with self.main.write_file(owners_file):
      pass
    result = self._run_test('train')
    self.assertTrue(self.main.is_file(owners_file))
    self.assertDictEqual(result.data, self._result_json())

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
        self._result_json(
            coverage={'recipe_modules/foo_module/config.py': [6]},
        ))

  def test_config_uncovered_strict(self):
    with self.main.write_module('foo_module') as mod:
      mod.config.write('''
        def BaseConfig(**_kwargs):
          return ConfigGroup(bar=Single(str))
        config_ctx = config_item_context(BaseConfig)
      ''')
    self.assertDictEqual(
        self._run_test('run', should_fail=True).data,
        self._result_json(
            coverage={'recipe_modules/foo_module/config.py': [6]},
            uncovered_mods=['foo_module'],
        ))


class TestDiff(Common):
  def test_basic(self):
    with self.main.write_file('base.json') as buf:
      json.dump(self._result_json(), buf)

    with self.main.write_file('new.json') as buf:
      json.dump(self._result_json(), buf)

    result = self._run_test(
        'diff',
        '--baseline', os.path.join(self.main.path, 'base.json'),
        '--actual', os.path.join(self.main.path, 'new.json'),
    )
    self.assertDictEqual(result.data, self._result_json())

  def test_invalid_baseline(self):
    invalid = self._result_json()
    del invalid['valid']

    with self.main.write_file('base.json') as buf:
      json.dump(invalid, buf)

    with self.main.write_file('new.json') as buf:
      json.dump(self._result_json(), buf)

    result = self._run_test(
        'diff',
        '--baseline', os.path.join(self.main.path, 'base.json'),
        '--actual', os.path.join(self.main.path, 'new.json'),
        should_fail=True
    )
    self.assertDictEqual(result.data, invalid)

  def test_invalid_actual(self):
    invalid = self._result_json()
    del invalid['valid']

    with self.main.write_file('base.json') as buf:
      json.dump(invalid, buf)

    with self.main.write_file('new.json') as buf:
      json.dump(self._result_json(), buf)

    result = self._run_test(
        'diff',
        '--baseline', os.path.join(self.main.path, 'base.json'),
        '--actual', os.path.join(self.main.path, 'new.json'),
        should_fail=True
    )
    self.assertDictEqual(result.data, invalid)

  def test_just_diff(self):
    with self.main.write_file('base.json') as buf:
      json.dump(self._result_json(diff=['foo']), buf)

    with self.main.write_file('new.json') as buf:
      json.dump(self._result_json(diff=['foo', 'bar']), buf)

    result = self._run_test(
        'diff',
        '--baseline', os.path.join(self.main.path, 'base.json'),
        '--actual', os.path.join(self.main.path, 'new.json'),
        should_fail=True
    )
    self.assertDictEqual(result.data, self._result_json(diff=['bar']))

  def test_full(self):
    with self.main.write_file('base.json') as buf:
      json.dump(self._result_json(
          check={
            'foo': [
              CheckFailure(filename='foo_file', lineno=1, func='foo_func')],
          },
          coverage={'foo': [1, 2, 3], 'bar': [1]},
          diff=['foo'], crash=['foo'], internal=['foo'], uncovered_mods=['foo'],
          unused_expect=['foo_expect'],
      ), buf)

    with self.main.write_file('new.json') as buf:
      json.dump(self._result_json(
          check={
            'foo': [
              CheckFailure(filename='foo_file', lineno=1, func='foo_func')],
            'bar': [
              CheckFailure(filename='bar_file', lineno=2, func='bar_func',
                           args=['"arg"'])],
          },
          coverage={'foo': [1, 2, 3], 'bar': [1, 2]},
          diff=['foo', 'bar'], crash=['foo', 'bar'], internal=['foo', 'bar'],
          uncovered_mods=['foo', 'bar'],
          unused_expect=['foo_expect', 'bar_expect'],
      ), buf)

    result = self._run_test(
        'diff',
        '--baseline', os.path.join(self.main.path, 'base.json'),
        '--actual', os.path.join(self.main.path, 'new.json'),
        should_fail=True
    )
    self.assertDictEqual(
        self._result_json(
            check={'bar': [
              CheckFailure(filename='bar_file', lineno=2, func='bar_func',
                           args=['"arg"'])],
            },
            coverage={'bar': [2]},
            diff=['bar'], crash=['bar'], internal=['bar'],
            uncovered_mods=['bar'], unused_expect=['bar_expect']),
        result.data)


class TestArgs(test_env.RecipeEngineUnitTest):
  @mock.patch('argparse._sys.stderr', new_callable=StringIO)
  def test_normalize_filter(self, stderr):
    parser = argparse.ArgumentParser()
    subp = parser.add_subparsers()
    test_parser.add_arguments(subp.add_parser('test'))

    with self.assertRaises(SystemExit):
      args = parser.parse_args([
        'test', 'run', '--filter', ''])
    self.assertIn('empty filters not allowed', stderr.getvalue())

    stderr.reset()
    args = parser.parse_args(['test', 'run', '--filter', 'foo'])
    self.assertEqual(args.filter, ['foo*.*'])

    stderr.reset()
    args = parser.parse_args(['test', 'run', '--filter', 'foo.bar'])
    self.assertEqual(args.filter, ['foo.bar'])


if __name__ == '__main__':
  test_env.main()
