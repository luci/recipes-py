# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import inspect
import os
import re

from collections import namedtuple

# These have to do with deriving classes from namedtuple return values.
# Pylint can't tell that namedtuple returns a new-style type() object.
#
# "no __init__ method" pylint: disable=W0232
# "use of super on an old style class" pylint: disable=E1002

UnknownError = namedtuple('UnknownError', 'message')
NoMatchingTestsError = namedtuple('NoMatchingTestsError', '')
Result = namedtuple('Result', 'data')
MultiResult = namedtuple('MultiResult', 'results')

class ResultStageAbort(Exception):
  pass


class Failure(object):
  pass


class TestError(namedtuple('TestError', 'test message log_lines')):
  def __new__(cls, test, message, log_lines=()):
    return super(TestError, cls).__new__(cls, test, message, log_lines)


class Bind(namedtuple('_Bind', 'loc name')):
  """A placeholder argument for a FuncCall.

  A Bind instance either indicates a 0-based index into the args argument,
  or a name in kwargs when calling .bind().
  """

  def __new__(cls, loc=None, name=None):
    """Either loc or name must be defined."""
    assert ((loc is None and isinstance(name, str)) or
            (name is None and 0 <= loc))
    return super(Bind, cls).__new__(cls, loc, name)

  def bind(self, args=(), kwargs=None):
    """Return the appropriate value for this Bind when binding against args and
    kwargs.

    >>> b = Bind(2)
    >>> # A bind will return itself if a matching arg value isn't present
    >>> b.bind(['cat'], {'arg': 100}) is b
    True
    >>> # Otherwise the matching value is returned
    >>> v = 'money'
    >>> b.bind(['happy', 'cool', v]) is v
    True
    >>> b2 = Bind(name='cat')
    >>> b2.bind((), {'cat': 'cool'})
    'cool'
    """
    kwargs = kwargs or {}
    if self.loc is not None:
      v = args[self.loc:self.loc+1]
      return self if not v else v[0]
    else:
      return kwargs.get(self.name, self)

  @staticmethod
  def maybe_bind(value, args, kwargs):
    """Helper which binds value with (args, kwargs) if value is a Bind."""
    return value.bind(args, kwargs) if isinstance(value, Bind) else value


class FuncCall(object):
  def __init__(self, func, *args, **kwargs):
    """FuncCall is a trivial single-function closure which is pickleable.

    This assumes that func, args and kwargs are all pickleable.

    When constructing the FuncCall, you may also set any positional or named
    argument to a Bind instance. A FuncCall can then be bound with the
    .bind(*args, **kwargs) method, and finally called by invoking func_call().

    A FuncCall may also be directly invoked with func_call(*args, **kwargs),
    which is equivalent to func_call.bind(*args, **kwargs)().

    Invoking a FuncCall with an unbound Bind instance is an error.

    >>> def func(alpha, beta=None, gamma=None):
    ...   return '%s-%s-%s' % (alpha, beta, gamma)
    >>> f = FuncCall(func, Bind(2), beta=Bind(name='context'), gamma=Bind(2))
    >>> # the first arg and the named arg 'gamma' are bound to index 2 of args.
    >>> # the named arg 'beta' is bound to the named kwarg 'context'.
    >>> #
    >>> # The FuncCall is equivalent to (py3 pattern syntax):
    >>> #   UNSET = object()
    >>> #   def f(_, _, arg1, *_, context=UNSET, **_):
    >>> #      assert pickle is not UNSET
    >>> #      return func(arg1, beta=context, gamma=arg1)
    >>> bound = f.bind('foo', 'bar', 'baz', context=100, extra=None)
    >>> # At this point, bound is a FuncCall with no Bind arguments, and can be
    >>> # invoked. This would be equivalent to:
    >>> #   func('baz', beta=100, gamma='baz')
    >>> bound()
    baz-100-baz

    Unused arguments in the .bind() call are ignored, which allows you to build
    value-agnostic invocations to FuncCall.bind().
    """
    self._func = func
    self._args = args
    self._kwargs = kwargs
    self._fully_bound = None

  # "access to a protected member" pylint: disable=W0212
  func = property(lambda self: self._func)
  args = property(lambda self: self._args)
  kwargs = property(lambda self: self._kwargs)

  @property
  def fully_bound(self):
    if self._fully_bound is None:
      self._fully_bound = not (
          any(isinstance(v, Bind) for v in self._args) or
          any(isinstance(v, Bind) for v in self._kwargs.itervalues())
      )
    return self._fully_bound

  def bind(self, *args, **kwargs):
    if self.fully_bound or not (args or kwargs):
      return self

    new = FuncCall(self._func)
    new._args = [Bind.maybe_bind(a, args, kwargs) for a in self.args]
    new._kwargs = {k: Bind.maybe_bind(v, args, kwargs)
                   for k, v in self.kwargs.iteritems()}
    return new

  def __call__(self, *args, **kwargs):
    f = self.bind(args, kwargs)
    assert f.fully_bound
    return f.func(*f.args, **f.kwargs)

  def __repr__(self):
    return 'FuncCall(%r, *%r, **%r)' % (self.func, self.args, self.kwargs)


