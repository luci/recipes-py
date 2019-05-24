#!/usr/bin/env vpython
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tool to interact with recipe repositories.

This tool operates on the nearest ancestor directory containing an
infra/config/recipes.cfg.
"""

# Hacks!

# Hack 0 (sorta); gevent.monkey patch the world before any other code runs.
import gevent.monkey
gevent.monkey.patch_all()

# Hack 1; Change default encoding.
# This is necessary to ensure that str literals are by-default assumed to hold
# utf-8. It also makes the implicit str(unicode(...)) act like
# unicode(...).encode('utf-8'), rather than unicode(...).encode('ascii') .
import sys
reload(sys)
sys.setdefaultencoding('UTF8')

# Hack 2; Lookup all available codecs (crbug.com/932259).
def _hack_lookup_codecs():
  import encodings
  import pkgutil
  import codecs
  for _, name, _ in pkgutil.iter_modules(encodings.__path__):
    if name in ('aliases', 'mbcs'):
      continue
    codecs.lookup(name)
_hack_lookup_codecs()
del _hack_lookup_codecs

# pylint: disable=wrong-import-position
import os

import urllib3.contrib.pyopenssl
urllib3.contrib.pyopenssl.inject_into_urllib3()

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

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
  exit_fn = os._exit  # pylint: disable=protected-access

  _strip_virtualenv()

  try:
    ret = parse_and_run()
  except Exception as exc:  # pylint: disable=broad-except
    import traceback
    traceback.print_exc(file=sys.stderr)
    print >> sys.stderr, 'Uncaught exception (%s): %s' % (
      type(exc).__name__, exc)
    exit_fn(1)

  if not isinstance(ret, int):
    if ret is None:
      ret = 0
    else:
      print >> sys.stderr, ret
      ret = 1
  sys.stdout.flush()
  sys.stderr.flush()
  exit_fn(ret)


if __name__ == '__main__':
  _main()
