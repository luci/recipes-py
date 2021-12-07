# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from builtins import str as text
from future.utils import iterkeys
from future.utils import itervalues

from recipe_engine import recipe_test_api

class RawIOTestApi(recipe_test_api.RecipeTestApi): # pragma: no cover
  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None, name=None):
    """Returns an output Placeholder for the provided data.

    The data is expected to be bytes (i.e. str in python2). However, to help
    with the Python3 migration, the unicode (str in python3) data will also be
    accepted and will be encoded to bytes internally because in Python3,
    `raw_io.output('foo')` pass will actually 'foo' as type 'str' instead of
    'bytes' to this method and we have lots of usages like this. Please
    make 'foo' a byte literal like `b'foo'`. We may drop the unicode support in
    the future.
    """
    if isinstance(data, text):
      # TODO(yiwzhang): implicitly encode the data to bytes to avoid excessive
      # errors during migration to python3. After we drop python2 support,
      # consider raise ValueError instead for non-bytes data.
      data = data.encode('utf-8')
    if not isinstance(data, (type(None), bytes)):
      raise ValueError(
          'expected bytes, got %s: %r' % (type(data), data))
    return data, retcode, name

  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output_text(data, retcode=None, name=None):
    """Returns an output Placeholder for the provided text data.

    data must be either str (unicode in py2) or bytes (str in py2) that has
    valid encoded utf-8 text in it.
    """
    if isinstance(data, bytes):
      data = data.decode('utf-8')
    if not isinstance(data, (type(None), text)):
      raise ValueError(
          'expected None or utf-8 text, got %s: %r' % (type(data), data))
    return data, retcode, name

  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output_dir(files_dict, retcode=None, name=None):
    """Use to mock an `output_dir` placeholder.

    Note that slashes should match the platform that this test is targeting.
    i.e. if this test is targeting Windows, you need to use backslashes.

    Example:

       yield api.test('tname') + api.step_data('sname', api.raw_io.output_dir({
         "some/file": "contents of some/file",
       }))
    """
    assert type(files_dict) is dict
    assert all(isinstance(key, str) for key in iterkeys(files_dict))
    assert all(isinstance(value, bytes) for value in itervalues(files_dict))
    return files_dict, retcode, name

  def stream_output(self, data, stream='stdout', retcode=None, name=None):
    return self._stream_output(data, self.output,
                               stream=stream,
                               retcode=retcode,
                               name=name)

  def stream_output_text(self, data, stream='stdout', retcode=None, name=None):
    return self._stream_output(data, self.output_text,
                               stream=stream,
                               retcode=retcode,
                               name=name)

  def _stream_output(self, data, to_step_data_fn,
                     stream='stdout', retcode=None, name=None):
    ret = recipe_test_api.StepTestData()
    assert stream in ('stdout', 'stderr')
    step_data = to_step_data_fn(data, retcode=retcode, name=name)
    setattr(ret, stream, step_data.unwrap_placeholder())
    if retcode:
      ret.retcode = retcode
    return ret

  @recipe_test_api.placeholder_step_data('output')
  @staticmethod
  def backing_file_missing(retcode=None, name=None):
    """Simulates a missing backing file.

    Only valid if the corresponding placeholder has `leak_to` specified.
    """
    # Passing None as the data of a placeholder causes the placeholder to
    # behave during testing as if its backing file was missing.
    return None, retcode, name
