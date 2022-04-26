# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from future.utils import iteritems

from ...test.empty_log import EMPTY_LOG


def _convert_nest_level(value):
  yield '@@@STEP_NEST_LEVEL@%d@@@' % value


def _convert_step_text(value):
  yield '@@@STEP_TEXT@%s@@@' % value


def _convert_step_summary_text(value):
  yield '@@@STEP_SUMMARY_TEXT@%s@@@' % value


def _convert_logs(value):
  for name, log in iteritems(value):
    if log is not EMPTY_LOG:
      for line in log.split('\n'):
        yield '@@@STEP_LOG_LINE@%s@%s@@@' % (name, line)
    yield '@@@STEP_LOG_END@%s@@@' % name


def _convert_links(value):
  for link, url in iteritems(value):
    yield '@@@STEP_LINK@%s@%s@@@' % (link, url)


_STATUS_MAP = {
    'EXCEPTION': '@@@STEP_EXCEPTION@@@',
    'CANCELED': '@@@STEP_EXCEPTION@@@',
    'FAILURE': '@@@STEP_FAILURE@@@',
    'WARNING': '@@@STEP_WARNINGS@@@',
}

def _convert_output_properties(value):
  for prop, prop_value in iteritems(value):
    yield '@@@SET_BUILD_PROPERTY@%s@%s@@@' % (prop, json.dumps(
        prop_value, sort_keys=True))


def _convert_status(value):
  assert value in _STATUS_MAP, (
      'status must be one of %r' % list(_STATUS_MAP))
  yield _STATUS_MAP[value]


def _convert_raw_annotations(value):
  return value


_CONVERTERS = [
    ('nest_level', _convert_nest_level),
    ('step_text', _convert_step_text),
    ('step_summary_text', _convert_step_summary_text),
    ('logs', _convert_logs),
    ('links', _convert_links),
    ('output_properties', _convert_output_properties),
    ('status', _convert_status),
    ('raw_annotations', _convert_raw_annotations),
]


def transform_expectations(path_cleaner, result_data):
  if result_data is None:
    return

  for step in result_data:
    if step.get('cost', None) is None:
      step.pop('cost', None)

    if step['name'] == '$result':
      continue

    annotations = []
    for field, converter in _CONVERTERS:
      if field in step:
        annotations.extend(converter(step.pop(field)))
    if annotations:
      step['~followup_annotations'] = path_cleaner(annotations)
