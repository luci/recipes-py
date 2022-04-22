# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides methods for running python scripts correctly.

This includes support for `vpython`, and knows how to specify parameters
correctly for bots (e.g. ensuring that python is working on Windows, passing the
unbuffered flag, etc.)
"""

import textwrap

from builtins import str as text_type

from recipe_engine import config_types
from recipe_engine import recipe_api

class PythonApi(recipe_api.RecipeApi):  # pragma: no cover
  """DEPRECATED: Directly invoke python instead of using this module.
  """

  def __call__(self, name, script, args=None, unbuffered=True, venv=None,
               **kwargs):
    """Return a step to run a python script with arguments.

    **TODO**: We should just use a single "args" list. Having "script"
    separate but required/first leads to weird things like:

        (... script='-m', args=['module'])

    Args:
      * name (str): The name of the step.
      * script (str or Path): The Path of the script to run, or the first
          command-line argument to pass to Python.
      * args (list or None): If not None, additional arguments to pass to the
          Python command.
      * unbuffered (bool): If True, run Python in unbuffered mode.
      * venv (None or False or True or Path): If True, run the script through
          "vpython". This will, by default, probe the target script for a
          configured VirtualEnv and, failing that, use an empty VirtualEnv. If a
          Path, this is a path to an explicit "vpython" VirtualEnv spec file to
          use. If False or None (default), the script will be run through the
          standard Python interpreter.
      * kwargs: Additional keyword arguments to forward to "step".

    **Returns (`step_data.StepData`)** - The StepData object as returned by
    api.step.
    """
    env = {}

    if venv:
      cmd = ['vpython']
      if isinstance(venv, config_types.Path):
        cmd += ['-vpython-spec', venv]
    else:
      cmd = ['python']

    if unbuffered:
      cmd.append('-u')
    else:
      env['PYTHONUNBUFFERED'] = None

    cmd.append(script)
    with self.m.context(env=env):
      return self.m.step(name, cmd + list(args or []), **kwargs)

  def inline(self, name, program, add_python_log=True, **kwargs):
    """Run an inline python program as a step.

    Program is output to a temp file and run when this step executes.

    Args:
      * name (str) - The name of the step
      * program (str) - The literal python program text. This will be dumped to
        a file and run like `python /path/to/file.py`
      * add_python_log (bool) - Whether to add a 'python.inline' link on this
        step on the build page. If true, the link will point to a log with
        a copy of `program`.

    **Returns (`step_data.StepData`)** - The StepData object as returned by
    api.step.
    """
    self.m.warning.issue("PYTHON_INLINE_DEPRECATED")

    program = textwrap.dedent(program)
    compile(program, '<string>', 'exec', dont_inherit=1)

    try:
      raw = (
        program.encode('utf-8') if isinstance(program, text_type) else program
      )
      self(name, self.m.raw_io.input(raw, '.py'), **kwargs)
    finally:
      result = self.m.step.active_result
      if result and add_python_log:
        result.presentation.logs['python.inline'] = program.splitlines()

    return result

  def result_step(
      self, name, text, retcode, as_log=None, **kwargs): # pragma: no cover
    """Runs a no-op step that exits with a specified return code.

    DEPRECATED: crbug.com/1276131

    The recipe engine will raise an exception when seeing a return code != 0.

    The text is expected to be str. Passing a list of lines(str) works but is
    discouraged and may be deprecated in the future. Please concatenate the
    lines with newline character instead.
    """
    self.m.warning.issue("PYTHON_RESULT_STEP_DEPRECATED")
    try:
      return self.inline(
          name,
          'import sys; sys.exit(%d)' % (retcode,),
          add_python_log=False,
          step_test_data=lambda: self.m.raw_io.test_api.output(
              '\n'.join(text) if isinstance(text, list) else text,
              retcode=retcode),
          **kwargs)
    finally:
      if as_log:
        self.m.step.active_result.presentation.logs[as_log] = text
      else:
        self.m.step.active_result.presentation.step_text = text

  @recipe_api.ignore_warnings("recipe_engine/PYTHON_RESULT_STEP_DEPRECATED")
  def succeeding_step(self, name, text, as_log=None): # pragma: no cover
    """Runs a succeeding step (exits 0).

    DEPRECATED: crbug.com/1276131
    """
    self.m.warning.issue(
        "PYTHON_SUCCEEDING_STEP_DEPRECATED" + ("_LOG" if as_log else ""))
    return self.result_step(name, text, 0, as_log=as_log)

  @recipe_api.ignore_warnings("recipe_engine/PYTHON_RESULT_STEP_DEPRECATED")
  def failing_step(self, name, text, as_log=None): # pragma: no cover
    """Runs a failing step (exits 1).

    DEPRECATED: crbug.com/1276131
    """
    self.m.warning.issue(
        "PYTHON_FAILING_STEP_DEPRECATED" + ("_LOG" if as_log else ""))
    return self.result_step(name, text, 1, as_log=as_log)

  @recipe_api.ignore_warnings("recipe_engine/PYTHON_RESULT_STEP_DEPRECATED")
  def infra_failing_step(self, name, text, as_log=None): # pragma: no cover
    """Runs an infra-failing step (exits 1).

    DEPRECATED: crbug.com/1276131
    """
    self.m.warning.issue(
        "PYTHON_INFRA_FAILING_STEP_DEPRECATED" + ("_LOG" if as_log else ""))
    return self.result_step(name, text, 1, as_log=as_log, infra_step=True)
