# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import inspect
from collections import defaultdict
from collections import namedtuple
from functools import reduce
from os import stat
from typing import Literal

from past.builtins import basestring

from recipe_engine.internal import recipe_deps

from .internal.warn import escape
from .util import ModuleInjectionSite
from .util import ModuleInjectionError
from .util import static_call
from .util import static_wraps


def combineify(name, dest, a, b, overwrite=False):
  """
  Combines dictionary members in two objects into a third one using addition.

  Args:
    name - the name of the member
    dest - the destination object
    a - the first source object
    b - the second source object
    overwrite - if True, for the same key, overwrite value from a with the one
        from b; otherwise, use addition to merge them.
  """
  dest_dict = getattr(dest, name)
  dest_dict.update(getattr(a, name))
  for k, v in getattr(b, name).items():
    if k in dest_dict:
      if not overwrite:
        dest_dict[k] += v
      else:
        dest_dict[k] = v
    else:
      dest_dict[k] = v


class BaseTestData:
  def __init__(self, enabled=True):
    super().__init__()
    self._enabled = enabled

  @property
  def enabled(self):
    return self._enabled


class PlaceholderTestData(BaseTestData):
  def __init__(self, data=None, name=None):
    super().__init__()
    self.data = data
    self.name = name

  def __repr__(self):
    if self.name is None:
      return "PlaceholderTestData(DEFAULT, %r)" % (self.data,)
    else:
      return "PlaceholderTestData(%r, %r)" % (self.name, self.data,)


class StepTestData(BaseTestData):
  """
  Mutable container for per-step test data.

  This data is consumed while running the recipe (during
  annotated_run.run_steps).
  """
  def __init__(self):
    super().__init__()
    # { (module, placeholder, name) -> data }. Data are for output placeholders.
    self.placeholder_data = defaultdict(dict)
    self.override = False
    self._stdout = None
    self._stderr = None
    self._retcode = None
    self._times_out_after = None
    self._cancel = False
    self._global_shutdown_event = None  # None, "before" or "after"

  def __add__(self, other):
    assert isinstance(other, StepTestData)

    if other.override:
      return other

    ret = StepTestData()

    combineify('placeholder_data', ret, self, other, overwrite=True)

    # pylint: disable=W0212
    ret._stdout = other._stdout or self._stdout
    ret._stderr = other._stderr or self._stderr
    ret._cancel = other._cancel or self._cancel
    ret._global_shutdown_event = (
      other._global_shutdown_event or self._global_shutdown_event
    )
    ret._retcode = self._retcode
    if other._retcode is not None:
      if ret._retcode is not None and ret._retcode != other._retcode:
        raise ValueError('Conflicting retcode values.')
      ret._retcode = other._retcode

    ret._times_out_after = self._times_out_after
    if other._times_out_after is not None:
      if ret._times_out_after is not None:
        raise ValueError('Conflicting times_out_after values.')
      ret._times_out_after = other._times_out_after

    return ret

  def unwrap_placeholder(self):
    # {(module, placeholder, name): data} => data.
    if len(self.placeholder_data) != 1:
      raise ValueError('Cannot unwrap placeholder_data with length > 1: len=%d'
                       % len(self.placeholder_data))
    return list(self.placeholder_data.values())[0]

  def pop_placeholder(self, module_name, placeholder_name, name):
    return self.placeholder_data.pop(
        (module_name, placeholder_name, name), PlaceholderTestData())

  @property
  def retcode(self):  # pylint: disable=E0202
    return self._retcode

  @retcode.setter
  def retcode(self, value):  # pylint: disable=E0202
    self._retcode = value

  @property
  def times_out_after(self):  # pylint: disable=E0202
    return self._times_out_after or 0

  @times_out_after.setter
  def times_out_after(self, value):  # pylint: disable=E0202
    self._times_out_after = value

  @property
  def global_shutdown_event(self):  # pylint: disable=E0202
    return self._global_shutdown_event

  @global_shutdown_event.setter
  def global_shutdown_event(self, value):  # pylint: disable=E0202
    assert value in ('before', 'after', None), "bad global_shutdown_event"
    self._global_shutdown_event = value

  @property
  def cancel(self):  # pylint: disable=E0202
    return self._cancel

  @cancel.setter
  def cancel(self, value):  # pylint: disable=E0202
    self._cancel = value

  @property
  def stdout(self):
    return self._stdout or PlaceholderTestData(None)

  @stdout.setter
  def stdout(self, value):
    assert isinstance(value, PlaceholderTestData)
    self._stdout = value

  @property
  def stderr(self):
    return self._stderr or PlaceholderTestData(None)

  @stderr.setter
  def stderr(self, value):
    assert isinstance(value, PlaceholderTestData)
    self._stderr = value

  @property
  def stdin(self):  # pylint: disable=R0201
    return PlaceholderTestData(None)

  def __repr__(self):
    dct = {
      'placeholder_data': dict(self.placeholder_data.items()),
      'stdout': self._stdout,
      'stderr': self._stderr,
      'retcode': self._retcode,
      'override': self.override,
      'cancel': self.cancel,
    }

    if self.global_shutdown_event:
      dct['global_shutdown_event'] = self.global_shutdown_event

    if self.times_out_after:
      dct['times_out_after'] = self.times_out_after

    return "StepTestData(%r)" % dct


