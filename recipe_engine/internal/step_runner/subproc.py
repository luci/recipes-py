# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import itertools
import os
import sys
import signal

import gevent
from gevent import subprocess

from ...step_data import ExecutionResult

from . import StepRunner


if subprocess.mswindows:
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
  # gevent.subprocess has special import logic. This symbol is definitely there
  # on windows.
  # pylint: disable=no-member
  EXTRA_KWARGS = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
else:
  # Non-windows platforms implement close_fds in a safe way.
  CLOSE_FDS = True
  EXTRA_KWARGS = {'preexec_fn': lambda: os.setpgid(0, 0)}


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
  @classmethod
  def _resolve_base_path(cls, debug_log, base_path):
    """Checks for existance/permission for a potential executable at
    `base_path`.

    If `base_path` contains an extension (e.g. '.bat'), then it will be checked
    for existance+execute permission without modification.

    If `base_path` doesn't contain an extension, the platform-specific
    extensions (_PATH_EXTS) will be tried in order.

    If base_path, or a modification of it, is accessible, the resolved path will
    be returned. Otherwise this returns None.

    Args:

      * debug_log (Stream)
      * base_path (str) - Absolute base path to check.

    Returns base_path or base_path+ext if an existing executable candidate was
    found, None otherwise.
    """
    if os.path.splitext(base_path)[1]:
      debug_log.write_line('path has extension')
      if not os.access(base_path, os.X_OK):
        debug_log.write_line(
            'file does not exist or user has no execute permission')
        return None
      return base_path

    for ext in cls._PATH_EXTS:
      candidate = base_path + ext
      debug_log.write_line('checking %r' % (candidate,))
      if os.access(candidate, os.X_OK):
        return candidate

    return None

  def resolve_cmd0(self, name_tokens, debug_log, cmd0, cwd, paths):
    """Transforms `cmd0` into an absolute path to the resolved executable, as if
    we had used `shell=True` in the current `env` and `cwd`.

    If this fails to resolve cmd0, this will return None.

    Rules:
      * If
        - cmd0 is absolute, PATH and CWD are not used.
        - cmd0 contains os.path.sep, it's treated as relative to CWD.
        - otherwise, cmd0 is tried within each component of PATH.
      * If cmd0 lacks an extension (i.e. ".exe"), the platform appropriate
        extensions will be tried (_PATH_EXTS). On windows this is
        ['.exe', '.bat']. On non-windows this is just [''] (empty string).
      * The candidate is checked for 'access' with the +x permission for the
        current user (using `os.access`).
      * The first candidate found is returned, or None, if no candidate matches
        all of the rules.

    NOTE (windows):
    This DOES NOT use $PATHEXT, in order to keep the recipe engine's behavior as
    predictable as possible. We don't currently rely on any other runnable
    extensions besides exe/bat, and when we could, we choose to explicitly
    invoke the interpreter (e.g. python.exe, cscript.exe, etc.).
    """
    del name_tokens
    if os.path.isabs(cmd0):
      debug_log.write_line('cmd0 appears to be absolute')
      return self._resolve_base_path(debug_log, cmd0)

    # If cmd0 has a path separator, treat it as relative to CWD.
    if os.path.sep in cmd0:
      debug_log.write_line('cmd0 appears to be relative to cwd')
      return self._resolve_base_path(debug_log, os.path.join(cwd, cmd0))

    debug_log.write_line('looking in PATH')
    for path in paths:
      candidate = self._resolve_base_path(debug_log, os.path.join(path, cmd0))
      if candidate:
        return candidate

    return None

  def run(self, name_tokens, debug_log, step):
    fhandles = {
      'stdin': open(step.stdin, 'rb') if step.stdin else None,
      'stdout': _fd_for_out(step.stdout),
      'stderr': _fd_for_out(step.stderr),
    }
    debug_log.write_line('fhandles %r' % fhandles)
    extra_kwargs = fhandles.copy()
    extra_kwargs.update(EXTRA_KWARGS)

    # Necessary because subprocess.Popen uses os.environ to perform lookup on
    # the supplied command, and only uses the |env| kwarg for modifying the
    # environment of the child process.
    orig_path = os.environ['PATH']
    try:
      if 'PATH' in step.env:
        os.environ['PATH'] = step.env['PATH']
      proc = subprocess.Popen(
          step.cmd,
          env=step.env,
          cwd=step.cwd,
          universal_newlines=True,
          close_fds=CLOSE_FDS,
          **extra_kwargs)
    finally:
      os.environ['PATH'] = orig_path

    # Lifted from subprocess42.
    gid = None
    if not subprocess.mswindows:
      try:
        gid = os.getpgid(proc.pid)
      except OSError:
        # sometimes the process can run+finish before we collect its pgid. fun.
        pass

    workers = []
    to_close = []
    for handle_name, handle in fhandles.iteritems():
      # Safe to close file handles now that subprocess has inherited them.
      if hasattr(handle, 'close'):
        handle.close()

      # Only want to set up copy workers for these two.
      if handle_name not in ('stdout', 'stderr'):
        continue

      if fhandles[handle_name] == subprocess.PIPE:
        proc_handle = getattr(proc, handle_name)
        to_close.append(proc_handle)
        workers.append(gevent.spawn(
            _copy_lines, proc_handle, getattr(step, handle_name),
        ))

    proc.wait(step.timeout)
    retcode = proc.poll()

    # TODO(iannucci): Make leaking subprocesses explicit (e.g. goma compiler
    # daemon). Better, change deamons to be owned by a gevent Greenlet (so that
    # we don't need to leak processes ever).
    #
    # _kill(proc, gid)  # In case of leaked subprocesses or timeout.
    if retcode is None:
      # Process timed out, kill it. Currently all uses of non-None timeout
      # intend to actually kill the subprocess when the timeout pops.
      _kill(proc, gid)
      proc.wait()
    for handle in to_close:
      try:
        handle.close()
      except RuntimeError:
        # NOTE(gevent): This can happen as a race between the worker greenlet
        # and the process ending. See gevent.subprocess.Popen.communicate, which
        # does the same thing.
        pass
    for worker in workers:
      worker.kill()
    gevent.wait(workers)

    if retcode is not None:
      return ExecutionResult(retcode=proc.returncode)

    return ExecutionResult(had_timeout=True)


def _copy_lines(handle, outstream):
  while True:
    try:
      # Because we use readline here we could, technically, lose some data in
      # the event of a timeout.
      data = handle.readline()
    except RuntimeError:
      # See NOTE(gevent) above.
      return
    if not data:
      break
    outstream.write_line(data.rstrip('\n'))


# It's either a file-like object, a string or it's a Stream (so we need to
# return PIPE)
def _fd_for_out(raw_val):
  if hasattr(raw_val, 'fileno'):
    return raw_val.fileno()
  if isinstance(raw_val, str):
    return open(raw_val, 'wb')
  return subprocess.PIPE


def _kill(proc, gid):
  """Kills the process and its children if possible.

  Swallows exceptions and return True on success.

  Lifted from subprocess42.
  """
  if gid:
    try:
      os.killpg(gid, signal.SIGKILL)
    except OSError:
      return False
  else:
    try:
      proc.kill()
    except OSError:
      return False
  return True
