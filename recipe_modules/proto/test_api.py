# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from google.protobuf import message

from recipe_engine import recipe_test_api


class ProtoTestApi(recipe_test_api.RecipeTestApi):

  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(proto_msg, retcode=None, name=None):
    """Supplies placeholder data for a proto.output.

    Args:
      * proto_msg - Instance of a proto message that should be returned for this
        placeholder.
      * retcode (Optional[int]) - The returncode of the step.
      * name (Optional[str]) - The name of the placeholder you're mocking.
    """
    if not isinstance(proto_msg, message.Message): # pragma: no cover
      raise ValueError("expected proto Message, got: %r" % (type(proto_msg),))
    return proto_msg, retcode, name

  @recipe_test_api.placeholder_step_data('output')
  @staticmethod
  def backing_file_missing(retcode=None, name=None):
    """Simulates a missing backing file.

    Only valid if the corresponding placeholder has `leak_to` specified.
    """
    # Passing None as the data of a placeholder causes the placeholder to
    # behave during testing as if its backing file was missing.
    return None, retcode, name

  @recipe_test_api.placeholder_step_data('output')
  @staticmethod
  def invalid_contents(retcode=None, name=None):
    """Simulates a file with invalid contents."""
    # Passing None as the data of a placeholder causes the placeholder to
    # behave during testing as if its backing file was missing.
    return 'i are not protoh', retcode, name