class ModuleTestData(BaseTestData, dict):
  """
  Mutable container for test data for a specific module.

  This test data is consumed at module load time (i.e. when create_recipe_api
  runs).
  """
  def __add__(self, other):
    assert isinstance(other, ModuleTestData)
    # BUG(crbug.com/327644647) - this implementation can silently drop data.
    ret = ModuleTestData()
    ret.update(self)
    ret.update(other)
    return ret

  def __repr__(self):
    return "ModuleTestData(%r)" % super().__repr__()


PostprocessHookContext = namedtuple(
    'PostprocessHookContext', 'func args kwargs filename lineno')
"""The context describing where a post-process hook was added."""

PostprocessHook = namedtuple(
  'PostprocessHook', 'func args kwargs context')
"""The details of a post-process hook.

func, args and kwargs detail the actual objects to use to invoke the check.
Context describes where the hook was added. Depending on whether post_process
or post_check is used, the context may or may not contain the same func, args
and kwargs.
"""


class TestData(BaseTestData):
  def __init__(self, name=None):
    super().__init__()
    self.name = name
    self.properties = {}  # key -> val
    self.environ = {}  # key -> val
    self.luci_context = {}  # key -> val
    self.mod_data = defaultdict(ModuleTestData)
    self.step_data = defaultdict(StepTestData)
    self.expected_exceptions = []
    self.expected_status = None
    self.post_process_hooks: list[PostprocessHook] = []
    self.assert_turboci_graph_hooks: list[PostprocessHook] = []

    # Filled in by recipe_deps.Recipe.gen_tests()
    self.expect_file = None

  def __add__(self, other):
    assert isinstance(other, TestData), repr(other)

    ret = TestData(self.name or other.name)

    ret.properties.update(self.properties)
    ret.properties.update(other.properties)

    ret.environ.update(self.environ)
    ret.environ.update(other.environ)

    # Override each section value instead of merging
    combineify('luci_context', ret, self, other, overwrite=True)

    combineify('mod_data', ret, self, other)
    combineify('step_data', ret, self, other)

    ret.post_process_hooks.extend(self.post_process_hooks)
    ret.post_process_hooks.extend(other.post_process_hooks)

    ret.assert_turboci_graph_hooks.extend(self.assert_turboci_graph_hooks)
    ret.assert_turboci_graph_hooks.extend(other.assert_turboci_graph_hooks)

    ret.expected_status = self.expected_status
    if other.expected_status is not None:
      ret.expected_status = other.expected_status

    ret.expected_exceptions = [
        *self.expected_exceptions, *other.expected_exceptions
    ]

    return ret

  @property
  def consumed(self):
    return not (self.step_data or self.expected_exception)

  def pop_step_test_data(self, step_name, step_test_data_fn):
    step_test_data = step_test_data_fn()
    if step_name in self.step_data:
      try:
        step_test_data += self.step_data.pop(step_name)
      except ValueError as ve:
        raise ValueError('in step %r: %s' % (step_name, ve))
    return step_test_data

  def get_module_test_data(self, module_name):
    return self.mod_data.get(module_name, ModuleTestData())

  def expect_exception(self, exception):
    if not isinstance(exception, basestring):
      raise ValueError('expect_exception expects a string containing the '
                       'exception class name')
    self.expected_exceptions.append(exception)

  @escape.escape_warnings('.*')
  def post_process(self, func, args, kwargs, context):
    for warning in getattr(func, 'recipe_warnings', ()):
      record_execution_warning(warning)
    self.post_process_hooks.append(PostprocessHook(func, args, kwargs, context))

  @escape.escape_warnings('.*')
  def assert_turboci_graph(self, func, args, kwargs, context):
    for warning in getattr(func, 'recipe_warnings', ()):
      record_execution_warning(warning)
    self.assert_turboci_graph_hooks.append(PostprocessHook(func, args, kwargs, context))

  def __repr__(self):
    return "TestData(%r)" % ({
      'name': self.name,
      'properties': self.properties,
      'environ': self.environ,
      'luci_context': self.luci_context,
      'mod_data': dict(self.mod_data.items()),
      'step_data': dict(self.step_data.items()),
      'expected_exceptions': self.expected_exceptions,
      'expected_status': self.expected_status,
    },)


