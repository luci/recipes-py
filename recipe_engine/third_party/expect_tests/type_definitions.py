# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from collections import namedtuple

UnknownError = namedtuple('UnknownError', 'message')
TestError = namedtuple('TestError', 'test message')
Result = namedtuple('Result', 'data')

class ResultStageAbort(Exception):
  pass


class Failure(object):
  pass


_Test = namedtuple(
    'Test', 'name func args kwargs expect_dir expect_base ext breakpoints')

class Test(_Test):  # pylint: disable=W0232
  def __new__(cls, name, func, args=(), kwargs=None, expect_dir=None,
              expect_base=None, ext='json', breakpoints=None, break_funcs=()):
    """Create a new test.

    @param name: The name of the test. Will be used as the default expect_base

    @param func: The function to execute to run this test. Must be pickleable.
    @param args: *args for |func|
    @param kwargs: **kwargs for |func|

    @param expect_dir: The directory which holds the expectation file for this
                       Test.
    @param expect_base: The basename (without extension) of the expectation
                        file. Defaults to |name|.
    @param ext: The extension of the expectation file. Affects the serializer
                used to write the expectations to disk. Valid values are
                'json' and 'yaml' (Keys in SERIALIZERS).

    @param breakpoints: A list of (path, lineno, func_name) tuples. These will
                        turn into breakpoints when the tests are run in 'debug'
                        mode. See |break_funcs| for an easier way to set this.
    @param break_funcs: A list of functions for which to set breakpoints.
    """
    # pylint: disable=E1002
    kwargs = kwargs or {}

    breakpoints = breakpoints or []
    if not breakpoints or break_funcs:
      for f in (break_funcs or (func,)):
        if hasattr(f, 'im_func'):
          f = f.im_func
        breakpoints.append((f.func_code.co_filename,
                            f.func_code.co_firstlineno,
                            f.func_code.co_name))

    return super(Test, cls).__new__(cls, name, func, args, kwargs, expect_dir,
                                    expect_base, ext, breakpoints)

  def expect_path(self, ext=None):
    name = self.expect_base or self.name
    name = ''.join('_' if c in '<>:"\\/|?*\0' else c for c in name)
    return os.path.join(self.expect_dir, name + ('.%s' % (ext or self.ext)))

  def run(self):
    return self.func(*self.args, **self.kwargs)


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
    @param tests: Iteraterable of type_definitions.Test objects
    @param put_next_stage: Function to push an object to the next stage of the
                           pipeline (RunStage).
    @param put_result_stage: Function to push an object to the result stage of
                             the pipeline.
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
