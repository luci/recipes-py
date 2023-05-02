#!/usr/bin/env vpython3
# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib
import inspect
import os
import re
import textwrap

from unittest import mock

import test_env

from recipe_engine.internal.recipe_deps import (
  Recipe,
  RecipeDeps,
  RecipeModule,
  RecipeRepo)
from recipe_engine.internal.warn import escape, record
from recipe_engine.internal.warn.definition import (
  RECIPE_WARNING_DEFINITIONS_REL,
  _populate_monorail_bug_default_fields,
  _validate,
)

import PB.recipe_engine.warning as warning_pb

def create_definition(
  name, description=None, deadline=None, monorail_bug=None):
  """Shorthand to create a warning definition proto message based on the
  given input"""
  return warning_pb.Definition(
    name = name,
    description = description,
    deadline = deadline,
    monorail_bug = [monorail_bug] if monorail_bug else None,
  )

class TestWarningDefinition(test_env.RecipeEngineUnitTest):
  def test_populate_monorail_bug_default_fields(self):
    # No Default fields specified
    definition = create_definition(
      'WARNING_NAME', monorail_bug=warning_pb.MonorailBug(id=123))
    expected_definition = warning_pb.Definition()
    expected_definition.CopyFrom(definition)
    _populate_monorail_bug_default_fields(
      [definition], warning_pb.MonorailBugDefault())
    self.assertEqual(expected_definition, definition)

    # All Default fields specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug=warning_pb.MonorailBug(project= 'two', id=123))
    _populate_monorail_bug_default_fields(
      [definition], warning_pb.MonorailBugDefault(host='a.com', project='one'))
    expected_definition = create_definition(
      'WARNING_NAME',
      # default project should not override the existing one
      monorail_bug=warning_pb.MonorailBug(host='a.com', project='two', id=123))
    self.assertEqual(expected_definition, definition)

    # Partial fields specified
    definition = create_definition(
      'WARNING_NAME', monorail_bug=warning_pb.MonorailBug(id=123))
    _populate_monorail_bug_default_fields(
      [definition], warning_pb.MonorailBugDefault(host='a.com'))
    expected_definition = create_definition(
      'WARNING_NAME',
      monorail_bug=warning_pb.MonorailBug(host='a.com', id=123))
    self.assertEqual(expected_definition, definition)

  def test_valid_definitions(self):
    simple_definition = create_definition('SIMPLE_WARNING_NAME')
    _validate(simple_definition)
    full_definition = create_definition(
      'FULL_WARNING_NAME',
      description = ['this is a description',],
      deadline = '2020-12-31',
      monorail_bug = warning_pb.MonorailBug(
        host='bugs.chromium.org', project= 'chromium', id=123456),
    )
    _validate(full_definition)

  def test_invalid_warning_name(self):
    with self.assertRaises(ValueError):
      _validate(create_definition('ThisIsCamalCase'))

  def test_invalid_monorail_bug(self):
    # No host specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug = warning_pb.MonorailBug(project='chromium', id=123456),
      )
    with self.assertRaises(ValueError):
      _validate(definition)
    # No project specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug = warning_pb.MonorailBug(
        host='bugs.chromium.org', id=123456),
      )
    with self.assertRaises(ValueError):
      _validate(definition)
    # No id specified
    definition = create_definition(
      'WARNING_NAME',
      monorail_bug = warning_pb.MonorailBug(
        host='bugs.chromium.org', project='chromium'),
      )
    with self.assertRaises(ValueError):
      _validate(definition)

  def test_invalid_deadline(self):
    with self.assertRaises(ValueError):
      _validate(create_definition(
        'WARNING_NAME', deadline='12-31-2020'))

    with self.assertRaises(ValueError):
      _validate(create_definition(
        'WARNING_NAME', deadline='2020-12-31T23:59:59'))

