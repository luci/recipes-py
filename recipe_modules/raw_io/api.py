# -*- encoding: utf-8 -*-
# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides objects for reading and writing raw data to and from steps."""

from __future__ import annotations

from future.utils import raise_

import codecs
import collections
import contextlib
import io
import errno
import os
import shutil
import sys
import tempfile

from recipe_engine import recipe_api
from recipe_engine import util as recipe_util


def _rmfile(p, _win_read_only_unset=False):  # pragma: no cover
  """Deletes a file, even a read-only one on Windows."""
  try:
    os.remove(p)
  except OSError as e:
    if sys.platform == 'win32' and not _win_read_only_unset:
      # Try to remove the read-only bit and remove again.
      os.chmod(p, 0o777)
      _rmfile(p, _win_read_only_unset=True)
    elif e.errno != errno.ENOENT:
      raise


def _rmtree(d):  # pragma: no cover
  """Deletes a directory without throwing, even one with read-only files."""
  if not os.path.exists(d):
    return

  if sys.platform == 'win32':
    # Tested manually.
    def unset_ro_and_remove_again(fn, p, excinfo):
      """Removes file even if it has the READ_ONLY file attribute.

      On Windows, a file with the READ_ONLY file attribute cannot be deleted.
      This is different than on POSIX where only the containing directory ACL
      matters.

      shutil.rmtree() has trouble with this. Helps it a bit.
      """
      # fn is one of islink, listdir, remove or rmdir.
      if fn is os.remove:
        # Try to remove the read-only bit.
        os.chmod(p, 0o777)
        # And remove again.
        os.remove(p)
        return
      # Reraise the original exception.
      raise_(excinfo[0], excinfo[1], excinfo[2])

    # On Windows, some paths exceed MAX_PATH. Work around this by prepending
    # the UNC magic prefix '\\?\' which allows the Windows API file calls to
    # ignore the MAX_PATH limit.
    shutil.rmtree(u'\\\\?\\%s' % (d,), onerror=unset_ro_and_remove_again)
  else:
    shutil.rmtree(d)


class InputDataPlaceholder(recipe_util.InputPlaceholder):
  def __init__(self, data, suffix, name=None):
    self.data = data
    self.suffix = suffix
    self._backing_file = None
    super().__init__(name=name)

  @property
  def backing_file(self):
    return self._backing_file

  def render(self, test):
    assert not self._backing_file, 'Placeholder can be used only once'
    if test.enabled:
      # cheat and pretend like we're going to pass the data on the
      # cmdline for test expectation purposes.
      self._backing_file = self.readable_test_data
    else:  # pragma: no cover
      input_fd, self._backing_file = tempfile.mkstemp(suffix=self.suffix)
      self.write_data(os.dup(input_fd))
      os.close(input_fd)
    return [self._backing_file]

  def cleanup(self, test_enabled):
    assert self._backing_file is not None
    if not test_enabled:  # pragma: no cover
      _rmfile(self._backing_file)
    self._backing_file = None

  def write_data(self, fd): # pragma: no cover
    with io.open(fd, mode='wb') as f:
      f.write(self.data)

  @property
  def readable_test_data(self):
    # TODO(yiwzhang): change errors to backslashreplace after python2 support
    # is dropped so that the expectation will display the escaped raw bytes
    # instead of a replacement character.
    return self.data.decode('utf-8', errors='replace')


class InputTextPlaceholder(InputDataPlaceholder):
  """A input placeholder which expects to write out text."""

  def __init__(self, data, suffix, name=None):
    super().__init__(data, suffix, name=name)
    assert isinstance(data, str)

  def write_data(self, fd): # pragma: no cover
    with io.open(fd, mode='w', encoding='utf-8', errors='replace') as f:
      f.write(self.data)

  @property
  def readable_test_data(self):
    return self.data


