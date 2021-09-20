# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import signal
import sys
import time

from future.utils import iteritems
from gevent import subprocess

import attr
import gevent

from ...step_data import ExecutionResult
from ...third_party import luci_context

from ..global_shutdown import GLOBAL_SHUTDOWN, GLOBAL_QUITQUITQUIT, MSWINDOWS
from ..global_shutdown import UNKILLED_PROC_GROUPS, GLOBAL_SOFT_DEADLINE

from . import StepRunner

_PY2 = sys.version_info.major == 2

if MSWINDOWS:
  # subprocess.Popen(close_fds) raises an exception when attempting to do this
  # and also redirect stdin/stdout/stderr. To be on the safe side, we just don't
  # do this on Windows.
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
  # on Windows.
  # pylint: disable=no-member
  EXTRA_KWARGS = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
else:
  # Non-Windows platforms implement close_fds in a safe way.
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

  @staticmethod
  def _is_executable_file(path):
    """Returns True iff `path` is:

      * A file
      * User has +x access to it
    """
    return os.path.isfile(path) and os.access(path, os.X_OK)

  _PATH_EXTS = ('.exe', '.bat') if sys.platform == "win32" else ('',)
  @classmethod
  def _resolve_base_path(cls, debug_log, base_path):
    """Checks for existence/permission for a potential executable at
    `base_path`.

    If `base_path` contains an extension (e.g. '.bat'), then it will be checked
    for existence+execute permission without modification.

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
      debug_log.write_line('path has extension; checking %r' % (base_path,))
      if not cls._is_executable_file(base_path):
        debug_log.write_line(
            '  > does not exist or user has no execute permission')
        return None
      return base_path

    for ext in cls._PATH_EXTS:
      candidate = base_path + ext
      debug_log.write_line('checking %r' % (candidate,))
      if cls._is_executable_file(candidate):
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
        extensions will be tried (_PATH_EXTS). On Windows this is
        ['.exe', '.bat']. On non-Windows this is just [''] (empty string).
      * The candidate is checked for isfile and 'access' with the +x permission
        for the current user (using `os.access`).
      * The first candidate found is returned, or None, if no candidate matches
        all of the rules.

    NOTE (Windows):
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

  def now(self):
    return time.time()

  def write_luci_context(self, section_values):
    with luci_context.stage(_leak=True, **section_values) as file_path:
      return file_path or os.environ.get(luci_context.ENV_KEY)

  def run(self, name_tokens, debug_log, step):
    proc, gid, pipes = self._mk_proc(step, debug_log)

    workers, to_close = self._mk_workers(step, proc, pipes)

    timeout = None
    grace_period = 30
    # See write_luci_context above; Sometime before `run`, `write_luci_context`
    # was called and populated soft_deadline. Now all we have to do is respect
    # that.
    if 'deadline' in step.luci_context:
      soft = step.luci_context['deadline'].soft_deadline
      if soft != GLOBAL_SOFT_DEADLINE:
        timeout = soft - time.time()
      grace_period = step.luci_context['deadline'].grace_period
    exc_result = self._wait_proc(proc, gid, timeout, grace_period, debug_log)

    self._reap_workers(workers, to_close, debug_log)

    return exc_result

  @staticmethod
  def _mk_proc(step, debug_log):
    """Makes a subprocess.Popen object from the Step.

    Args:
      * step (..step_runner.Step) - The Step object describing what we're
        supposed to run.
      * debug_log (..stream.StreamEngine.Stream)

    Returns (proc, gid, pipes):
      * proc (subprocess.Popen) - The Popen object for the running subprocess.
      * gid (int|None) - The (new) group-id of the process (POSIX only).
        TODO(iannucci): expand this from an int to a killable object to
        encapsulate JobObjects on Windows too.
      * pipes (Set[str]) - A subset of {'stdout', 'stderr'} which we need to set
        up pipe workers for.

    Should not raise an exception.
    """
    stdin = None
    if step.stdin:
      stdin = open(step.stdin, 'rb')
    else:
      # Python3 appears to set an invalid stdin where its inode number is 0
      # (see https://crbug.com/1249150#c12 for problems it causes).
      # So use DEVNULL as a workaround.
      stdin = None if _PY2 else subprocess.DEVNULL
    fhandles = {
      'stdin': stdin,
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
    if not MSWINDOWS:
      try:
        gid = os.getpgid(proc.pid)
        UNKILLED_PROC_GROUPS.add(gid)
      except OSError:
        # sometimes the process can run+finish before we collect its pgid.
        pass
    else:
      # On windows we use the actual process object to track the 'group'. If the
      # process does tricks to daemonize, this can easily leak processes.
      #
      # TODO(iannucci): Use Job Objects for process management.
      UNKILLED_PROC_GROUPS.add(proc)

    debug_log.write_line('launched pid:%r gid:%r' % (proc.pid, gid))

    pipes = set()
    for handle_name, handle in iteritems(fhandles):
      # Close all closable file handles, since the subprocess has them now.
      if hasattr(handle, 'close'):
        handle.close()
      elif handle == subprocess.PIPE:
        pipes.add(handle_name)

    return proc, gid, pipes

  @staticmethod
  def _mk_workers(step, proc, pipes):
    """Makes greenlets to shuttle lines from the process's PIPE'd std{out,err}
    handles to the recipe Step's std{out,err} handles.

    NOTE: This applies to @@@annotator@@@ runs when allow_subannotations=False;
    Step.std{out,err} will be Stream objects which don't implement `fileno()`,
    but add an '!' in front of all lines starting with '@@@'. In build.proto
    mode this code path should NOT be active at all; Placeholders will be
    redirected directly to files on disk and non-placeholders will go straight
    to butler (i.e. regular file handles).

    Args:

      * step (..step_runner.Step) - The Step object describing what we're
        supposed to run.
      * proc (subprocess.Popen) - The running subprocess.
      * pipes (Set[str]) - A subset of {'stdout', 'stderr'} to make worker
        greenlets for.

    Returns Tuple[
      workers: List[Greenlet],
      to_close: List[Tuple[
        handle_name: str,
        proc_handle: fileobj,
      ]]
    ]. Both returned values are expected to be passed directly to
    `_reap_workers` without inspection or alteration.
    """
    workers = []
    to_close = []
    for handle_name in pipes:
      proc_handle = getattr(proc, handle_name)
      to_close.append((handle_name, proc_handle))
      workers.append(gevent.spawn(
          _copy_lines, proc_handle, getattr(step, handle_name),
      ))
    return workers, to_close

  def _wait_proc(self, proc, gid, timeout, grace_period, debug_log):
    """Waits for the completion (or timeout) of `proc`.

    Args:

      * proc (subprocess.Popen) - The actual running subprocess to wait for.
      * gid (int|None) - The group ID of the process.
      * timeout (Number|None) - The number of seconds to wait for the process to
        end (or None for no timeout).
      * grace_period (Number|None) - The number of seconds to wait after SIGTERM
        before sending SIGKILL.
      * debug_log (..stream.StreamEngine.Stream)

    Returns the ExecutionResult.

    Should not raise an exception.
    """
    ret = ExecutionResult()

    # We're about to do gevent-blocking operations (waiting on the subprocess)
    # and so another greenlet could kill us; we guard all of these operations
    # with a `try/except GreenletExit` to handle this and return an
    # ExecutionResult(was_cancelled=True) in that case.
    try:
      debug_log.write_line('Waiting for process.')
      gevent.wait([GLOBAL_SHUTDOWN, proc], timeout=timeout, count=1)
      if GLOBAL_SHUTDOWN.ready():
        debug_log.write_line('Interrupted by GLOBAL_SHUTDOWN')
        return attr.evolve(ret,
                           retcode=self._kill(
                               debug_log, proc, gid, grace_period),
                           was_cancelled=True)

      # Otherwise our process is done (or timed out).
      ret = attr.evolve(ret, retcode=proc.poll())

      # TODO(iannucci): Make leaking subprocesses explicit (e.g. goma compiler
      # daemon). Better, change daemons to be owned by a gevent Greenlet (so
      # that we don't need to leak processes ever).
      #
      # See BUG/FEATURE below for why we don't do this, even though we should.
      # _kill(proc, gid)  # In case of leaked subprocesses or timeout.

      if ret.retcode is None:
        # Process timed out, kill it. Currently all uses of non-None timeout
        # intend to actually kill the subprocess when the timeout pops.
        ret = attr.evolve(
            ret, retcode=self._kill(debug_log, proc, gid, grace_period))
        debug_log.write_line('Timeout expired (%ds)' % (timeout,))
        return attr.evolve(ret, had_timeout=True)

      debug_log.write_line('Finished waiting, retcode %r' % ret.retcode)
      # TODO(iannucci): Make leaking subprocesses explicit (e.g. goma compiler
      # daemon). Better, change daemons to be owned by a gevent Greenlet (so
      # that we don't need to leak processes ever).
      debug_log.write_line('BUG/FEATURE: Allowing process group to continue.')

    except gevent.GreenletExit:
      debug_log.write_line('Canceled')
      ret = attr.evolve(
          ret, retcode=self._kill(
              debug_log, proc, gid, grace_period), was_cancelled=True)

    return ret

  @staticmethod
  def _reap_workers(workers, to_close, debug_log):
    """Collects the IO workers created with _mk_workers.

    After killing the workers, also closes the subprocess's open PIPE handles.

    See _safe_close for caveats around closing handles on windows.

    Args:
      * workers (List[Greenlet]) - The IO workers to kill.
      * to_close (List[...]) - (see _mk_workers for definition). The handles to
        close. These originate from the `Popen.std{out,err}` handles when the
        recipe engine had to use PIPEs.
      * debug_log (..stream.StreamEngine.Stream)

    Should not raise an exception.
    """
    debug_log.write_line('reaping IO workers...')
    for worker in workers:
      worker.kill()
    gevent.wait(workers)
    debug_log.write_line('  done')
    for handle_name, handle in to_close:
      _safe_close(debug_log, handle_name, handle)


  if MSWINDOWS:
    def _kill(self, debug_log, proc, gid, grace_period):
      """Kills the process as gracefully as possible:

        * Send CTRL_BREAK_EVENT (to the process group, there's no other way)
        * Give main process `grace_period` to quit.
        * Call TerminateProcess on the process we spawned.

      Unfortunately, we don't have a mechanism to do 'TerminateProcess' to the
      process's group, so this could leak processes on Windows.

      If GLOBAL_QUITQUITQUIT is set, then we will abort/skip the first timeout.

      Returns the process's returncode.
      """
      # TODO(iannucci): Use a Job Object for process management. Use
      # subprocess42 for reference.
      _ = gid  # unused on windows

      def _ctrlbreak():
        debug_log.write_line(
            'Proc(%d).send_signal(CTRL_BREAK_EVENT)' % (proc.pid,))
        try:
          # pylint: disable=no-member
          proc.send_signal(signal.CTRL_BREAK_EVENT)
        except OSError:
          pass

      _ctrlbreak()
      gevent.wait([GLOBAL_QUITQUITQUIT, proc], timeout=grace_period, count=1)
      ret = proc.poll()
      if ret is None:
        if GLOBAL_QUITQUITQUIT.ready():
          debug_log.write_line('GLOBAL_QUITQUITQUIT')
        else:
          debug_log.write_line('Grace period expired (%fs)' % (grace_period,))
      else:
        debug_log.write_line('Got retcode %d' % (ret,))

      debug_log.write_line('Proc(%d).terminate()' % (proc.pid,))
      try:
        proc.terminate()
      except OSError:
        pass
      UNKILLED_PROC_GROUPS.discard(proc)

      ret = proc.wait()
      if ret is not None:
        debug_log.write_line('Got retcode %d' % (ret,))
      return ret

  else:
    @staticmethod
    def _killpg(debug_log, gid, signame):
      debug_log.write_line('killpg(%d, %s)' % (gid, signame))
      try:
        os.killpg(gid, getattr(signal, signame))
      except OSError:
        pass

    def _kill(self, debug_log, proc, gid, grace_period):
      """Kills the process in group `gid` as gracefully as possible:

        * Send SIGTERM to the process group.
          * This is a bit atypical for POSIX, but this is done to provide
            consistent behavior between *nix/Windows (where we MUST signal the
            whole group). This allows writing parent/child programs which run
            cross-platform without requiring per-platform parent/child handling
            code.
          * If programs really don't want this, they should make their own
            process group for their children.
        * Give main process `grace_period` to quit.
        * Send SIGKILL to the process group (to avoid leaked processes).
          This will also kill the process we spawned if it's not dead yet.

      Returns the process's returncode.
      """
      self._killpg(debug_log, gid, 'SIGTERM')
      debug_log.write_line('Waiting for process %d.' % (proc.pid,))
      gevent.wait([GLOBAL_QUITQUITQUIT, proc], timeout=grace_period, count=1)
      ret = proc.poll()
      if ret is None:
        if GLOBAL_QUITQUITQUIT.ready():
          debug_log.write_line('GLOBAL_QUITQUITQUIT')
        else:
          debug_log.write_line('Grace period expired (%fs)' % (grace_period,))
      else:
        debug_log.write_line('Got retcode %d' % (ret,))

      self._killpg(debug_log, gid, 'SIGKILL')

      UNKILLED_PROC_GROUPS.discard(gid)
      return ret


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


def _safe_close(debug_log, handle_name, handle):
  """Safely attempt to close the given handle.

  Args:

    * debug_log (Stream) - Stream to write debug information to about closing
      this handle.
    * handle_name (str) - The name of the handle (like 'stdout', 'stderr')
    * handle (file-like-object) - The file object to call .close() on.

  NOTE: On Windows this may end up leaking threads for processes which spawn
  'daemon' children that hang onto the handles we pass. In this case debug_log
  is updated with as much detail as we know and the gevent threadpool's maxsize
  is increased by 2 (one thread blocked on reading from the handle, and one
  thread blocked on trying to close the handle).
  """
  try:
    debug_log.write_line('closing handle %r' % handle_name)
    with gevent.Timeout(.1):
      handle.close()
    debug_log.write_line('  closed!')

  except gevent.Timeout:
    # This should never happen... except on Windows when the process we launched
    # itself leaked.
    debug_log.write_line('  LEAKED: timeout closing handle')
    # We assume we've now leaked 2 threads; one is blocked on 'read' and the
    # other is blocked on 'close'. Add two more threads to the pool so we do not
    # globally block the recipe engine on subsequent steps.
    gevent.get_hub().threadpool.maxsize += 2

  except IOError as ex:
    # TODO(iannucci): Currently this leaks handles on Windows for processes like
    # the goma compiler proxy; because of python2.7's inability to set
    # close_fds=True and also redirect std handles, daemonized subprocesses
    # actually inherit our handles (yuck).
    #
    # This is fixable on python3, but not likely to be fixable on python 2.
    debug_log.write_line('  LEAKED: unable to close: %r' % (ex,))
    # We assume we've now leaked 2 threads; one is blocked on 'read' and the
    # other is blocked on 'close'. Add two more threads to the pool so we do not
    # globally block the recipe engine on subsequent steps.
    gevent.get_hub().threadpool.maxsize += 2

  except RuntimeError:
    # NOTE(gevent): This can happen as a race between the worker greenlet and
    # the process ending. See gevent.subprocess.Popen.communicate, which does
    # the same thing.
    debug_log.write_line('  LEAKED?: race with IO worker')
