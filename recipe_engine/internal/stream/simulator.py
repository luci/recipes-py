# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import collections
from collections.abc import Callable, Sequence
import json
from typing import Any, Literal

from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb

from ... import engine_types
from .. import stream as stream_mod
from ..test import empty_log


def _ignoreable(f: Callable[..., None]) -> Callable[..., None]:
  def check_annotations(
      self: _SimulationStepStream, *args: Any, **kwargs: Any
  ) -> None:
    if self._annotations is not None:
      f(self, *args, **kwargs)
  return check_annotations


class _SimulationStepStream(stream_mod.StreamEngine.StepStream):
  def __init__(self, annotations: dict[str, Any] | None) -> None:
    """A step stream recording annotations for simulation tests.

    Args:
      annotations - The dictionary to map annotations into. If None, annotations
          will be ignored.
    """
    super().__init__()
    self._annotations = annotations

  def _dict_annotation(self, field: str) -> collections.OrderedDict[str, Any]:
    assert self._annotations is not None
    return self._annotations.setdefault(field, collections.OrderedDict())

  @_ignoreable
  def write_line(self, line: str) -> None:
    assert self._annotations is not None
    self._annotations.setdefault('raw_annotations', []).append(line)

  def open_std_handles(
      self, stdout: bool = False, stderr: bool = False
  ) -> dict[str, stream_mod.StreamEngine.Stream]:
    ret: dict[str, stream_mod.StreamEngine.Stream] = {}
    if stdout:
      ret['stdout'] = self
    if stderr:
      ret['stderr'] = self
    return ret

  def close(self) -> None:
    pass

  def new_log_stream(self, log_name: str) -> stream_mod.StreamEngine.Stream:
    # We sink '$execution details' to dev/null. This is the log that the recipe
    # engine produces that contains the printout of the command, environment,
    # etc.
    #
    # The '$debug' log is conditionally filtered in _merge_presentation_updates.
    if self._annotations is None or log_name in ('$execution details',):
      lines: list[str] | None = None
    else:
      # TODO(gbeaty) Remove this?
      log_name = log_name.replace('/', '&#x2f;')
      logs = self._dict_annotation('logs')
      lines = []

    class LogStream(stream_mod.StreamEngine.Stream):
      def write_line(self, line: str) -> None:
        if lines is not None:
          lines.append(line)

      def close(self) -> None:
        if lines is not None:
          if not lines:
            logs[log_name] = empty_log.EMPTY_LOG
          else:
            logs[log_name] = '\n'.join(stream_mod.encode_str(l) for l in lines)

    return LogStream()

  def append_log(self, log: common_pb.Log) -> None:
    # TODO(yiwzhang): This is confusing as it is printing the log proto msg in
    # json format in followup_annotations section of the test expectation file.
    # Normally, we print the actual log content of log there (e.g. json.output
    # log). We should improve this once we remove annotator mode and make
    # simulation speak build.proto natively.
    log_stream = self.new_log_stream(log.name)
    jsonify = jsonpb.MessageToJson(log,
        preserving_proto_field_name=True, sort_keys=True)
    for line in jsonify.splitlines():
      log_stream.write_line(line.rstrip())
    log_stream.close()

  @_ignoreable
  def add_step_text(self, text: str) -> None:
    assert self._annotations is not None
    self._annotations['step_text'] = text

  @_ignoreable
  def add_step_summary_text(self, text: str) -> None:
    assert self._annotations is not None
    self._annotations['step_summary_text'] = text

  @_ignoreable
  def add_step_link(self, name: str, url: str) -> None:
    self._dict_annotation('links')[name] = url

  @_ignoreable
  def set_step_status(self, status: str, had_timeout: bool) -> None:
    assert status in engine_types.StepPresentation.STATUSES, (
        'Impossible status %s' % status)
    del had_timeout
    if status != 'SUCCESS':
      assert self._annotations is not None
      self._annotations['status'] = status

  @_ignoreable
  def set_build_property(self, key: str, value: str) -> None:
    self._dict_annotation('output_properties')[key] = json.loads(value)

  def set_summary_markdown(self, text: str) -> None:
    # TODO(iannucci): don't ignore this... Can fix this when we remove annotator
    # mode.
    pass

  def set_step_tag(self, key: str, value: str) -> None:
    self._dict_annotation('tags')[key] = value


class SimulationStreamEngine(stream_mod.StreamEngine):
  """Stream engine which just records generated commands."""

  def __init__(self) -> None:
    self._annotations_map: collections.OrderedDict[str, dict[str, Any]] = (
        collections.OrderedDict()
    )
    super().__init__()

  @property
  def annotations(self) -> collections.OrderedDict[str, dict[str, Any]]:
    return self._annotations_map

  @property
  def supports_concurrency(self) -> bool:
    return True

  def new_step_stream(
      self,
      name_tokens: Sequence[str],
      allow_subannotations: bool,
      merge_step: bool | Literal['legacy'] = False,
      merge_output_properties_to: Sequence[str] | None = None,
  ) -> _SimulationStepStream:
    del allow_subannotations, merge_step, merge_output_properties_to

    # TODO(iannucci): don't skip these. Omitting them for now to reduce the
    # amount of test expectation changes.
    steps_to_skip = (
      'recipe result',   # explicitly covered by '$result'
    )
    # TODO(iannucci): use '|' separator instead of '.'
    name = '.'.join(name_tokens)
    if name in steps_to_skip:
      annotations: dict[str, Any] | None = None
    else:
      annotations = self._annotations_map[name] = {}
      # TODO(iannucci): this is duplicated with
      # AnnotatorStreamEngine._create_step_stream
      if len(name_tokens) > 1:
        annotations['nest_level'] = len(name_tokens) - 1
    return _SimulationStepStream(annotations)