class OutputDataPlaceholder(recipe_util.OutputPlaceholder):

  def __init__(self, suffix, leak_to, name=None, add_output_log=False):
    assert add_output_log in (True, False, 'on_failure'), (
        'add_output_log=%r' % add_output_log)
    self.suffix = suffix
    self.leak_to = leak_to
    self.add_output_log = add_output_log
    self._backing_file = None
    super().__init__(name=name)

  @property
  def backing_file(self):
    return self._backing_file

  def render(self, test):
    assert not self._backing_file, 'Placeholder can be used only once'
    if self.leak_to:
      self._backing_file = str(self.leak_to)
      return [self._backing_file]
    if test.enabled:
      self._backing_file = '/path/to/tmp/' + self.suffix.lstrip('.')
    else:  # pragma: no cover
      output_fd, self._backing_file = tempfile.mkstemp(suffix=self.suffix)
      os.close(output_fd)
    return [self._backing_file]

  def result(self, presentation, test):
    assert self._backing_file
    ret = None
    if test.enabled:
      self._backing_file = None
      # Use None to indicate that `result()` should behave as if the backing
      # file is missing. Only valid if `leak_to` is None; otherwise, the
      # backing file is a temporary file created in `render()` that is
      # guaranteed to exist unless the recipe or the step subprocess explicitly
      # removes it before accessing its contents.
      if self.leak_to and test.data is None:
        return None
      ret = self.read_test_data(test)
    else:  # pragma: no cover
      try:
        ret = self.read_data()
      except IOError as e:
        if e.errno != errno.ENOENT:
          raise
      finally:
        if not self.leak_to:
          _rmfile(self._backing_file)
        self._backing_file = None

    if ret is not None and (
        self.add_output_log is True or
        (self.add_output_log == 'on_failure' and
         presentation.status != 'SUCCESS')):
      presentation.logs[self.label] = ret.splitlines()

    return ret

  def read_data(self):  # pragma: no cover
    with io.open(self._backing_file, 'rb') as f:
      return f.read()

  def read_test_data(self, test):
    test_data = test.data or b''
    if not isinstance(test_data, bytes):
      raise TypeError(
          'test data must be binary data, got {!r}'.format(test_data))
    return test_data


class OutputTextPlaceholder(OutputDataPlaceholder):
  """A output placeholder which expects to read utf-8 text."""

  def read_data(self):  # pragma: no cover
    # This ensures that the raw result bytes we got are, in fact, valid utf-8,
    # replacing invalid bytes with �.
    with io.open(self._backing_file,
                 mode='r', encoding='utf-8', errors='replace') as f:
      return f.read()

  def read_test_data(self, test):
    test_data = test.data or ''
    if not isinstance(test_data, str):
      raise TypeError(
          'test data must be text data, got {!r}'.format(test_data))
    return test_data


class _LazyDirectoryReader(collections.abc.Mapping):
  UNSET = object()

  def __init__(self, paths, read_fn):
    self._paths = set(paths)
    self._data = {}
    self._read_fn = read_fn

  def __getitem__(self, rel_path):
    ret = self._data.get(rel_path, self.UNSET)
    if ret is self.UNSET:
      if rel_path not in self._paths:
        raise KeyError(rel_path)
      ret = self._read_fn(rel_path)
      self._data[rel_path] = ret
    return ret

  def __setitem__(self, rel_path, newvalue):  # pragma: no cover
    raise NotImplementedError(
        '_LazyDirectoryReader is not supposed to set directly')

  def __delitem__(self, rel_path):
    self._paths.discard(rel_path)
    self._data.pop(rel_path, None)

  def __iter__(self):
    return iter(self._paths)

  def __len__(self):  # pragma: no cover
    return len(self._paths)


class OutputDataDirPlaceholder(recipe_util.OutputPlaceholder):
  def __init__(self, path_api, backing_dir, name=None):
    self._path_api = path_api
    self._backing_dir = backing_dir

    self._used = False
    super().__init__(name=name)

  @property
  def backing_file(self):  # pragma: no cover
    raise ValueError(
        'Output dir placeholders cannot be used for std{in,out,err}.')

  def render(self, test):
    if self._used:  # pragma: no cover
      raise AssertionError('Placeholder can be used only once')
    self._used = True

    self._backing_dir = str(
        self._path_api.mkdtemp()
        if not self._backing_dir
        else self._backing_dir)

    if not test.enabled:  # pragma: no cover
      if not os.path.exists(self._backing_dir):
        os.makedirs(self._backing_dir)

    return [self._backing_dir]

  def result(self, presentation, test):
    if not self._used:  # pragma: no cover
      raise AssertionError(
          'Placeholder was not yet rendered as part of a step.')

    if test.enabled:
      data = test.data or {}
      return _LazyDirectoryReader(list(data), data.get)
    else:  # pragma: no cover
      all_paths = set()
      for dir_path, _, files in os.walk(self._backing_dir):
        for filename in files:
          abs_path = os.path.join(dir_path, filename)
          rel_path = os.path.relpath(abs_path, self._backing_dir)
          all_paths.add(rel_path)
      def _read_fn(rel_path):
        abspath = self._path_api.join(self._backing_dir, rel_path)
        if self._path_api.sep == '\\':
          # On Windows, some paths exceed MAX_PATH. Work around this by
          # prepending the UNC magic prefix '\\?\' which allows the Windows API
          # file calls to ignore the MAX_PATH limit.
          abspath = r'\\?\%s' % abspath
        with open(abspath, 'rb') as fil:
          return fil.read()
      return _LazyDirectoryReader(all_paths, _read_fn)


