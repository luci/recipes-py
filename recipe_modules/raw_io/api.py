# -*- encoding: utf-8 -*-
# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides objects for reading and writing raw data to and from steps."""

from future import standard_library
standard_library.install_aliases()
from builtins import range
from past.builtins import basestring
from future.utils import raise_

import codecs
import contextlib
import io
import errno
import os
import shutil
import sys
import tempfile
import UserDict

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
    if not isinstance(data, basestring): # pragma: no cover
      raise TypeError(
        "Data passed to InputDataPlaceholder was %r, expected 'str'"
        % (type(data).__name__))
    self.data = data
    self.suffix = suffix
    self._backing_file = None
    super(InputDataPlaceholder, self).__init__(name=name)

  @property
  def backing_file(self):
    return self._backing_file

  def render(self, test):
    assert not self._backing_file, 'Placeholder can be used only once'
    if test.enabled:
      # cheat and pretend like we're going to pass the data on the
      # cmdline for test expectation purposes.
      with contextlib.closing(io.BytesIO()) as output:
        self.write_encoded_data(output)
        self._backing_file = output.getvalue()
    else:  # pragma: no cover
      # python3 - this can be done properly by opening the file with an
      # encoding.
      input_fd, self._backing_file = tempfile.mkstemp(suffix=self.suffix)
      with os.fdopen(os.dup(input_fd), 'wb') as f:
        self.write_encoded_data(f)
      os.close(input_fd)
    return [self._backing_file]

  def cleanup(self, test_enabled):
    assert self._backing_file is not None
    if not test_enabled:  # pragma: no cover
      _rmfile(self._backing_file)
    self._backing_file = None

  def write_encoded_data(self, f):
    """ Encodes data to be written out, when rendering this placeholder.
    """
    f.write(self.data)


class InputTextPlaceholder(InputDataPlaceholder):
  """A input placeholder which expects to write out text."""

  def __init__(self, data, suffix, name=None):
    super(InputTextPlaceholder, self).__init__(data, suffix, name=name)
    assert isinstance(data, basestring)

  def write_encoded_data(self, f):
    # Sometimes users give us invalid utf-8 data. They shouldn't, but it does
    # happen every once and a while. Just ignore it, and replace with �.
    # We're assuming users only want to write text data out.
    # self.data can be large, so be careful to do the conversion in chunks
    # while streaming the data out, instead of requiring a full copy.
    n = 1 << 16
    # This is a generator expression, so this only copies one chunk of
    # self.data at any one time.
    chunks = (self.data[i:i + n] for i in range(0, len(self.data), n))
    decoded = codecs.iterdecode(chunks, 'utf-8', 'replace')
    for chunk in codecs.iterencode(decoded, 'utf-8'):
      f.write(chunk)


class OutputDataPlaceholder(recipe_util.OutputPlaceholder):

  def __init__(self, suffix, leak_to, name=None, add_output_log=False):
    assert add_output_log in (True, False, 'on_failure'), (
        'add_output_log=%r' % add_output_log)
    self.suffix = suffix
    self.leak_to = leak_to
    self.add_output_log = add_output_log
    self._backing_file = None
    super(OutputDataPlaceholder, self).__init__(name=name)

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

      # python3 - this can be done properly by opening the file with an
      # encoding.
      test_data = test.data or b''
      if isinstance(test.data, unicode):
        test_data = test_data.encode('utf-8')
      with contextlib.closing(io.BytesIO(test_data)) as infile:
        ret = self.read_decoded_data(infile)
    else:  # pragma: no cover
      try:
        with open(self._backing_file, 'rb') as f:
          ret = self.read_decoded_data(f)
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

  def read_decoded_data(self, f):
    """Decodes data to be read in, when getting the result of this
    placeholder."""
    return f.read()


class OutputTextPlaceholder(OutputDataPlaceholder):
  """A output placeholder which expects to write out text."""

  def read_decoded_data(self, f):
    # This ensures that the raw result bytes we got are, in fact, valid utf-8,
    # replacing invalid bytes with �. Because python2's unicode support is
    # wonky, we re-encode the now-valid-utf-8 back into a str object so that
    # users don't need to deal with `unicode` objects.
    # The file contents can be large, so be careful to do the conversion in
    # chunks while streaming the data in, instead of requiring a full copy.
    n = 1 << 16
    chunks = iter(lambda: f.read(n), '')
    decoded = codecs.iterdecode(chunks, 'utf-8', 'replace')
    return ''.join(codecs.iterencode(decoded, 'utf-8'))


class _LazyDirectoryReader(UserDict.DictMixin):
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

  def __delitem__(self, rel_path):
    self._paths.discard(rel_path)
    self._data.pop(rel_path, None)

  def keys(self):  # pylint: disable=missing-docstring
    return list(self._paths)


class OutputDataDirPlaceholder(recipe_util.OutputPlaceholder):
  def __init__(self, path_api, backing_dir, name=None):
    self._path_api = path_api
    self._backing_dir = backing_dir

    self._used = False
    super(OutputDataDirPlaceholder, self).__init__(name=name)

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

    data MUST be of type 'str' (not basestring, not unicode).

    If 'suffix' is not '', it will be used when the engine calls
    tempfile.mkstemp.

    See examples/full.py for usage example.
    """
    return InputDataPlaceholder(data, suffix, name=name)

  @recipe_util.returns_placeholder
  @staticmethod
  def input_text(data, suffix='', name=None):
    """Returns a Placeholder for use as a step argument.

    data MUST be of type 'str' (not basestring, not unicode). The str is
    expected to have valid utf-8 data in it.

    Similar to input(), but ensures that 'data' is valid utf-8 text. Any
    non-utf-8 characters will be replaced with �.
    """
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
