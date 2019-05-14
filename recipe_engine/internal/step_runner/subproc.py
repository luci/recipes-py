# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import itertools
import os
import sys
import time

from cStringIO import StringIO

from ...step_data import ExecutionResult
from ...third_party import subprocess42

from . import StepRunner


if sys.platform == "win32":
  # subprocess.Popen(close_fds) raises an exception when attempting to do this
  # and also redirect stdin/stdout/stderr. To be on the safe side, we just don't
  # do this on windows.
  CLOSE_FDS = False

  # Windows has a bad habit of opening a dialog when a console program
  # crashes, rather than just letting it crash.  Therefore, when a
  # program crashes on Windows, we don't find out until the build step
  # times out.  This code prevents the dialog from appearing, so that we
  # find out immediately and don't waste time waiting for a user to
  # close the dialog.
  import ctypes
  # SetErrorMode(
  #   SEM_FAILCRITICALERRORS|
  #   SEM_NOGPFAULTERRORBOX|
  #   SEM_NOOPENFILEERRORBOX
  # ).
  #
  # For more information, see:
  # https://msdn.microsoft.com/en-us/library/windows/desktop/ms680621.aspx
  ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002|0x8000)
else:
  # Non-windows platforms implement close_fds in a safe way.
  CLOSE_FDS = True


class _streamingLinebuf(object):
  def __init__(self):
    self.buffedlines = []
    self.extra = StringIO()

  def ingest(self, data):
    lines = data.splitlines()
    ended_on_linebreak = data.endswith("\n")

    if self.extra.tell():
      # we had leftovers from some previous ingest
      self.extra.write(lines[0])
      if len(lines) > 1 or ended_on_linebreak:
        lines[0] = self.extra.getvalue()
        self.extra = StringIO()
      else:
        return

    if not ended_on_linebreak:
      self.extra.write(lines[-1])
      lines = lines[:-1]

    self.buffedlines += lines

  def get_buffered(self):
    ret = self.buffedlines
    self.buffedlines = []
    return ret


class SubprocessStepRunner(StepRunner):
  """Responsible for actually running steps as subprocesses, filtering their
  output into a stream."""

  def isabs(self, _name_tokens, path):
    return os.path.isabs(path)

  def isdir(self, _name_tokens, path):
    return os.path.isdir(path)

  def access(self, _name_tokens, path, mode):
    return os.access(path, mode)

  _PATH_EXTS = ('.exe', '.bat') if sys.platform == "win32" else ('',)
  def resolve_cmd0(self, name_tokens, debug_log, cmd0, cwd, paths):
    """Transforms `cmd0` into an absolute path to the resolved executable, as if
    we had used `shell=True` in the current `env` and `cwd`.

    If this fails to resolve cmd0, this will return None.

    Windows:

    On windows, if cmd0 does not have an extension, this takes the lazy
    cross-product of PATH and ('.exe', '.bat') to find what cmd.exe would have
    found for the command.

    This DOES NOT use $PATHEXT to keep the recipe engine's behavior as
    predictable as possible. We don't currently rely on any other runnable
    extensions besides these two, and when we could, we choose to explicitly
    invoke the interpreter (e.g. python.exe, cscript.exe, etc.).
    """
    del name_tokens
    if os.path.isabs(cmd0):
      debug_log.write_line('cmd0 appears to already be absolute')
      if not os.access(cmd0, os.X_OK):
        debug_log.write_line('current user has no execute permission!')
        return None
      return cmd0

    # If cmd0 has a path separator, treat it as relative to CWD.
    if os.path.sep in cmd0:
      candidate = os.path.join(cwd, cmd0)
      if not os.access(candidate, os.X_OK):
        debug_log.write_line(
            'cmd0 was relative to cwd but does not have executable permission.'
        )
        return None
      return candidate

    # Otherwise find it in $PATH.
    # If it already has an extension don't propose new extensions for it.
    exts = self._PATH_EXTS if '.' not in os.path.basename(cmd0) else ('',)

    # Look along each path+ext combination until we find an executable match.
    for path, ext in itertools.product(paths, exts):
      candidate = os.path.join(path, cmd0+ext)
      if os.access(candidate, os.X_OK):
        return candidate

    return None

  def run(self, _name_tokens, debug_log, step):
    fhandles = {
      'stdin': open(step.stdin, 'rb') if step.stdin else None,
      'stdout': _fd_for_out(step.stdout),
      'stderr': _fd_for_out(step.stderr),
    }
    debug_log.write_line('fhandles %r' % fhandles)

    # Necessary because subprocess.Popen uses os.environ to perform lookup on
    # the supplied command, and only uses the |env| kwarg for modifying the
    # environment of the child process.
    orig_path = os.environ['PATH']
    try:
      if 'PATH' in step.env:
        os.environ['PATH'] = step.env['PATH']
      proc = subprocess42.Popen(
          step.cmd,
          env=step.env,
          cwd=step.cwd,
          detached=True,
          universal_newlines=True,
          close_fds=CLOSE_FDS,
          **fhandles)
    finally:
      os.environ['PATH'] = orig_path

    # Safe to close file handles now that subprocess has inherited them.
    for handle in fhandles.itervalues():
      if hasattr(handle, 'close'):
        handle.close()

    outstreams = {}
    linebufs = {}

    for handle_name in ('stdout', 'stderr'):
      if fhandles[handle_name] == subprocess42.PIPE:
        outstreams[handle_name] = getattr(step, handle_name)
        linebufs[handle_name] = _streamingLinebuf()

    try:
      if linebufs:
        _stream_outputs(proc, step.timeout, outstreams, linebufs)
      else:
        proc.wait(step.timeout)
    except subprocess42.TimeoutExpired:
      return ExecutionResult(has_timeout=True)

    return ExecutionResult(retcode=proc.returncode)


def _stream_outputs(proc, timeout, outstreams, linebufs):
  # manually check the timeout, because we poll
  start_time = time.time()
  for handle_name, data in proc.yield_any(timeout=1):
    if timeout and time.time() - start_time > timeout:
      proc.kill()   # best-effort nuke
      raise subprocess42.TimeoutExpired((), 0)

    if handle_name is None:
      continue
    buf = linebufs.get(handle_name)
    if not buf:
      continue
    buf.ingest(data)
    for line in buf.get_buffered():
      outstreams[handle_name].write_line(line)


# It's either a file-like object, a string or it's a Stream (so we need to
# return PIPE)
def _fd_for_out(raw_val):
  if hasattr(raw_val, 'fileno'):
    return raw_val.fileno()
  if isinstance(raw_val, str):
    return open(raw_val, 'wb')
  return subprocess42.PIPE
