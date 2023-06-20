# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Provides utility functions for the engine to enable remote python debuggers."""

import os
import sys
import pdb
import typing

_DEBUGGER_ENVVAR = 'RECIPE_DEBUGGER'
_DEBUG_ALL_ENVVAR = 'RECIPE_DEBUG_ALL'

_PDB = None

PROTOCOL = None
IMPLICIT_BREAKPOINTS = False


def should_set_implicit_breakpoints():
  """Returns True if the engine should set implicit breakpoints.

  This only applies to the 'debug' command when using PDB.
  """
  return _PDB is not None and IMPLICIT_BREAKPOINTS


def set_implicit_pdb_breakpoint(filename, lineno, funcname=None):
  """
  Sets an implicit breakpoint with pdb, if pdb debugging and implicit
  breakpoints are enabled.
  """
  if not should_set_implicit_breakpoints():
    return

  _PDB.set_break(_PDB.canonic(filename), lineno, funcname=funcname)


def parse_remote_debugger() -> \
  typing.Union[typing.Tuple[str, str, int], typing.Tuple[None, None, None]]:
  """Parses the RECIPE_DEBUGGER environment variable.

  This will also return (None, None, None) if sys.argv doesn't include `debug`.

  If the RECIPE_DEBUGGER envvar is set, expects it to look like:

     protocol[://host[:port]]

  If host is absent, it defaults to 'localhost'.
  If port is absent, it defaults to 5678.

  `protocol` must be one of 'vscode', 'pycharm' or 'pdb'.

  If RECIPE_DEBUGGER is set, and malformed, this prints a message to stderr and
  exits the process.
  """
  is_debug_command = 'debug' in sys.argv
  if is_debug_command:
    global IMPLICIT_BREAKPOINTS  # pylint: disable=global-statement
    IMPLICIT_BREAKPOINTS = True
  all_commands = os.environ.get(_DEBUG_ALL_ENVVAR, '') == '1'
  if not all_commands and not is_debug_command:
    return None, None, None

  debugger = os.environ.get(_DEBUGGER_ENVVAR, None)
  if is_debug_command and debugger is None:
    # debug command defaults to pdb
    debugger = 'pdb'
  elif debugger is None:
    # debugger is disabled
    return None, None, None

  proto_data = debugger.split('://', 1)
  if len(proto_data) == 1:
    # Treat this as the RECIPE_DEBUGGER=protocol case.
    proto_data.append('')
  elif len(proto_data) != 2:
    sys.exit(
        f'${_DEBUGGER_ENVVAR} must be protocol[://host[:port]] - got {debugger!r}'
    )

  protocol = proto_data[0]
  if protocol not in {'vscode', 'pycharm', 'pdb'}:
    sys.exit('$RECIPE_DEBUGGER scheme not valid '
             f'(must be in {{pycharm, vscode, pdb}}) - got {protocol!r}')

  host = 'localhost'
  port = 5678
  if proto_data[1]:
    host_port = proto_data[1].split(':', 1)
    if len(host_port) == 1:
      host = host_port[0] if host_port[0] else 'localhost'
      port = 5678
    elif len(host_port) == 2:
      host = host_port[0] if host_port[0] else 'localhost'
      try:
        port = int(host_port[1])
      except ValueError:
        sys.exit(f'$RECIPE_DEBUGGER port not valid int - got {port!r}')

  return protocol, host, port


def engage_debugger():
  """Connects to a remote debugger, if one is configured in the environment.

  If the RECIPE_DEBUGGER envvar is set, expects it to look like:

     protocol[://host[:port]]

  If host is absent, it defaults to 'localhost'.
  If port is absent, it defaults to 5678.

  `protocol` must be one of 'vscode', 'pycharm', or 'pdb'.
  For 'pdb', host and port are ignored.

  If in_debug_command is set, and the environment didn't define a debugger,
  this will enable `pdb`. If in_debug_command is NOT set, and $RECIPE_DEBUG_ALL
  was not set to "1", this skips enabling the debugger.
  """
  protocol, host, port = parse_remote_debugger()
  if protocol is None:
    return

  os.environ.pop(_DEBUGGER_ENVVAR, None)
  os.environ.pop(_DEBUG_ALL_ENVVAR, None)

  global PROTOCOL  # pylint: disable=global-statement
  PROTOCOL = protocol

  if protocol == 'pdb':
    global _PDB  # pylint: disable=global-statement
    debugger = pdb.Pdb()

    def dispatch_thunk(frame, event, arg):
      """Triggers 'continue' command when debugger starts."""
      debugger.trace_dispatch(frame, event, arg)
      debugger.set_continue()
      sys.settrace(debugger.trace_dispatch)

    debugger.reset()
    sys.settrace(dispatch_thunk)
    _PDB = debugger
    return

  print(
      f'Waiting to connect to {protocol}://{host}:{port}... ',
      file=sys.stderr,
      end='')
  sys.stderr.flush()

  # pylint: disable=import-error, import-outside-toplevel
  if protocol == 'pycharm':
    import pydevd
    pydevd.settrace(
        host=host,
        port=port,
        stdoutToServer=True,
        stderrToServer=True,
        suspend=False,  # we will use `breakpoint` later.
    )
    print('OK', file=sys.stderr)
    return

  if protocol == 'vscode':
    import debugpy
    debugpy.listen((host, port))
    debugpy.wait_for_client()
    print('OK', file=sys.stderr)
    return

  sys.exit(f'BUG: $RECIPE_DEBUGGER scheme not valid: {protocol}')
