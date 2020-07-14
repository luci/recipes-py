# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os

from recipe_engine import recipe_test_api


class FileTestApi(recipe_test_api.RecipeTestApi):
  def listdir(self, paths=(), errno_name=0):
    """Provides test mock for the `listdir` method.

    Args:
      paths (iterable[str]) - The list of relative paths for this `listdir`
        step to return.
      errno_name (str|None) - The error name for this step to return, if any.

    Example:
      yield (api.test('my_test')
        + api.step_data('listdir step name', api.file.listdir(['a', 'b', 'c']))
    """
    def _check(p):
      p = str(p)
      if p.startswith('../') or p.startswith('..\\'):  # pragma: no cover
        raise ValueError('path is outside of listdir root directory: %r' % p)
      return p
    return (self.m.raw_io.stream_output('\n'.join(sorted(map(_check, paths))))
            + self.errno(errno_name))

  def filesizes(self, sizes=(), errno_name=0):
    """Provides test mock for the `filesizes` method.

    Args:
      sizes (iterable[int]) - The list of sizes to return.
      errno_name (str|None) - The error name for this step to return, if any.

    Example:
      yield (api.test('my_test')
        + api.step_data('filesize step name', api.file.filesizes([1674, 5714]))
    """
    return (self.m.raw_io.stream_output('\n'.join(map(str, sizes)))
            + self.errno(errno_name))

  def read_raw(self, content='', errno_name=0):
    """Provides test mock for the `read_raw` method.

    Args:
      content (str) - The text data for this read_raw step to return.
      errno_name (str|None) - The error name for this step to return, if any.

    Example:
      yield (api.test('my_test')
        + api.step_data('read step name',
            api.file.read_raw('some\0file\0content'))
      )
    """
    return (self.m.raw_io.output(content)
            + self.errno(errno_name))


  def read_text(self, text_content='', errno_name=0):
    """Provides test mock for the `read_text` method.

    Args:
      text_content (str) - The text data for this read_text step to return.
      errno_name (str|None) - The error name for this step to return, if any.

    Example:
      yield (api.test('my_test')
        + api.step_data('read step name',
            api.file.read_text('some\nfile\ncontent'))
      )
    """
    return (self.m.raw_io.output_text(text_content)
            + self.errno(errno_name))

  def read_json(self, json_content='', errno_name=0):
    """Provides test mock for the `read_json` method.

    Args:
      json_content (object) - The json serializable data for this read_json step
        to return.
      errno_name (str|None) - The error name for this step to return, if any.

    Example:
      yield (api.test('my_test')
        + api.step_data('read step name',
            api.file.read_json({'is_content': true}))
      )
    """
    return (self.m.raw_io.output_text(json.dumps(json_content))
            + self.errno(errno_name))

  def read_proto(self, proto_msg, errno_name=0):
    """Provides a test mock for the `read_proto` method.

    Args:
      proto_msg (protobuf Message) - The proto message to be returned.
      errno_name (str|None) - The error name for this step to return, if any.
    """
    return (self.m.proto.output(proto_msg)
            + self.errno(errno_name))

  def glob_paths(self, names=(), errno_name=0):
    """Provides test mock for the `glob_paths` method.

    Args:
      names (iterable[str]) - The file names for the glob_paths step to return.
      errno_name (str|None) - The error name for this step to return, if any.

    Example:
      yield (api.test('my_test')
        + api.step_data('glob step name', api.file.glob_paths([
          'pattern_path', 'pattern_other_thing'
      ]))
    """
    return (self.m.raw_io.stream_output('\n'.join(sorted(map(str, names))))
            + self.errno(errno_name))

  def errno(self, errno_name=None):
    """Provides test mock for any file module method, causing the step to raise
    a file.Error exception.

    Args:
      errno_name (None|str) - The errno error name that the step should raise.
        This must be e.g. 'EPERM', 'EEXIST', etc.
    """
    data = {'ok': True}
    if errno_name:
      data['ok'] = False
      data['errno_name'] = errno_name
      # in real operation, this message will come from the underlying OS and
      # will potentially have descriptive detail.
      data['message'] = 'file command encountered system error '+errno_name
    return self.m.json.output(data)