class DisabledTestData(BaseTestData):
  def __init__(self):
    super().__init__(False)

  def __getattr__(self, name):
    return self

  def pop_placeholder(self, _module_name, _placeholder_name, _name):
    return self

  def pop_step_test_data(self, _step_name, _step_test_data_fn):
    return self

  def get_module_test_data(self, _module_name):
    return ModuleTestData(enabled=False)


def mod_test_data(func):
  @static_wraps(func)
  def inner(self, *args, **kwargs):
    assert isinstance(self, RecipeTestApi)
    ret = TestData(None)
    data = static_call(self, func, *args, **kwargs)
    ret.mod_data[self._module.name][inner.__name__] = data
    return ret
  return inner


def placeholder_step_data(func):
  """Decorates RecipeTestApi member functions to allow those functions to
  return just the output placeholder data, instead of the normally required
  StepTestData() object.

  The wrapped function may return either:
    * <placeholder data>, <retcode or None>, <name or None>
    * StepTestData containing exactly one PlaceholderTestData and possible a
      retcode. This is useful for returning the result of another method which
      is wrapped with placeholder_step_data.

  In either case, the wrapper function will return a StepTestData object with
  the retcode and placeholder datum inserted with a name of:
    (<Test module name>, <wrapped function name>, <name>)

  Say you had a 'foo_module' with the following RecipeTestApi:
    class FooTestApi(RecipeTestApi):
      @placeholder_step_data
      @staticmethod
      def cool_method(data, retcode=None, name=None):
        return ("Test data (%s)" % data), retcode, name

      @placeholder_step_data
      def other_method(self, retcode=None, name=None):
        return self.cool_method('hammer time', retcode=retcode, name=name)

  Code calling cool_method('hello', name='cool1') would get a StepTestData:
    StepTestData(
      placeholder_data = {
        ('foo_module', 'cool_method', 'cool1') :
          PlaceholderTestData('Test data (hello)')
      },
      retcode = None
    )

  Code calling other_method(retcode=50, name='other1') would get a StepTestData:
    StepTestData(
      placeholder_data = {
        ('foo_module', 'other_method', 'other1'):
          PlaceholderTestData('Test data (hammer time)')
      },
      retcode = 50
    )

  You can also use the alternate form of the decorator to mock a RecipeApi
  placeholder method with a different name from the decorated RecipeTestApi
  method:
    class FooTestApi(RecipeTestApi):
      @placeholder_step_data('cool_method')
      @staticmethod
      def blah_method(data, retcode=None, name=None):
        return ("Test data (%s)" % data), retcode, name

  Code calling blah_method('hello', name='blah1') would get a StepTestData:
    StepTestData(
      placeholder_data = {
        ('foo_module', 'cool_method', 'cool1') :
          PlaceholderTestData('Test data (hello)')
      },
      retcode = None
    )

  Note that the placeholder name (cool_method) is different from the
  RecipeTestApi method name (blah_method). This lets you define many
  RecipeTestApi helper methods for mocking a single
  """
  if callable(func) or isinstance(func, staticmethod):
    # Plain decorator:
    # @placeholder_step_data
    return _placeholder_step_data(func)
  else:
    # Decorator with placeholder name argument:
    # @placeholder_step_data('placeholder_name')
    mocked_func_name = func
    assert isinstance(mocked_func_name, basestring), (
      'placeholder_step_data used as decorator with non-string argument %r'
      % mocked_func_name
    )

    def decorator(func):
      return _placeholder_step_data(func, mocked_func_name)

    return decorator


