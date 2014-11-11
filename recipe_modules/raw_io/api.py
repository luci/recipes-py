# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api
from slave import recipe_util

import os
import shutil
import tempfile


class InputDataPlaceholder(recipe_util.Placeholder):
  def __init__(self, data, suffix):
    assert isinstance(data, basestring)
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
      self._backing_file = self.data
    else:  # pragma: no cover
      input_fd, self._backing_file = tempfile.mkstemp(suffix=self.suffix)
      os.write(input_fd, self.data)
      os.close(input_fd)
    return [self._backing_file]

  def result(self, presentation, test):
    assert self._backing_file
    exists = os.path.exists(self._backing_file)
    if not test.enabled and exists:  # pragma: no cover
      os.unlink(self._backing_file)
    self._backing_file = None


class OutputDataPlaceholder(recipe_util.Placeholder):
  def __init__(self, suffix, leak_to):
    self.suffix = suffix
    self.leak_to = leak_to
    self._backing_file = None
    super(OutputDataPlaceholder, self).__init__()

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
      return test.data
    else:  # pragma: no cover
      try:
        with open(self._backing_file, 'rb') as f:
          return f.read()
      finally:
        if not self.leak_to:
          os.unlink(self._backing_file)
        self._backing_file = None


class OutputDataDirPlaceholder(recipe_util.Placeholder):
  def __init__(self, suffix, leak_to):
    self.suffix = suffix
    self.leak_to = leak_to
    self._backing_dir = None
    super(OutputDataDirPlaceholder, self).__init__()

  @property
  def backing_file(self):  # pragma: no cover
    raise ValueError('Output dir placeholders can not be used for stdin, '
                     'stdout or stderr')

  def render(self, test):
    assert not self._backing_dir, 'Placeholder can be used only once'
    if self.leak_to:
      self._backing_dir = str(self.leak_to)
      return [self._backing_dir]
    if test.enabled:
      self._backing_dir = '/path/to/tmp/' + self.suffix
    else:  # pragma: no cover
      self._backing_dir = tempfile.mkdtemp(suffix=self.suffix)
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
    return InputDataPlaceholder(data, suffix)

  @recipe_util.returns_placeholder
  @staticmethod
  def output(suffix='', leak_to=None):
    """Returns a Placeholder for use as a step argument, or for std{out,err}.

    If 'leak_to' is None, the placeholder is backed by a temporary file with
    a suffix 'suffix'. The file is deleted when the step finishes.

    If 'leak_to' is not None, then it should be a Path and placeholder
    redirects IO to a file at that path. Once step finishes, the file is
    NOT deleted (i.e. it's 'leaking'). 'suffix' is ignored in that case.
    """
    return OutputDataPlaceholder(suffix, leak_to)

  @recipe_util.returns_placeholder
  @staticmethod
  def output_dir(suffix='', leak_to=None):
    """Returns a directory Placeholder for use as a step argument.

    If 'leak_to' is None, the placeholder is backed by a temporary dir with
    a suffix 'suffix'. The dir is deleted when the step finishes.

    If 'leak_to' is not None, then it should be a Path and placeholder
    redirects IO to a dir at that path. Once step finishes, the dir is
    NOT deleted (i.e. it's 'leaking'). 'suffix' is ignored in that case.
    """
    return OutputDataDirPlaceholder(suffix, leak_to)