_Test = namedtuple(
    'Test', 'name func_call expect_dir expect_base ext covers breakpoints')

class Test(_Test):
  TEST_COVERS_MATCH = re.compile('.*/test/([^/]*)_test\.py$')

  def __new__(cls, name, func_call, expect_dir=None, expect_base=None,
              ext='json', covers=None, breakpoints=None, break_funcs=()):
    """Create a new test.

    @param name: The name of the test. Will be used as the default expect_base

    @param func_call: A FuncCall object

    @param expect_dir: The directory which holds the expectation file for this
                       Test.
    @param expect_base: The basename (without extension) of the expectation
                        file. Defaults to |name|.
    @param ext: The extension of the expectation file. Affects the serializer
                used to write the expectations to disk. Valid values are
                'json' and 'yaml' (Keys in SERIALIZERS).
    @param covers: A list of coverage file patterns to include for this Test.
                   By default, a Test covers the file in which its function
                   was defined, as well as the source file matching the test
                   according to TEST_COVERS_MATCH.

    @param breakpoints: A list of (path, lineno, func_name) tuples. These will
                        turn into breakpoints when the tests are run in 'debug'
                        mode. See |break_funcs| for an easier way to set this.
    @param break_funcs: A list of functions for which to set breakpoints.
    """
    breakpoints = breakpoints or []
    if not breakpoints or break_funcs:
      for f in (break_funcs or (func_call.func,)):
        if hasattr(f, 'im_func'):
          f = f.im_func
        breakpoints.append((f.func_code.co_filename,
                            f.func_code.co_firstlineno,
                            f.func_code.co_name))

    expect_dir = expect_dir.rstrip('/')
    return super(Test, cls).__new__(cls, name, func_call, expect_dir,
                                    expect_base, ext, covers, breakpoints)

  def coverage_includes(self):
    if self.covers is not None:
      return self.covers

    test_file = inspect.getabsfile(self.func_call.func)
    covers = [test_file]
    match = Test.TEST_COVERS_MATCH.match(test_file)
    if match:
      covers.append(os.path.join(
          os.path.dirname(os.path.dirname(test_file)),
          match.group(1) + '.py'
      ))

    return covers

  def expect_path(self, ext=None):
    expect_dir = self.expect_dir
    if expect_dir is None:
      test_file = inspect.getabsfile(self.func_call.func)
      expect_dir = os.path.splitext(test_file)[0] + '.expected'
    name = self.expect_base or self.name
    name = ''.join('_' if c in '<>:"\\/|?*\0' else c for c in name)
    return os.path.join(expect_dir, name + ('.%s' % (ext or self.ext)))

  def run(self, context=None):
    return self.func_call(context=context)

  def process(self, func=lambda test: test.run()):
    """Applies |func| to the test, and yields (self, func(self)).

    For duck-typing compatibility with MultiTest.

    Bind(name='context') if used by your test function, is bound to None.

    Used interally by expect_tests, you're not expected to call this yourself.
    """
    yield self, func(self.bind(context=None))

  def bind(self, *args, **kwargs):
    return self._replace(func_call=self.func_call.bind(*args, **kwargs))

  def restrict(self, tests):
    assert tests[0] is self
    return self


_MultiTest = namedtuple(
    'MultiTest', 'name make_ctx_call destroy_ctx_call tests atomic')