class RawIOApi(recipe_api.RecipeApi):
  @recipe_util.returns_placeholder
  @staticmethod
  def input(data, suffix='', name=None):
    """Returns a Placeholder for use as a step argument.

    This placeholder can be used to pass data to steps. The recipe engine will
    dump the 'data' into a file, and pass the filename to the command line
    argument.

    data MUST be either of type 'bytes' (recommended) or type 'str' in Python 3.
    Respectively, 'str' or 'unicode' in Python 2.

    If the provided data is of type 'str', it is encoded to bytes assuming
    utf-8 encoding. Please switch to `input_text(...)` instead in this case.

    If 'suffix' is not '', it will be used when the engine calls
    tempfile.mkstemp.

    See examples/full.py for usage example.
    """
    if isinstance(data, str):  # pragma: no cover
      # TODO(yiwzhang): warn user here to provide bytes data.
      data = data.encode('utf-8', errors='replace')
    if not isinstance(data, bytes):  # pragma: no cover
      raise ValueError("expected bytes, got %s: %r" % (type(data), data))
    return InputDataPlaceholder(data, suffix, name=name)

  @recipe_util.returns_placeholder
  @staticmethod
  def input_text(data, suffix='', name=None):
    """Returns a Placeholder for use as a step argument.

    Similar to input(), but ensures that 'data' is valid utf-8 text. Any
    non-utf-8 characters will be replaced with �.

    data MUST be either of type 'bytes' or type 'str' (recommended) in Python 3.
    Respectively, 'str' or 'unicode' in Python 2.

    If the provided data is of type 'bytes', it is expected to be valid utf-8
    encoded data. Note that, the support of type 'bytes' is for backwards
    compatibility to Python 2, we may drop this support in the future after
    recipe becomes Python 3 only.
    """
    if isinstance(data, bytes):  # pragma: no cover
      # TODO(yiwzhang): warn user here to provide utf-8 text data.
      data = data.decode('utf-8', errors='replace')
    if not isinstance(data, str):  # pragma: no cover
      raise ValueError("expected utf-8 text, got %s: %r" % (type(data), data))
    return InputTextPlaceholder(data, suffix, name=name)

  @recipe_util.returns_placeholder
  @staticmethod
  def output(suffix='', leak_to=None, name=None, add_output_log=False):
    """Returns a Placeholder for use as a step argument, or for std{out,err}.

    If 'leak_to' is None, the placeholder is backed by a temporary file with
    a suffix 'suffix'. The file is deleted when the step finishes.

    If 'leak_to' is not None, then it should be a Path and placeholder
    redirects IO to a file at that path. Once step finishes, the file is
    NOT deleted (i.e. it's 'leaking'). 'suffix' is ignored in that case.

    Args:
       * add_output_log (True|False|'on_failure') - Log a copy of the output
         to a step link named `name`. If this is 'on_failure', only create this
         log when the step has a non-SUCCESS status.
    """
    return OutputDataPlaceholder(suffix, leak_to, name=name,
                                 add_output_log=add_output_log)

  @recipe_util.returns_placeholder
  @staticmethod
  def output_text(suffix='', leak_to=None, name=None, add_output_log=False):
    """Returns a Placeholder for use as a step argument, or for std{out,err}.

    Similar to output(), but uses an OutputTextPlaceholder, which expects utf-8
    encoded text.
    Similar to input(), but tries to decode the resulting data as utf-8 text,
    replacing any decoding errors with �.

    Args:
       * add_output_log (True|False|'on_failure') - Log a copy of the output
         to a step link named `name`. If this is 'on_failure', only create this
         log when the step has a non-SUCCESS status.
    """
    return OutputTextPlaceholder(suffix, leak_to, name=name,
                                 add_output_log=add_output_log)

  @recipe_util.returns_placeholder
  def output_dir(self, leak_to=None, name=None):
    """Returns a directory Placeholder for use as a step argument.

    If `leak_to` is None, the placeholder is backed by a temporary dir.

    Otherwise `leak_to` must be a Path; if the path doesn't exist, it will be
    created.

    The placeholder value attached to the step will be a dictionary-like mapping
    of relative paths to the contents of the file. The actual reading of the
    file data is done lazily (i.e. on first access).

    Relative paths are stored with the native slash delimitation (i.e. forward
    slash on *nix, backslash on Windows).

    Example:

    ```python
    result = api.step('name', [..., api.raw_io.output_dir()])

    # some time later; The read of 'some/file' happens now:
    some_file = api.path.join('some', 'file')
    assert result.raw_io.output_dir[some_file] == 'contents of some/file'

    # data for 'some/file' is cached now; To free it from memory (and make
    # all further reads of 'some/file' an error):
    del result.raw_io.output_dir[some_file]

    result.raw_io.output_dir[some_file] -> raises KeyError
    ```
    """
    return OutputDataDirPlaceholder(self.m.path, leak_to, name=name)