class TestWarningRecorder(test_env.RecipeEngineUnitTest):
  repo_name = 'main_repo'
  test_file_path = '/path/to/test.py'

  def setUp(self):
    super(TestWarningRecorder, self).setUp()
    mock_deps = mock.Mock(
      warning_definitions={
        'recipe_engine/SOME_WARNING': warning_pb.Definition()
      },
    )
    mock_deps.__class__ = RecipeDeps
    mock_deps.main_repo.name = self.repo_name
    mock_deps.main_repo.recipes_dir = os.path.dirname(self.test_file_path)
    mock_deps.main_repo.modules_dir = os.path.dirname(self.test_file_path)
    self.recorder = record.WarningRecorder(mock_deps)
    # This test should NOT test the functionality of any predicate
    # implementation
    self._override_skip_frame_predicates(tuple())

  def test_record_execution_warning(self):
    with create_test_frames(self.test_file_path) as test_frames:
      self.recorder.record_execution_warning(
        'recipe_engine/SOME_WARNING', test_frames)

    expected_cause = warning_pb.Cause()
    expected_cause.call_site.site.file = self.test_file_path
    expected_cause.call_site.site.line = 3
    self.assert_has_warning('recipe_engine/SOME_WARNING', expected_cause)

  def test_record_execution_warning_filter(self):
    self.recorder.call_site_filter = lambda name, cause: False
    with create_test_frames(self.test_file_path) as test_frames:
      self.recorder.record_execution_warning(
        'recipe_engine/SOME_WARNING', test_frames)

    self.assertFalse(
      self.recorder.recorded_warnings['recipe_engine/SOME_WARNING'])

  def test_record_execution_warning_include_call_stack(self):
    self.recorder.include_call_stack = True
    with create_test_frames(self.test_file_path) as test_frames:
      self.recorder.record_execution_warning(
        'recipe_engine/SOME_WARNING', test_frames)

    cause = self.recorder.recorded_warnings['recipe_engine/SOME_WARNING'][0]
    self.assertTrue(cause.call_site.call_stack)

  def test_record_execution_warning_skip_frame(self):
    def line_number_less_than_4(_name, frame):
      return 'line number is less then 4' if frame.f_lineno < 4 else None
    self._override_skip_frame_predicates((line_number_less_than_4,))
    with create_test_frames(self.test_file_path) as test_frames:
      self.recorder.record_execution_warning(
        'recipe_engine/SOME_WARNING', test_frames)

    # attribute to frame on line 4
    expected_cause = warning_pb.Cause()
    expected_cause.call_site.site.file = self.test_file_path
    expected_cause.call_site.site.line = 4
    self.assert_has_warning('recipe_engine/SOME_WARNING', expected_cause)

  def test_record_empty_site_for_execution_warning(self):
    self._override_skip_frame_predicates((
      lambda _name, _frame: 'skip all frames', ))
    with create_test_frames(self.test_file_path) as test_frames:
      self.recorder.record_execution_warning(
        'recipe_engine/SOME_WARNING', test_frames)
    self.assertIn('recipe_engine/SOME_WARNING', self.recorder.recorded_warnings)
    cause = self.recorder.recorded_warnings['recipe_engine/SOME_WARNING'][0]
    self.assertEqual(cause.call_site.site.file, '')
    self.assertEqual(cause.call_site.site.line, 0)
    self.assertTrue(cause.call_site.call_stack)

  def test_no_duplicate_execution_warning(self):
    with create_test_frames(self.test_file_path) as test_frames:
      self.recorder.record_execution_warning(
        'recipe_engine/SOME_WARNING', test_frames)
      self.recorder.record_execution_warning(
        'recipe_engine/SOME_WARNING', test_frames)

    self.assertEqual(1, len(
      self.recorder.recorded_warnings['recipe_engine/SOME_WARNING']))

  def test_record_import_warning(self):
    self.recorder.record_import_warning(
      'recipe_engine/SOME_WARNING',
      self._create_mock_recipe('test_module:path/to/recipe', self.repo_name),
    )
    self.recorder.record_import_warning(
      'recipe_engine/SOME_WARNING',
      self._create_mock_recipe_module('test_module', self.repo_name),
    )

    expected_recipe_cause = warning_pb.Cause()
    expected_recipe_cause.import_site.repo = self.repo_name
    expected_recipe_cause.import_site.recipe = 'test_module:path/to/recipe'
    expected_recipe_module_cause = warning_pb.Cause()
    expected_recipe_module_cause.import_site.repo = self.repo_name
    expected_recipe_module_cause.import_site.module = 'test_module'
    self.assert_has_warning(
      'recipe_engine/SOME_WARNING',
      expected_recipe_cause,
      expected_recipe_module_cause,
    )

  def test_record_import_warning_raise_for_invalid_type(self):
    with self.assertRaises(ValueError):
      self.recorder.record_import_warning(
        'recipe_engine/SOME_WARNING', 'I am a str type')

  def test_record_import_warning_filter(self):
    self.recorder.import_site_filter = lambda name, cause: False
    self.recorder.record_import_warning(
      'recipe_engine/SOME_WARNING',
      self._create_mock_recipe('test_module:path/to/recipe', self.repo_name),
    )
    self.recorder.record_import_warning(
      'recipe_engine/SOME_WARNING',
      self._create_mock_recipe_module('test_module', self.repo_name),
    )
    self.assertFalse(
      self.recorder.recorded_warnings['recipe_engine/SOME_WARNING'])

  def test_no_duplicate_import_warning(self):
    mock_recipe = self._create_mock_recipe(
      'test_module:path/to/recipe', self.repo_name)
    self.recorder.record_import_warning(
      'recipe_engine/SOME_WARNING', mock_recipe)
    self.recorder.record_import_warning(
      'recipe_engine/SOME_WARNING', mock_recipe)
    self.assertEqual(1, len(
      self.recorder.recorded_warnings['recipe_engine/SOME_WARNING']))

  def test_record_non_fully_qualified_warning(self):
    # execution warning
    with create_test_frames(self.test_file_path) as test_frames:
      with self.assertRaisesRegex(
          ValueError,
          'expected fully-qualified warning name, got SOME_WARNING'):
        self.recorder.record_execution_warning('SOME_WARNING', test_frames)
    # import warning
    with self.assertRaisesRegex(
        ValueError, 'expected fully-qualified warning name, got SOME_WARNING'):
      self.recorder.record_import_warning(
          'SOME_WARNING',
          self._create_mock_recipe('test_module:path/to/recipe', self.repo_name),
      )

  def test_record_not_defined_execution_warning(self):
    # execution warning
    with create_test_frames(self.test_file_path) as test_frames:
      with self.assertRaisesRegex(
          ValueError,
          'warning "COOL_WARNING" is not defined in recipe repo infra'):
        self.recorder.record_execution_warning('infra/COOL_WARNING',
                                               test_frames)
    # import warning
    with self.assertRaisesRegex(
        ValueError,
        'warning "COOL_WARNING" is not defined in recipe repo infra'):
      self.recorder.record_import_warning(
          'infra/COOL_WARNING',
          self._create_mock_recipe('test_module:path/to/recipe', self.repo_name),
      )

  def assert_has_warning(self, warning_name, *causes):
    recorded_warnings = self.recorder.recorded_warnings
    self.assertIn(warning_name, recorded_warnings)
    for cause in causes:
      self.assertIn(cause, recorded_warnings.get(warning_name))

  def _override_skip_frame_predicates(self, new_predicates):
    key = '_cached_property_' + '_skip_frame_predicates'
    object.__setattr__(self.recorder, key, new_predicates)

  @staticmethod
  def _create_mock_recipe(recipe_name, repo_name):
    mock_repo = mock.Mock()
    mock_repo.name = repo_name
    mock_recipe = mock.Mock()
    mock_recipe.__class__ = Recipe
    mock_recipe.name = recipe_name
    mock_recipe.repo = mock_repo
    return mock_recipe

  @staticmethod
  def _create_mock_recipe_module(module_name, repo_name):
    mock_repo = mock.Mock()
    mock_repo.name = repo_name
    mock_module = mock.Mock()
    mock_module.__class__ = RecipeModule
    mock_module.name = module_name
    mock_module.repo = mock_repo
    return mock_module


