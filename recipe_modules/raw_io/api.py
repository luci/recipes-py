from slave import recipe_api
from slave import recipe_util

import os
import tempfile

class InputDataPlaceholder(recipe_util.Placeholder):
  def __init__(self, data, suffix):
    assert isinstance(data, basestring)
    self.data = data
    self.suffix = suffix
    self.input_file = None
    super(InputDataPlaceholder, self).__init__()

  def render(self, test):
    if test.enabled:
      # cheat and pretend like we're going to pass the data on the
      # cmdline for test expectation purposes.
      return [self.data]
    else:  # pragma: no cover
      input_fd, self.input_file = tempfile.mkstemp(suffix=self.suffix)
      os.write(input_fd, self.data)
      os.close(input_fd)
      return [self.input_file]

  def result(self, presentation, test):
    if not test.enabled:  # pragma: no cover
      os.unlink(self.input_file)


class OutputDataPlaceholder(recipe_util.Placeholder):
  def __init__(self, suffix):
    self.suffix = suffix
    self.output_file = None
    super(OutputDataPlaceholder, self).__init__()

  def render(self, test):
    if test.enabled:
      return ['/path/to/tmp/' + self.suffix.lstrip('.')]
    else:  # pragma: no cover
      output_fd, self.output_file = tempfile.mkstemp(self.suffix)
      os.close(output_fd)
      return [self.output_file]

  def result(self, presentation, test):
    if test.enabled:
      return test.data
    else:  # pragma: no cover
      assert self.output_file is not None
      try:
        with open(self.output_file, 'rb') as f:
          return f.read()
      finally:
        os.unlink(self.output_file)


class RawIOApi(recipe_api.RecipeApi):
  @recipe_util.returns_placeholder
  @staticmethod
  def input(data, suffix):
    return InputDataPlaceholder(data, suffix)

  @recipe_util.returns_placeholder
  @staticmethod
  def output(suffix):
    return OutputDataPlaceholder(suffix)
