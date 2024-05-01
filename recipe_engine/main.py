#!/usr/bin/env vpython3
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tool to interact with recipe repositories.

This tool operates on the nearest ancestor directory containing an
infra/config/recipes.cfg.
"""

import sys
import errno
import os
import time

# Hack 1; crbug.com/980535
#
# On OS X there seems to be an issue with subprocess's use of its error
# pipe which causes os.read to raise EINVAL (but very infrequently).
#
# It turns out that merely retrying this read operation with exactly the same
# parameters works... go figure.
if sys.platform == 'darwin':
  _REAL_OS_READ = os.read
  def _hacked_read(fileno, bufsiz):
    tries = 3
    while True:
      try:
        return _REAL_OS_READ(fileno, bufsiz)
      except OSError as ex:
        if ex.errno == errno.EINVAL and tries > 0:
          tries -= 1
          time.sleep(0.1)
          continue
        raise
  os.read = _hacked_read

# Hack 2; Bump the recursion limit as well; because of step nesting and gevent
# overhead, we can sometimes exceed the default.
sys.setrecursionlimit(sys.getrecursionlimit() * 2)

# Hack 3; Lookup all available codecs (crbug.com/932259).
# TODO(crbug.com/1147793): try to remove this in python3.
def _hack_lookup_codecs():
  import encodings
  import pkgutil
  import codecs
  for _, name, _ in pkgutil.iter_modules(encodings.__path__):
    if name in ('aliases', 'mbcs'):
      continue
    if name == 'oem':
      continue
    codecs.lookup(name)
_hack_lookup_codecs()
del _hack_lookup_codecs

try:
  import urllib3.contrib.pyopenssl
  urllib3.contrib.pyopenssl.inject_into_urllib3()
except ImportError:
  pass

from recipe_engine.internal import debugger

debugger.engage_debugger()
if debugger.PROTOCOL == 'pdb' and not debugger.IMPLICIT_BREAKPOINTS:
  breakpoint()  # pylint: disable=forgotten-debug-statement
  # NOTE for the NOTE: `pdb` by default gives 4 lines of context when doing `l`,
  # so try to keep the following comment to 4 lines or less.

  # NOTE: pdb debugging for a non-`recipes.py debug` command breaks extremely
  # early in the recipe engine. Manually add any additional breakpoints.
  # It is recommended to use a remote debugger (see doc/user_guide.md).

from recipe_engine.internal.commands import parse_and_run


def _strip_virtualenv():
  # Prune all evidence of VPython/VirtualEnv out of the environment. This means
  # that recipe engine 'unwraps' vpython VirtualEnv path/env manipulation.
  # Invocations of `python` from recipes should never inherit the recipe
  # engine's own VirtualEnv.

  # Set by VirtualEnv, no need to keep it.
  os.environ.pop('VIRTUAL_ENV', None)

  # Set by VPython, if recipes want it back they have to set it explicitly.
  os.environ.pop('PYTHONNOUSERSITE', None)

  # Look for "activate_this.py" in this path, which is installed by VirtualEnv.
  # This mechanism is used by vpython as well to sanitize VirtualEnvs from
  # $PATH.
  os.environ['PATH'] = os.pathsep.join([
    p for p in os.environ.get('PATH', '').split(os.pathsep)
    if not os.path.isfile(os.path.join(p, 'activate_this.py'))
  ])


def _main():
  # Use os._exit instead of sys.exit to prevent the python interpreter from
  # hanging on threads/processes which may have been spawned and not reaped
  # (e.g. by a leaky test harness).
  os_exit = os._exit  # pylint: disable=protected-access
  if 'RECIPES_DEBUG_SLEEP' in os.environ:
    sleep_duration = float(os.environ.pop('RECIPES_DEBUG_SLEEP'))
    sys.stderr.write(
        '[engine will sleep for %f seconds after execution]\n' % sleep_duration)
    def exit_fn(code):
      sys.stderr.write(
          '[engine sleeping for %f seconds]\n' % sleep_duration)
      time.sleep(sleep_duration)
      os_exit(code)
  else:
    exit_fn = os_exit

  _strip_virtualenv()

  # TODO(crbug.com/1147793): clear this code after py3 migration is done.
  # Unset it to prevent the leak through recipe subcommand, e.g if a recipe runs
  # `led edit-recipe-bundle` which will run `recipes.py bundle`, the env var
  # should explicitly be set in that recipe.
  if 'RECIPES_USE_PY3' in os.environ:
    os.environ.pop('RECIPES_USE_PY3')

  try:
    ret = parse_and_run()
  except Exception as exc:  # pylint: disable=broad-except
    import traceback
    traceback.print_exc(file=sys.stderr)
    print('Uncaught exception (%s): %s' % (
      type(exc).__name__, exc), file=sys.stderr)
    exit_fn(1)
  except SystemExit as exc:
    # funnel all 'exit' methods through flush&&os._exit
    ret = exc.code

  if not isinstance(ret, int):
    if ret is None:
      ret = 0
    else:
      print('Bogus retcode %r' % (ret,), file=sys.stderr)
      ret = 1
  sys.stdout.flush()
  sys.stderr.flush()
  exit_fn(ret)


if __name__ == '__main__':
  _main()