@contextlib.contextmanager
def create_test_frames(frame_file):
  """Execute a program and return a list of stack frames for testing
  purpose as follows.
  [
    file: frame_file, line: 3,
    file: frame_file, line: 4,
    file: frame_file, line: 5,
    the frame that is calling this function,
    *all outer frames,
  ]
  """
  program="""
def outer():
  def inner():
    return [frame_tuple[0] for frame_tuple in inspect.stack()]
  return inner()
frames = outer()
  """.strip()
  try:
    ns = {}
    exec(compile(program, frame_file, 'exec'), globals(), ns)
    yield ns['frames']
  finally:
    del ns['frames']


class EscapeWarningPredicateTest(test_env.RecipeEngineUnitTest):
  def test_issue_SOME_WARN(self):
    warning_name = 'SOME_WARN'
    self.assertIsNone(
      self.apply_predicate(warning_name, self.non_escaped_frame()))
    self.assertRegex(
        self.apply_predicate(warning_name, self.escaped_frame()),
        '^escaped function at .+#L[0-9]+$',
    )
    self.assertRegex(
        self.apply_predicate(warning_name, self.escaped_all_frame()),
        '^escaped function at .+#L[0-9]+$',
    )

  def test_issue_ANOTHER_WARN(self):
    warning_name = 'ANOTHER_WARN'
    self.assertIsNone(
      self.apply_predicate(warning_name, self.non_escaped_frame()))
    self.assertIsNone(
      self.apply_predicate(warning_name, self.escaped_frame()))
    self.assertRegex(
        self.apply_predicate(warning_name, self.escaped_all_frame()),
        '^escaped function at .+#L[0-9]+$',
    )

  def non_escaped_frame(self):
    return inspect.currentframe()

  @escape.escape_warnings('^SOME.WARN$')
  def escaped_frame(self):
    return inspect.currentframe()

  @escape.escape_all_warnings
  def escaped_all_frame(self):
    return inspect.currentframe()

  @staticmethod
  def apply_predicate(warning_name, frame):
    return escape.escape_warning_predicate(warning_name, frame)


