# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
import json
from typing import Any

from ...test import empty_log


def _convert_nest_level(value: int) -> Iterator[str]:
  yield '@@@STEP_NEST_LEVEL@%d@@@' % value


def _convert_step_text(value: str) -> Iterator[str]:
  yield '@@@STEP_TEXT@%s@@@' % value


def _convert_step_summary_text(value: str) -> Iterator[str]:
  yield '@@@STEP_SUMMARY_TEXT@%s@@@' % value


def _convert_logs(value: Mapping[str, str]) -> Iterator[str]:
  for name, log in value.items():
    if log is not empty_log.EMPTY_LOG:
      for line in log.split('\n'):
        yield '@@@STEP_LOG_LINE@%s@%s@@@' % (name, line)
    yield '@@@STEP_LOG_END@%s@@@' % name


def _convert_links(value: Mapping[str, str]) -> Iterator[str]:
  for link, url in value.items():
    yield '@@@STEP_LINK@%s@%s@@@' % (link, url)


_STATUS_MAP = {
    'EXCEPTION': '@@@STEP_EXCEPTION@@@',
    'CANCELED': '@@@STEP_EXCEPTION@@@',
    'FAILURE': '@@@STEP_FAILURE@@@',
    'WARNING': '@@@STEP_WARNINGS@@@',
}


def _convert_output_properties(value: Mapping[str, Any]) -> Iterator[str]:
  for prop, prop_value in value.items():
    yield '@@@SET_BUILD_PROPERTY@%s@%s@@@' % (prop, json.dumps(
        prop_value, sort_keys=True))


def _convert_status(value: str) -> Iterator[str]:
  assert value in _STATUS_MAP, (
      'status must be one of %r' % list(_STATUS_MAP))
  yield _STATUS_MAP[value]


def _convert_raw_annotations(value: Sequence[str]) -> Sequence[str]:
  return value


_CONVERTERS: list[tuple[str, Callable[[Any], Iterable[str]]]] = [
    ('nest_level', _convert_nest_level),
    ('step_text', _convert_step_text),
    ('step_summary_text', _convert_step_summary_text),
    ('logs', _convert_logs),
    ('links', _convert_links),
    ('output_properties', _convert_output_properties),
    ('status', _convert_status),
    ('raw_annotations', _convert_raw_annotations),
]


def transform_expectations(
    path_cleaner: Callable[[list[str]], list[str]],
    result_data: Sequence[dict[str, Any]] | None,
) -> None:
  if result_data is None:
    return

  for step in result_data:
    if step.get('cost', None) is None:
      step.pop('cost', None)

    if step['name'] == '$result':
      continue

    annotations: list[str] = []
    for field, converter in _CONVERTERS:
      if field in step:
        annotations.extend(converter(step.pop(field)))
    if annotations:
      step['~followup_annotations'] = path_cleaner(annotations)
