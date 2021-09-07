# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Methods for producing and consuming protobuf data to/from steps and the
filesystem."""

from google.protobuf import message

from recipe_engine import recipe_api, recipe_test_api
from recipe_engine import util as recipe_util

from . import proto_codec

class ProtoOutputPlaceholder(recipe_util.OutputPlaceholder):
  def __init__(self, api, msg_class, codec, add_json_log, name,
               leak_to, decoding_kwargs):
    if codec is proto_codec.BINARY:
      self.raw = api.m.raw_io.output(codec.ext, leak_to=leak_to)
    else:
      self.raw = api.m.raw_io.output_text(codec.ext, leak_to=leak_to)
    self.add_json_log = add_json_log
    self._msg_class = msg_class
    self._codec = codec
    self._decoding_kwargs = decoding_kwargs
    super(ProtoOutputPlaceholder, self).__init__(name=name)

  @property
  def backing_file(self):
    return self.raw.backing_file

  def render(self, test):
    return self.raw.render(test)

  def result(self, presentation, test):
    # This is a bit silly, but we only have the codec information here, and
    # we don't want the user to redundantly provide it in the test.
    if test.enabled and isinstance(test.data, message.Message):
      # We replace the test object with one containing raw bytes for raw_io.
      test = recipe_test_api.PlaceholderTestData(
          data=ProtoApi.encode(test.data, self._codec),
          name=self.name)

    # Save name before self.raw.result() deletes it.
    backing_file = self.backing_file
    raw_data = self.raw.result(presentation, test)
    if raw_data is None:
      if self.add_json_log in (True, 'on_failure'):
        presentation.logs[self.label + ' (read error)'] = [
          'Proto file was missing or unreadable:',
          '  ' + backing_file,
        ]
      return None

    valid = False
    invalid_error = ''
    ret = None
    try:
      ret = ProtoApi.decode(
          raw_data, self._msg_class, self._codec, **self._decoding_kwargs)
      valid = True
    except Exception as ex:  # pragma: no cover
      invalid_error = str(ex)
      jsonErrPrefix = 'Failed to load JSON: '
      if test.enabled and invalid_error.startswith(jsonErrPrefix):
        invalid_error = (
            jsonErrPrefix +
            recipe_util.unify_json_load_err(invalid_error[len(jsonErrPrefix):]))

    if self.add_json_log is True or (
        self.add_json_log == 'on_failure' and presentation.status != 'SUCCESS'):
      if valid:
        jsonpb = ProtoApi.encode(ret, 'JSONPB', indent=2)
        presentation.logs[self.label] = jsonpb.splitlines()
      else:
        presentation.logs[self.label + ' (invalid)'] = raw_data.splitlines()
        presentation.logs[self.label + ' (exception)'] = (
          invalid_error.splitlines())

    return ret


class ProtoApi(recipe_api.RecipeApi):

  @recipe_util.returns_placeholder
  def input(self, proto_msg, codec, **encoding_kwargs):
    """A placeholder which will expand to a file path containing the encoded
    `proto_msg`.

    Example:
       proto_msg = MyMessage(field=10)
       api.step('step name', ['some_cmd', api.proto.input(proto_msg)])
       # some_cmd sees "/path/to/random.pb"

    Args:
      * proto_msg (message.Message) - The message data to encode.
      * codec ('BINARY'|'JSONPB'|'TEXTPB') - The encoder to use.
      * encoding_kwargs - Passed directly to the chosen encoder. See:
        - BINARY: google.protobuf.message.Message.SerializeToString
          * 'deterministic' defaults to True.
        - JSONPB: google.protobuf.json_format.MessageToJson
          * 'preserving_proto_field_name' defaults to True.
          * 'sort_keys' defaults to True.
          * 'indent' defaults to 0.
        - TEXTPB: google.protobuf.text_format.MessageToString

    Returns an InputPlaceholder.
    """
    codec = proto_codec.resolve(codec)
    encoded = self.encode(proto_msg, codec, **encoding_kwargs)
    suffix = '.%s' % (codec.ext,)
    if codec is proto_codec.BINARY:
      return self.m.raw_io.input(encoded, suffix=suffix)
    return self.m.raw_io.input_text(encoded, suffix=suffix)

  @recipe_util.returns_placeholder
  def output(self, msg_class, codec, add_json_log=True, name=None,
             leak_to=None, **decoding_kwargs):
    """A placeholder which expands to a file path and then reads an encoded
    proto back from that location when the step finishes.

    Args:
      * msg_class (protobuf Message subclass) - The message type to decode.
      * codec ('BINARY'|'JSONPB'|'TEXTPB') - The encoder to use.
      * add_json_log (True|False|'on_failure') - Log a copy of the parsed proto
        in JSONPB form to a step link named `name`. If this is 'on_failure',
        only create this log when the step has a non-SUCCESS status.
      * leak_to (Optional[Path]) - This path will be used in place of a random
        temporary file, and the file will not be deleted at the end of the step.
      * decoding_kwargs - Passed directly to the chosen decoder. See:
        - BINARY: google.protobuf.message.Message.Parse
        - JSONPB: google.protobuf.json_format.Parse
          * 'ignore_unknown_fields' defaults to True.
        - TEXTPB: google.protobuf.text_format.Parse
    """
    codec = proto_codec.resolve(codec)
    if not issubclass(msg_class, message.Message): # pragma: no cover
      raise ValueError('msg_class is unexpected type: %r' % (msg_class,))
    if add_json_log not in (True, False, 'on_failure'): # pragma: no cover
      raise ValueError(
          'unexpected value for add_json_log: %r' % (add_json_log,))

    return ProtoOutputPlaceholder(
        self, msg_class, codec, add_json_log, name, leak_to, decoding_kwargs)

  @staticmethod
  def encode(proto_msg, codec, **encoding_kwargs):
    """Encodes a proto message to a string.

    Args:
      * codec ('BINARY'|'JSONPB'|'TEXTPB') - The encoder to use.
      * encoding_kwargs - Passed directly to the chosen encoder. See output
        placeholder for details.

    Returns the encoded proto message.
    """
    if not isinstance(proto_msg, message.Message): # pragma: no cover
      raise ValueError('proto_msg had unexpected type: %s' % (type(proto_msg),))
    return proto_codec.do_enc(codec, proto_msg, **encoding_kwargs)

  @staticmethod
  def decode(data, msg_class, codec, **decoding_kwargs):
    """Decodes a proto message from a string.

    Args:
      * msg_class (protobuf Message subclass) - The message type to decode.
      * codec ('BINARY'|'JSONPB'|'TEXTPB') - The encoder to use.
      * decoding_kwargs - Passed directly to the chosen decoder. See input
        placeholder for details.

    Returns the decoded proto object.
    """
    if not issubclass(msg_class, message.Message): # pragma: no cover
      raise ValueError('msg_class is unexpected type: %r' % (msg_class,))
    return proto_codec.do_dec(data, msg_class, codec, **decoding_kwargs)