class WarningIntegrationTests(test_env.RecipeEngineUnitTest):
  def setUp(self):
    super(WarningIntegrationTests, self).setUp()
    self.deps = self.FakeRecipeDeps()
    with self.deps.main_repo.write_file(RECIPE_WARNING_DEFINITIONS_REL) as d:
      d.write('''
      monorail_bug_default {
        host: "bugs.chromium.org"
        project: "chromium"
      }
      warning {
        name: "MYMODULE_SWIZZLE_BADARG_USAGE"
        description: "The `badarg` argument on my_mod.swizzle is deprecated."
        deadline: "2020-01-01"
        monorail_bug {
          id: 123456
        }
      }
      warning {
        name: "MYMODULE_DEPRECATION"
        description: "my_mod is deprecated."
        # Comment goes here
        description: "Use other_mod instead."
        deadline: "2020-12-31"
        monorail_bug {
          project: "chrome-operations"
          id: 654321
        }
      }
      ''')

  def test_execution_warning(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.DEPS.append('recipe_engine/warning')
      mod.api.write('''
        def swizzle(self, bad_arg=None):
          if bad_arg is not None:
            self.m.warning.issue('MYMODULE_SWIZZLE_BADARG_USAGE')
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/bad.py') as bad:
      bad.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle('bad')
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/good.py') as good:
      good.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle()
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    with self.deps.main_repo.write_module('cool_mod') as mod:
      mod.DEPS.append('my_mod')
      mod.api.write('''
        def call_my_mod_swizzle(self):
          self.m.my_mod.swizzle('badbadbad')
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/cool_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['cool_mod']
        def RunSteps(api):
          api.cool_mod.call_my_mod_swizzle()
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    output, retcode  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 0)
    expected_regexp = textwrap.dedent(r'''
    [\*]{70}
    \s*WARNING: main/MYMODULE_SWIZZLE_BADARG_USAGE\s*
    \s*Found 2 call sites and 0 import sites\s*
    [\*]{70}
    Description:
      The `badarg` argument on my_mod\.swizzle is deprecated\.
    Deadline: 2020-01-01

    Bug Link: https://bugs\.chromium\.org/p/chromium/issues/detail\?id=123456
    Call Sites:
    .+/recipe_modules/cool_mod/api\.py:\d+
    .+/recipe_modules/my_mod/tests/bad\.py:3
    '''.strip('\n'))
    self.assertRegex(output, expected_regexp)

  def test_import_warning(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.WARNINGS.append('MYMODULE_DEPRECATION')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          pass
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    with self.deps.main_repo.write_module('cool_mod') as cool_mod:
      cool_mod.DEPS.append('my_mod')
    with self.deps.main_repo.write_file(
        'recipe_modules/cool_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['cool_mod']
        def RunSteps(api):
          pass
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    output, retcode  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 0)
    expected_regexp = textwrap.dedent(r'''
    [\*]{70}
    \s*WARNING: main/MYMODULE_DEPRECATION\s*
    \s*Found 0 call sites and 2 import sites\s*
    [\*]{70}
    Description:
      my_mod is deprecated\.
      Use other_mod instead\.
    Deadline: 2020-12-31

    Bug Link: https://bugs\.chromium\.org/p/chrome\-operations/issues/detail\?id=654321
    Import Sites:
    .+/recipe_modules/my_mod/tests/full\.py
    .+/recipe_modules/cool_mod/__init__\.py
    '''.strip('\n'))
    self.assertRegex(output, expected_regexp)

  def test_issue_both_warnings(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.DEPS.append('recipe_engine/warning')
      mod.WARNINGS.append('MYMODULE_DEPRECATION')
      mod.api.write('''
        def swizzle(self):
          self.m.warning.issue('MYMODULE_DEPRECATION')
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle()
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    output, retcode  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 0)
    expected_regexp = textwrap.dedent(r'''
    [\*]{70}
    \s*WARNING: main/MYMODULE_DEPRECATION\s*
    \s*Found 1 call sites and 1 import sites\s*
    [\*]{70}
    Description:
      my_mod is deprecated\.
      Use other_mod instead\.
    Deadline: 2020-12-31

    Bug Link: https://bugs\.chromium\.org/p/chrome\-operations/issues/detail\?id=654321
    Call Sites:
    .+/recipe_modules/my_mod/tests/full\.py:3
    Import Sites:
    .+/recipe_modules/my_mod/tests/full\.py
    '''.strip('\n'))
    self.assertRegex(output, expected_regexp)

  def test_issue_not_defined_execution_warning(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.DEPS.append('recipe_engine/warning')
      mod.api.write('''
        def swizzle(self):
          self.m.warning.issue('NOT_DEFINED_WARNING')
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle()
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    _, retcode  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 1)

  def test_issue_not_defined_import_warning(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.WARNINGS.append('NOT_DEFINED_WARNING')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          pass
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    _, retcode  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 1)

  def test_consolidate_multiple_call_sites(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.DEPS.append('recipe_engine/warning')
      mod.api.write('''
        def swizzle(self, bad_arg=None):
          if bad_arg is not None:
            self.m.warning.issue('MYMODULE_SWIZZLE_BADARG_USAGE')
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/bad.py') as bad:
      bad.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle('bad')
          api.my_mod.swizzle('very bad')
          api.my_mod.swizzle('extremely bad')
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    output, _  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertIn('/recipe_modules/my_mod/tests/bad.py:3 (and 4, 5)', output)

  def test_dedupe_causes_for_multiple_tests(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.DEPS.append('recipe_engine/warning')
      mod.api.write('''
        def swizzle(self, bad_arg=None):
          if bad_arg is not None:
            self.m.warning.issue('MYMODULE_SWIZZLE_BADARG_USAGE')
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/bad.py') as bad:
      bad.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle('bad')
        def GenTests(api):
          yield api.test('basic')
          yield api.test('again')
          yield api.test('one more time')
      '''.lstrip('\n'))
    output, _  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertIn('Found 1 call sites and 0 import sites', output)

  def test_escape_warnings(self):
    with self.deps.main_repo.write_module('my_mod') as mod:
      mod.DEPS.append('recipe_engine/warning')
      mod.api.write('''
        def swizzle(self, bad_arg=None):
          if bad_arg is not None:
            self.m.warning.issue('MYMODULE_SWIZZLE_BADARG_USAGE')
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/my_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle('bad')
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    with self.deps.main_repo.write_module('cool_mod') as mod:
      mod.DEPS.append('my_mod')
      mod.imports.append('from recipe_engine import recipe_api')
      mod.api.write(r'''
        @recipe_api.escape_warnings('^.+/MYMODULE_\w+$')
        def pass_through_to_my_mod(self, **kwargs):
          self.m.my_mod.swizzle(**kwargs)
      ''')
    with self.deps.main_repo.write_file(
        'recipe_modules/cool_mod/tests/full.py') as bad:
      bad.write('''
        DEPS = ['cool_mod']
        def RunSteps(api):
          api.cool_mod.pass_through_to_my_mod(bad_arg='bad')
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    output, _  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertNotIn('recipe_modules/cool_mod/api.py', output)
    self.assertIn('recipe_modules/cool_mod/tests/full.py', output)

  def test_cross_repo(self):
    upstream = self.deps.add_repo('upstream')
    with upstream.write_file(RECIPE_WARNING_DEFINITIONS_REL) as d:
      d.write('''
      monorail_bug_default {
        host: "bugs.chromium.org"
        project: "chromium"
      }
      warning {
        name: "MYMODULE_SWIZZLE_BADARG_USAGE"
        description: "The `badarg` argument on my_mod.swizzle is deprecated."
        deadline: "2020-01-01"
        monorail_bug {
          id: 123456
        }
      }
      warning {
        name: "MYMODULE_DEPRECATION"
        description: "my_mod is deprecated."
        # Comment goes here
        description: "Use other_mod instead."
        deadline: "2020-12-31"
        monorail_bug {
          project: "chrome-operations"
          id: 654321
        }
      }
      ''')

    with upstream.write_module('my_mod') as mod:
      mod.DEPS.append('recipe_engine/warning')
      mod.WARNINGS.append('MYMODULE_DEPRECATION')
      mod.api.write('''
        def swizzle(self, bad_arg=None):
          if bad_arg is not None:
            self.m.warning.issue('MYMODULE_SWIZZLE_BADARG_USAGE')
      ''')
    with upstream.write_file(
        'recipe_modules/my_mod/tests/full.py') as recipe:
      recipe.write('''
        DEPS = ['my_mod']
        def RunSteps(api):
          api.my_mod.swizzle('badbad')
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    upstream.commit('add my_mod module')

    with self.deps.main_repo.write_file('recipes/bad.py') as recipe:
      recipe.write('''
        DEPS = ['upstream/my_mod']
        def RunSteps(api):
          api.my_mod.swizzle('bad')
        def GenTests(api):
          yield api.test('basic')
      '''.lstrip('\n'))
    self.deps.main_repo.add_dep('upstream')
    self.deps.main_repo.commit('add recipe and upgrade upstream dep')

    output, retcode  = self.deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 0)
    expected_regexp = textwrap.dedent(r'''
    [\*]{70}
    \s*WARNING: upstream/MYMODULE_DEPRECATION\s*
    \s*Found 0 call sites and 1 import sites\s*
    [\*]{70}
    Description:
      my_mod is deprecated\.
      Use other_mod instead\.
    Deadline: 2020-12-31

    Bug Link: https://bugs\.chromium\.org/p/chrome\-operations/issues/detail\?id=654321
    Import Sites:
    .+/main/recipes/bad\.py
    [\*]{70}
    \s*WARNING: upstream/MYMODULE_SWIZZLE_BADARG_USAGE\s*
    \s*Found 1 call sites and 0 import sites\s*
    [\*]{70}
    Description:
      The `badarg` argument on my_mod\.swizzle is deprecated\.
    Deadline: 2020-01-01

    Bug Link: https://bugs\.chromium\.org/p/chromium/issues/detail\?id=123456
    Call Sites:
    .+/main/recipes/bad\.py:3
    '''.strip('\n'))
    self.assertRegex(output, expected_regexp)


if __name__ == '__main__':
  test_env.main()
