# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import textwrap

from recipe_engine import config_types
from recipe_engine import recipe_api

class PythonApi(recipe_api.RecipeApi):
  def __call__(self, name, script, args=None, unbuffered=True, venv=None,
               **kwargs):
    """Return a step to run a python script with arguments.

    TODO: We should just use a single "args" list. Having "script"
    separate but required/first leads to weird things like:
        (... script='-m', args=['module'])

    Args:
      name (str): The name of the step.
      script (str or Path): The Path of the script to run, or the first
          command-line argument to pass to Python.
      args (list or None): If not None, additional arguments to pass to the
          Python command.
      unbuffered (bool): If True, run Python in unbuffered mode.
      venv (None or False or True or Path): If True, run the script through
          "vpython". This will, by default, probe the target script for a
          configured VirtualEnv and, failing that, use an empty VirtualEnv. If a
          Path, this is a path to an explicit "vpython" VirtualEnv spec file to
          use. If False or None (default), the script will be run through the
          standard Python interpreter.
      kwargs: Additional keyword arguments to forward to "step".
    """
    env = {}

    if venv:
      cmd = ['vpython']
      if isinstance(venv, config_types.Path):
        cmd += ['-spec', venv]
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
    """
    program = textwrap.dedent(program)
    compile(program, '<string>', 'exec', dont_inherit=1)

    try:
      self(name, self.m.raw_io.input(program, '.py'), **kwargs)
    finally:
      result = self.m.step.active_result
      if result and add_python_log:
        result.presentation.logs['python.inline'] = program.splitlines()

    return result

  def result_step(self, name, text, retcode, as_log=None):
    """Return a no-op step that exits with a specified return code."""
    try:
      return self.inline(
          name,
          'import sys; sys.exit(%d)' % (retcode,),
          add_python_log=False,
          step_test_data=lambda: self.m.raw_io.test_api.output(
              text, retcode=retcode))
    finally:
      if as_log:
        self.m.step.active_result.presentation.logs[as_log] = text
      else:
        self.m.step.active_result.presentation.step_text = text

  def succeeding_step(self, name, text, as_log=None):
    """Return a succeeding step (correctly recognized in expectations)."""
    return self.result_step(name, text, 0, as_log=as_log)

  def failing_step(self, name, text, as_log=None):
    """Return a failing step (correctly recognized in expectations)."""
    return self.result_step(name, text, 1, as_log=as_log)