def _placeholder_step_data(func, placeholder_name=None):
  @static_wraps(func)
  def inner(self, *args, **kwargs):
    assert isinstance(self, RecipeTestApi)
    data = static_call(self, func, *args, **kwargs)
    if isinstance(data, StepTestData):
      all_data = list(data.placeholder_data.values())
      if len(all_data) != 1:
        raise ValueError(
          'placeholder_step_data is only expecting a single output placeholder '
          'datum. Got: %r' % data
        )
      placeholder_data, retcode = all_data[0], data._retcode
    else:
      placeholder_data, retcode, name = data
      placeholder_data = PlaceholderTestData(data=placeholder_data, name=name)

    ret = StepTestData()
    final_placeholder_name = placeholder_name
    if placeholder_name is None:
      final_placeholder_name = inner.__name__
    key = (self._module.name, final_placeholder_name, placeholder_data.name)
    ret.placeholder_data[key] = placeholder_data
    ret.retcode = retcode
    return ret
  return inner


class RecipeTestApi:
  """Provides testing interface for GenTest method.

  There are two primary components to the test api:
    * Test data creation methods (test and step_data)
    * test_api's from all the modules in DEPS.

  Every test in GenTests(api) takes the form:
    yield <instance of TestData>

  There are 7 basic pieces to TestData:
    name          - The name of the test.
    status        - The expected status of the test. Must be one of the statuses
                    found in the Common.Status enum. Defaults to SUCCESS.
    properties    - Dictionary which is used as the properties for this test.
                    You may use protobuf message objects as part of the
                    dictionary and they'll be expanded to their JSON dictionary
                    representation.
    environ       - Single-level key-value dictionary which is used as the
                    environment variables for this test.
    luci_context  - Dictionary (mapping from section key to its proto value
                    serialized in dict) which is used as the initial
                    LUCI_CONTEXT value for this test.
    mod_data      - Module-specific testing data (see the platform module for a
                    good example). This is testing data which is only used once
                    at the start of the execution of the recipe. Modules should
                    provide methods to get their specific test information. See
                    the platform module's test_api for a good example of this.
    step_data     - Step-specific data. There are two major components to this.
          retcode          - The return code of the step
          placeholder_data - A mapping from placeholder name to the
                             PlaceholderTestData object in the step.
          stdout, stderr   - PlaceholderTestData objects for stdout and stderr.

  TestData objects are concatenatable, so it's convenient to phrase test cases
  as a series of added TestData objects. For example:
    DEPS = ['properties', 'platform', 'json']
    def GenTests(api):
      yield (
        api.test('try_win64') +
        api.properties.tryserver(power_level=9001) +
        api.context.luci_context(
          luciexe=sections_pb2.LUCIExe(cache_dir='/a/b/c'),
          resultdb=sections_pb2.ResultDB(current_invocation=...)
        ) +
        api.platform('win', 64) +
        api.step_data(
          'some_step',
          api.json.output("bobface", name="a"),
          api.json.output({'key': 'value'}, name="b")
        )
      )

  This example would run a single test (named 'try_win64') with the standard
  tryserver properties (plus an extra property 'power_level' whose value was
  over 9000).  The test would run as if it were being run on a 64-bit windows
  installation, and the step named 'some_step' would have the json output of
  the placeholder with name "a" be mocked to return '"bobface"', and the json
  output of the placeholder with name "b" be mocked to return
  '{"key": "value"}'. The test would expect the status at the end to be success.

  The properties.tryserver() call is documented in the 'properties' module's
  test_api.
  The platform() call is documented in the 'platform' module's test_api.
  The json.output() call is documented in the 'json' module's test_api.
  """

  def __init__(self, module: 'recipe_deps.RecipeModule | None'):
    """Note: Injected dependencies are NOT available in __init__()."""
    # If we're the 'root' api, inject directly into 'self'.
    # Otherwise inject into 'self.m'
    self.m = self if module is None else ModuleInjectionSite()
    self._module = module

  def __getattr__(self, name):
    if self._module is None:
      raise ModuleInjectionError(
          f"Recipe has no dependency {name!r}. (Add it to DEPS?)")
    raise AttributeError(f"'RecipeTestApi' object has no attribute {name!r}")

  # TODO(iannucci): Fix this and other kwargs to use direct keyword py3 syntax.
  @staticmethod
  def test(name, *test_data, **kwargs):
    """Returns a new empty TestData with the name filled in.

    Use in GenTests:
      def GenTests(api):
        yield api.test('basic')

        yield api.test(
            # All test cases have a name; Recipe test full test names always
            # look like '<name of recipe>.<test case name>'. Recipe names
            # will look like 'path/under/recipes/directory/to/recipe_file'
            # or 'recipe_module_name:tests/recipe_file'.
            #
            # Note that spaces in test names are allowed, but can be annoying to
            # work with when e.g. using the `--filter` CLI argument on
            # `recipes.py test train` due to extra quoting requirements.
            'moreComplex',

            # Properties are semi-structured input (~JSON object) which the
            # recipe operates on, and can observe with PROPERTIES declarations
            # or (less preferred) via the `properties` recipe module.
            api.properties(
                foo='foo-value',
                bar='bar-value',
            ),

            # Here is an example of how to mock the state of the `platform`
            # module using its 'test API'. This adjusts state in the `platform`
            # module so that when the recipe queries it during this test, it
            # will claim that the recipe is operating in a 32bit windows
            # environment. Many modules have ways to mock their state, though
            # most mocks will appear in the form of `step_data` which mocks the
            # output of running one (or more) steps from that module, providing
            # mock outputs such as JSON output, return codes, etc.
            api.platform.name('win'),
            api.platform.bits(32),

            # Most recipes keep and review expectation files, but some teams
            # use DropExpectation in addition to other additional assertions
            # instead.
            #
            # If you choose to drop expectations, but don't make any other
            # assertions, your test will not be doing much aside from
            # ensuring that the code does not crash when executed.
            api.post_process(<assertion>),
            api.post_process(<other assertion>),
            api.post_process(post_process.DropExpectation),

            # All recipe tests must state the expected outcome of the overall
            # recipe by setting the status. By default, tests which omit this
            # status will expect a SUCCESS outcome. If your test uses
            # `expect_exception`, the test will expect an INFRA_FAILURE outcome.
            # The valid statuses here are:
            #   * SUCCESS
            #   * FAILURE (recipe ended by explicitly returning this, or raising
            #     StepFailure)
            #   * INFRA_FAILURE (recipe ended by explicitly returning this,
            #     raising InfraFailure, or by raising some other exception)
            #   * CANCELED (recipe ended by explicitly returning this,
            #     raising InfraFailure (canceled), or by mocking external
            #     cancelation)
            #
            # This is a shorthand for using `api.expect_status(...)` at the very
            # beginning of `test_data`. Adding api.expect_status into test_data,
            # or using api.expect_exception will override this.
            status='FAILURE',
        )

    Arguments:
      name - The name of the test.
      *test_data - Additional TestData objects to combine into the returned
          TestData. The returned TestData will have each element added (in the
          same order they are passed) to it.
    """
    from PB.go.chromium.org.luci.buildbucket.proto.common import Status
    base = TestData(name)
    if 'status' in kwargs:
      base.expected_status = Status.Value(kwargs['status'])
    ret = sum(test_data, base)
    return ret

  @staticmethod
  def empty_test_data():
    """Returns a TestData with no information.

    This is the identity of the + operator for combining TestData.
    """
    return TestData()

  @staticmethod
  def recipe_test_data(**kwargs) -> TestData:
    """Returns TestData which gets plumbed through to RunSteps' `api`.

    Example:

       def RunSteps(api):
         mock_data = None
         if api._test_data.enabled:
           mock_data = api._test_data.get('mock_data', None)

         api.m.something(..., test_data=mock_data)

       def GenTests(api):
         # mock_data is 'a'
         yield api.test('a', api.recipe_test_data(mock_data='a'))

         # mock_data is 'b'
         yield api.test('b', api.recipe_test_data(mock_data='b'))

         # mock_data is None
         yield api.test('c')
    """
    ret = TestData()
    ret.mod_data[None].update(kwargs)
    return ret

  @staticmethod
  def _step_data(
      name: str,
      *data: StepTestData,
      retcode: int | None = None,
      stdout: StepTestData | None = None,
      stderr: StepTestData | None = None,
      override: bool | None = None,
      times_out_after: int | None = None,
      cancel: bool | None = None,
      global_shutdown_event: Literal['before', 'after'] | None = None,
  ) -> TestData:
    """Returns a new TestData with the mock data filled in for a single step.

    Used by step_data and override_step_data.

    Args:
      name - The name of the step we're providing data for.
      data - Zero or more StepTestData objects. These may fill in output placeholder
          data for zero or more modules, as well as possibly setting the retcode for
          this step.
      retcode - Override the retcode for this step, even if it was set by |data|.
          This must be set as a keyword arg. In the case of None, if the step
          completes successfully (not canceled or timed out), then the step's retcode
          will be 0.
      stdout - StepTestData object with a single output placeholder datum for a
          step's stdout.
      stderr - StepTestData object with a single output placeholder datum for a
          step's stderr.
      override - This step data completely replaces any previously generated step
          data, instead of adding on to it.
      times_out_after - Causes the step to timeout after the given number of seconds.
      cancel=(bool) - Causes the step to indicate that it was canceled.
      global_shutdown_event=(None,'before','after') - Causes a global shutdown
          either before or after this step runs.

    Use in GenTests:
      # Hypothetically, suppose that your recipe has default test data for two
      # steps 'init' and 'sync' (probably via recipe_api.inject_test_data()).
      # For this example, lets say that the default test data looks like:
      #   api.step_data('init', api.json.output({'some': ["cool", "json"]}))
      # AND
      #   api.step_data('sync', api.json.output({'src': {'rev': 100}}))
      # Then, your GenTests code may augment or replace this data like:

      def GenTests(api):
        yield (
          api.test('more') +
          api.step_data(  # Adds step data for a step with no default test data
            'mystep',
            api.json.output({'legend': ['...', 'DARY!']})
          ) +
          api.step_data(  # Adds retcode to default step_data for this step
            'init',
            retcode=1
          ) +
          api.override_step_data(  # Removes json output and overrides retcode
            'sync',
            retcode=100
          )
        )
    """
    assert all(isinstance(d, StepTestData) for d in data)
    assert isinstance(stdout, (StepTestData, type(None)))
    assert isinstance(stderr, (StepTestData, type(None)))

    ret = TestData(None)
    if data:
      ret.step_data[name] = reduce(lambda x,y: x + y, data)
    if retcode is not None:
      ret.step_data[name].retcode = retcode
    if times_out_after is not None:
      ret.step_data[name].times_out_after = times_out_after
    if cancel is not None:
      ret.step_data[name].cancel = cancel
    if global_shutdown_event is not None:
      ret.step_data[name].global_shutdown_event = global_shutdown_event
    if override is not None:
      ret.step_data[name].override = override

    if stdout is not None:
      ret.step_data[name].stdout = stdout.unwrap_placeholder()
    if stderr is not None:
      ret.step_data[name].stderr = stderr.unwrap_placeholder()

    return ret

  def step_data(self, name, *data, **kwargs):
    """See _step_data()"""
    return self._step_data(name, *data, **kwargs)
  step_data.__doc__ = _step_data.__doc__

  def override_step_data(self, name, *data, **kwargs):
    """See _step_data()"""
    kwargs['override'] = True
    return self._step_data(name, *data, **kwargs)
  override_step_data.__doc__ = _step_data.__doc__

  def expect_exception(self, exc_type):
    """Indicate that this test should end by raising an exception from RunSteps
    whose exception class name is `exc_type`.

    Using this will imply an `expect_status` of INFRA_FAILURE - If you want to
    override this, add an explicit expect_status after this expect_exception.

    Args:
      * exc_type - String value of exception name.

    Returns `TestData` which can be added to other TestData prior to yielding
    from GenTests, or can be included as `*test_data` to the `test(name, ...)`
    function in RecipeTestApi.
    """
    from PB.go.chromium.org.luci.buildbucket.proto.common import Status
    ret = TestData()
    ret.expect_exception(exc_type)
    ret.expected_status = Status.INFRA_FAILURE
    return ret

  def expect_status(self, status):
    """Indicate that this test should have an overall status of `status`.

    Args:
      * status - String value of Buildbucket Common Status (i.e. SUCCESS,
        FAILURE, INFRA_FAILURE, CANCELED)

    Returns `TestData` which can be added to other TestData prior to yielding
    from GenTests, or can be included as `*test_data` to the `test(name, ...)`
    function in RecipeTestApi.
    """
    from PB.go.chromium.org.luci.buildbucket.proto.common import Status
    ret = TestData()
    ret.expected_status = Status.Value(status)
    return ret

  def post_process(self, func, *args, **kwargs):
    """Calling this adds a post-processing hook for this test's expectations.

    `func` should be a callable whose signature is in the form of:
      func(check, step_odict, *args, **kwargs) -> (step_odict or None)

    Where:
      * `step_odict` is an ordered dictionary of `Step` objects (see `Step` in
      //recipe_engine/post_process_inputs.py). The final item will have the key
      '$result' and will be a dictionary describing the final result of the
      recipe rather than a `Step`.

      * `check` is a semi-magical function which you can use to test things.
      Using `check` will allow you to see all the violated assertions from your
      post_process functions simultaneously. Always call `check` directly (i.e.
      with parens) to produce helpful check messages. `check` also has a second
      form that takes a human hint to print when the `check` fails. Hints should
      be written as the ___ in the sentence 'check that ___.'. Essentially,
      check has the function signatures:

        `def check(<bool expression>) #=> bool`
        `def check(hint, <bool expression>) #=> bool`

      Check returns True iff the boolean expression was True.

      If the hint is omitted, then the boolean expression itself becomes the
      hint when the check failure message is printed.

      Note that check DOES NOT stop your function. It is not an assert. Your
      function will continue to execute after invoking the check function. If
      the boolean expression is False, the check will produce a helpful error
      message and cause the test case to fail.

      * args and kwargs are optional, and completely up to your implementation.
      They will be passed straight through to your function, and are provided to
      eliminate an extra `lambda` if your function needs to take additional
      inputs.

    If a KeyError is raised, it will be caught and a check failure will be
    emitted with details about the expression that resulted in the KeyError and
    post-processing will continue at the next hook. This allows hooks to assume
    that a key is present without sacrificing debuggability. If any other
    exception is raised, the exception will be printed and the post-processing
    chain will be halted.

    The function must return either `None`, or it may return a filtered subset
    of step_odict (e.g. omitting some steps and/or step fields). This will be
    the new value of step_odict for the test. Returning an empty dict or
    OrderedDict will remove the expectations from disk altogether. Returning
    `None` (Python's implicit default return value) is equivalent to returning
    the unmodified step_odict. To use lambdas that simply call `check`, use
    `post_check` instead of `post_process`.

    Steps can be returned either as a `Step` or as a dictionary obtained by
    calling `to_step_dict` on a `Step`. It is fine to mix representations
    between different steps. Fields can be removed from a field either by
    setting them to their default value or removing the item for the field when
    returning a dict. 'name' will always be preserved in every step, even if you
    remove it.

    Calling post_process multiple times will apply each function in order,
    chaining the output of one function to the input of the next function. This
    is intended to be use to compose the effects of multiple re-usable
    post-processing functions, some of which are pre-defined in
    `recipe_engine.post_process` which you can import in your recipe.

    Example:
      from recipe_engine.post_process import (Filter, DoesNotRun,
        DropExpectation)

      def GenTests(api):
        yield api.test('no post processing')

        yield (api.test('only thing_step')
          + api.post_process(Filter('thing_step'))
        )

        tstepFilt = Filter()
        tstepFilt = tstepFilt.include('thing_step', 'cmd')
        yield (api.test('only thing_step\'s cmd')
          + api.post_process(tstepFilt)
        )

        yield (api.test('assert bob_step does not run')
          + api.post_process(DoesNotRun, 'bob_step')
        )

        yield (api.test('only care one step and the result')
          + api.post_process(Filter('one_step', '$result'))
        )

        def assertStuff(check, step_odict, to_check):
          check(to_check in step_odict['step_name'].cmd)

        yield (api.test('assert something and have NO expectation file')
          + api.post_process(assertStuff, 'to_check_arg')
          + api.post_process(DropExpectation)
        )
    """
    ret = TestData()
    _, filename, lineno, _, _, _ = inspect.stack()[1]
    context = PostprocessHookContext(func, args, kwargs, filename, lineno)
    ret.post_process(func, args, kwargs, context)
    return ret

  def post_check(self, func, *args, **kwargs):
    """Add a check-only post-processing hook.

    See `post_process` for information on the arguments and behavior. The
    difference between `post_check` and `post_process` is the return value of
    `func` is ignored, so it's not possible for a hook added using `post_check`
    to propagate changes in the steps dictionary to later hooks. This enables
    the use of lambdas for performing simple checks.

    Example:
      from recipe_engine.post_process import DoesNotRun, DropExpectation

    def GenTests(api):
      yield (api.test('lambda-check')
        + api.post_check(lambda check, steps: check('foo' not in steps))
        + api.post_process(DropExpectation)
      )

      yield (api.test('reuse-existing-hook')
        + api.post_check(DoesNotRun, 'foo')
        + api.post_process(DropExpectation)
      )
    """
    def post_check(check, steps, f, *args, **kwargs):
      f(check, steps, *args, **kwargs)
    ret = TestData()
    _, filename, lineno, _, _, _ = inspect.stack()[1]
    context = PostprocessHookContext(func, args, kwargs, filename, lineno)
    ret.post_process(post_check, (func,) + args, kwargs, context)
    return ret

  def assert_turboci_graph(self, func, *args, **kwargs):
    """Add a check-only post-processing hook which asserts on the TurboCI
    graph state.

    This is like post_process, except that func should look like:

       from PB.turboci.graph.orchestrator.v1.graph_view import GraphView

       func(assert_, graph: GraphView, *args, **kwargs) -> None

    def GenTests(api):
      def _assert_graph(assert_, graph: GraphView):
        check_view = graph.checks[0]
        assert_(check_view.check.identifier.id == 'bob')

      yield api.test(
        'whatever',
        api.assert_turboci_graph(_check_graph),
      )
    """
    def post_check(check, steps, f, *args, **kwargs):
      f(check, steps, *args, **kwargs)
    ret = TestData()
    _, filename, lineno, _, _, _ = inspect.stack()[1]
    context = PostprocessHookContext(func, args, kwargs, filename, lineno)
    ret.assert_turboci_graph(post_check, (func,) + args, kwargs, context)
    return ret