class MultiTest(_MultiTest):
  """A wrapper around one or more Test instances.

  Allows the entire group to have common pre- and post- actions and an optional
  shared context between the Test methods (represented by Bind(name='context')).

  Args:
    name - The name of the MultiTest. Each Test's name should be prefixed with
        this name, though this is not enforced.
    make_ctx_call - A FuncCall which will be called once before any test in this
        MultiTest runs. The return value of this FuncCall will become bound
        to the name 'context' for both the |destroy_ctx_call| as well as every
        test in |tests|.
    destroy_ctx_call - A FuncCall which will be called once after all tests in
        this MultiTest runs. The context object produced by |make_ctx_call| is
        bound to the name 'context'.
    tests - A list of Test instances. The context object produced by
        |make_ctx_call| is bound to the name 'context'.
    atomic - A boolean which indicates that this MultiTest must be executed
        either all at once, or not at all (i.e., subtests may not be filtered).
  """

  def restrict(self, tests):
    """A helper method to re-cast the MultiTest with fewer subtests.

    All fields will be identical except for tests. If this MultiTest is atomic,
    then this method returns |self|.

    Used interally by expect_tests, you're not expected to call this yourself.
    """
    if self.atomic:
      return self
    assert all(t in self.tests for t in tests)
    return self._replace(tests=tests)

  def process(self, func=lambda test: test.run()):
    """Applies |func| to each sub-test, with properly bound context.

    make_ctx_call will be called before any test, and its return value becomes
    bound to the name 'context'. All sub-tests will be bound with this value
    as well as destroy_ctx_call, which will be invoked after all tests have
    been yielded.

    Optionally, you may specify a different function to apply to each test
    (by default it is `lambda test: test.run()`). The context will be bound
    to the test before your function recieves it.

    Used interally by expect_tests, you're not expected to call this yourself.
    """
    # TODO(iannucci): pass list of test names?
    ctx_object = self.make_ctx_call()
    try:
      for test in self.tests:
        yield test, func(test.bind(context=ctx_object))
    finally:
      self.destroy_ctx_call.bind(context=ctx_object)()

  @staticmethod
  def expect_path(_ext=None):
    return None


class Handler(object):
  """Handler object.

  Defines 3 handler methods for each stage of the test pipeline. The pipeline
  looks like:

                         ->           ->
                         ->    jobs   ->                   (main)
  GenStage -> test_queue ->      *    -> result_queue -> ResultStage
                         ->  RunStage ->
                         ->           ->

  Each process will have an instance of one of the nested handler classes, which
  will be called on each test / result.

  You can skip the RunStage phase by setting SKIP_RUNLOOP to True on your
  implementation class.

  Tips:
    * Only do printing in ResultStage, since it's running on the main process.
  """
  SKIP_RUNLOOP = False

  @classmethod
  def add_options(cls, parser):
    """
    @type parser: argparse.ArgumentParser()
    """
    pass

  @classmethod
  def gen_stage_loop(cls, _opts, tests, put_next_stage, _put_result_stage):
    """Called in the GenStage portion of the pipeline.

    @param opts: Parsed CLI options
    @param tests:
        Iteraterable of type_definitions.Test or type_definitions.MultiTest
        objects.
    @param put_next_stage:
        Function to push an object to the next stage of the pipeline (RunStage).
        Note that you should push the item you got from |tests|, not the
        subtests, in the case that the item is a MultiTest.
    @param put_result_stage:
        Function to push an object to the result stage of the pipeline.
    """
    for test in tests:
      put_next_stage(test)

  @classmethod
  def run_stage_loop(cls, _opts, tests_results, put_next_stage):
    """Called in the RunStage portion of the pipeline.

    @param opts: Parsed CLI options
    @param tests_results: Iteraterable of (type_definitions.Test,
                          type_definitions.Result) objects
    @param put_next_stage: Function to push an object to the next stage of the
                           pipeline (ResultStage).
    """
    for _, result in tests_results:
      put_next_stage(result)

  @classmethod
  def result_stage_loop(cls, opts, objects):
    """Called in the ResultStage portion of the pipeline.

    Consider subclassing ResultStageHandler instead as it provides a more
    flexible interface for dealing with |objects|.

    @param opts: Parsed CLI options
    @param objects: Iteraterable of objects from GenStage and RunStage.
    """
    error = False
    aborted = False
    handler = cls.ResultStageHandler(opts)
    try:
      for obj in objects:
        error |= isinstance(handler(obj), Failure)
    except ResultStageAbort:
      aborted = True
    handler.finalize(aborted)
    return error

  class ResultStageHandler(object):
    """SAX-like event handler dispatches to self.handle_{type(obj).__name__}

    So if |obj| is a Test, this would call self.handle_Test(obj).

    self.__unknown is called to handle objects which have no defined handler.

    self.finalize is called after all objects are processed.
    """
    def __init__(self, opts):
      self.opts = opts

    def __call__(self, obj):
      """Called to handle each object in the ResultStage

      @type obj: Anything passed to put_result in GenStage or RunStage.

      @return: If the handler method returns Failure(), then it will
               cause the entire test run to ultimately return an error code.
      """
      return getattr(self, 'handle_' + type(obj).__name__, self.__unknown)(obj)

    def handle_NoMatchingTestsError(self, _error):
      print 'No tests found that match the glob: %s' % (
          ' '.join(self.opts.test_glob),)
      return Failure()

    def __unknown(self, obj):
      if self.opts.verbose:
        print 'UNHANDLED:', obj
      return Failure()

    def finalize(self, aborted):
      """Called after __call__() has been called for all results.

      @param aborted: True if the user aborted the run.
      @type aborted: bool
      """
      pass
