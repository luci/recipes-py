# -*- encoding: utf-8 -*-
# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api
from recipe_engine import util as recipe_util

import os
import shutil
import tempfile


class InputDataPlaceholder(recipe_util.InputPlaceholder):
  def __init__(self, data, suffix):
    if not isinstance(data, str): # pragma: no cover
      raise TypeError(
        "Data passed to InputDataPlaceholder was %r, expected 'str'"
        % (type(data).__name__))
    self.data = data
    self.suffix = suffix
    self._backing_file = None
    super(InputDataPlaceholder, self).__init__()

  @property
  def backing_file(self):
    return self._backing_file

  def render(self, test):
    assert not self._backing_file, 'Placeholder can be used only once'
    if test.enabled:
      # cheat and pretend like we're going to pass the data on the
      # cmdline for test expectation purposes.
      self._backing_file = self.encode(self.data)
    else:  # pragma: no cover
      input_fd, self._backing_file = tempfile.mkstemp(suffix=self.suffix)

      os.write(input_fd, self.encode(self.data))
      os.close(input_fd)
    return [self._backing_file]

  def cleanup(self, test_enabled):
    assert self._backing_file is not None
    if not test_enabled:  # pragma: no cover
      try:
        os.unlink(self._backing_file)
      except OSError:
        pass
    self._backing_file = None

  def encode(self, data):
    """ Encodes data to be written out, when rendering this placeholder.
    """
    return data

class InputTextPlaceholder(InputDataPlaceholder):
  """ A input placeholder which expects to write out text.
  """
  def __init__(self, data, suffix):
    super(InputTextPlaceholder, self).__init__(data, suffix)
    assert isinstance(data, basestring)

  def encode(self, data):
    # Sometimes users give us invalid utf-8 data. They shouldn't, but it does
    # happen every once and a while. Just ignore it, and replace with �.
    # We're assuming users only want to write text data out.
    return data.decode('utf-8', 'replace').encode('utf-8')


class OutputDataPlaceholder(recipe_util.OutputPlaceholder):
  def __init__(self, suffix, leak_to, name=None):
    self.suffix = suffix
    self.leak_to = leak_to
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
    if test.enabled:
      self._backing_file = None
      return self.decode(test.data)
    else:  # pragma: no cover
      try:
        with open(self._backing_file, 'rb') as f:
          return self.decode(f.read())
      finally:
        if not self.leak_to:
          os.unlink(self._backing_file)
        self._backing_file = None

  def decode(self, result):
    """ Decodes data to be read in, when getting the result of this placeholder.
    """
    return result

class OutputTextPlaceholder(OutputDataPlaceholder):
  """ A output placeholder which expects to write out text.
  """
  def decode(self, result):
    # This ensures that the raw result bytes we got are, in fact, valid utf-8,
    # replacing invalid bytes with �. Because python2's unicode support is
    # wonky, we re-encode the now-valid-utf-8 back into a str object so that
    # users don't need to deal with `unicode` objects.
    return (None if result is None
            else result.decode('utf-8', 'replace').encode('utf-8'))

class OutputDataDirPlaceholder(recipe_util.OutputPlaceholder):
  def __init__(self, suffix, leak_to, name=None):
    self.suffix = suffix
    self.leak_to = leak_to
    self._backing_dir = None
    super(OutputDataDirPlaceholder, self).__init__(name=name)

  @property
  def backing_file(self):  # pragma: no cover
    raise ValueError('Output dir placeholders can not be used for stdin, '
                     'stdout or stderr')

  def render(self, test):
    assert not self._backing_dir, 'Placeholder can be used only once'
    if self.leak_to:
      self._backing_dir = str(self.leak_to)
      if not test.enabled: # pragma: no cover
        if not os.path.exists(self._backing_dir):
          os.mkdir(self._backing_dir)
    else:
      if not test.enabled: # pragma: no cover
        self._backing_dir = tempfile.mkdtemp(suffix=self.suffix)
      else:
        self._backing_dir = '/path/to/tmp/' + self.suffix

    return [self._backing_dir]

  def result(self, presentation, test):
    assert self._backing_dir
    if test.enabled:
      self._backing_dir = None
      return test.data or {}
    else:  # pragma: no cover
      try:
        all_files = {}
        for dir_path, _, files in os.walk(self._backing_dir):
          for filename in files:
            abs_path = os.path.join(dir_path, filename)
            rel_path = os.path.relpath(abs_path, self._backing_dir)
            with open(abs_path, 'rb') as f:
              all_files[rel_path] = f.read()
        return all_files
      finally:
        if not self.leak_to:
          shutil.rmtree(self._backing_dir)
        self._backing_dir = None


class RawIOApi(recipe_api.RecipeApi):
  @recipe_util.returns_placeholder
  @staticmethod
  def input(data, suffix=''):
    """Returns a Placeholder for use as a step argument.

    This placeholder can be used to pass data to steps. The recipe engine will
    dump the 'data' into a file, and pass the filename to the command line
    argument.

    data MUST be of type 'str' (not basestring, not unicode).

    If 'suffix' is not '', it will be used when the engine calls
    tempfile.mkstemp.

    See example.py for usage example.
    """
    return InputDataPlaceholder(data, suffix)

  @recipe_util.returns_placeholder
  @staticmethod
  def input_text(data, suffix=''):
    """Returns a Placeholder for use as a step argument.

    data MUST be of type 'str' (not basestring, not unicode). The str is
    expected to have valid utf-8 data in it.

    Similar to input(), but ensures that 'data' is valid utf-8 text. Any
    non-utf-8 characters will be replaced with �.
    """
    return InputTextPlaceholder(data, suffix)

  @recipe_util.returns_placeholder
  @staticmethod
  def output(suffix='', leak_to=None, name=None):
    """Returns a Placeholder for use as a step argument, or for std{out,err}.

    If 'leak_to' is None, the placeholder is backed by a temporary file with
    a suffix 'suffix'. The file is deleted when the step finishes.

    If 'leak_to' is not None, then it should be a Path and placeholder
    redirects IO to a file at that path. Once step finishes, the file is
    NOT deleted (i.e. it's 'leaking'). 'suffix' is ignored in that case.
    """
    return OutputDataPlaceholder(suffix, leak_to, name=name)

  @recipe_util.returns_placeholder
  @staticmethod
  def output_text(suffix='', leak_to=None, name=None):
    """Returns a Placeholder for use as a step argument, or for std{out,err}.

    Similar to output(), but uses an OutputTextPlaceholder, which expects utf-8
    encoded text.
    Similar to input(), but tries to decode the resulting data as utf-8 text,
    replacing any decoding errors with �.
    """
    return OutputTextPlaceholder(suffix, leak_to, name=name)

  @recipe_util.returns_placeholder
  @staticmethod
  def output_dir(suffix='', leak_to=None, name=None):
    """Returns a directory Placeholder for use as a step argument.

    If 'leak_to' is None, the placeholder is backed by a temporary dir with
    a suffix 'suffix'. The dir is deleted when the step finishes.

    If 'leak_to' is not None, then it should be a Path and placeholder
    redirects IO to a dir at that path. Once step finishes, the dir is
    NOT deleted (i.e. it's 'leaking'). 'suffix' is ignored in that case.
    """
    return OutputDataDirPlaceholder(suffix, leak_to, name=name)