# Exports warning escape decorators

# escape_warnings is a function decorator which will cause warnings matching any
# of the given regexps to be attributed to the decorated function's caller
# instead of the decorated function itself.
#
#   escape_warnings(*warning_name_regexps)
escape_warnings = escape.escape_warnings

# escape_all_warnings is a function decorator which is equivalent to
# `escape_warnings(".*")`
escape_all_warnings = escape.escape_all_warnings

# ignore_warnings is a function decorator which will cause warnings matching any
# of the given regexps to be ignored (i.e. swallowed).
#
#   ignore_warnings(*warning_name_regexps)
ignore_warnings = escape.ignore_warnings


def record_execution_warning(warning_name, skip=0):
  """Records a warning during testing.

  No-op in production contexts.

  Args:
    * name - the name of a pre-defined warning in a recipe.warnings file.
      If this is absolute (i.e. "repo/WARNING"), then it's used as-is.
      Otherwise "WARNING" would be resolved against the recipe repo containing
      the function which calls this one.
    * skip - the number of stack frames to skip before starting attribution.
      A value of 0 indicates that your frame is skipped, so 1 would skip your
      caller's frame, etc.
  """
  from recipe_engine.internal.warn.record import GLOBAL
  GLOBAL.record_execution_warning(warning_name, skip+1)
