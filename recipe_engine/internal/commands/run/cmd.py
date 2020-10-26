# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Entry point for running recipes for real (not in testing mode)."""

import logging
import os
import sys

import psutil

from google.protobuf import json_format as jsonpb

from recipe_engine import __path__ as RECIPE_ENGINE_PATH

from .... import util

from ... import legacy

from ...engine import RecipeEngine
from ...global_shutdown import install_signal_handlers
from ...step_runner.subproc import SubprocessStepRunner
from ...stream.annotator import AnnotatorStreamEngine
from ...stream.invariants import StreamEngineInvariants
from ...warn.record import NULL_WARNING_RECORDER

from ....third_party import luci_context


def main(args):
  with install_signal_handlers():
    return _main_impl(args)


def _main_impl(args):
  if args.props:
    for p in args.props:
      args.properties.update(p)

  properties = args.properties

  properties['recipe'] = args.recipe

  properties = util.strip_unicode(properties)

  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'

  # TODO(iannucci): this is horrible; why do we want to set a workdir anyway?
  # Shouldn't the caller of recipes just CD somewhere if they want a different
  # workdir?
  workdir = (args.workdir or
      os.path.join(RECIPE_ENGINE_PATH[0], os.path.pardir, 'workdir'))
  logging.info('Using %s as work directory' % workdir)
  if not os.path.exists(workdir):
    os.makedirs(workdir)

  stream_engine = AnnotatorStreamEngine(sys.stdout)

  # Have a top-level set of invariants to enforce StreamEngine expectations.
  raw_result, _ = RecipeEngine.run_steps(
      args.recipe_deps,
      properties,
      StreamEngineInvariants.wrap(stream_engine),
      SubprocessStepRunner(),
      NULL_WARNING_RECORDER,
      os.environ,
      os.path.abspath(workdir),
      luci_context.read_full(),
      psutil.cpu_count(),
      psutil.virtual_memory().total,
      emit_initial_properties=True)
  result = legacy.to_legacy_result(raw_result)

  if args.output_result_json:
    with open(args.output_result_json, 'w') as fil:
      fil.write(jsonpb.MessageToJson(
          result, including_default_value_fields=True))

  return 1 if result.HasField("failure") else 0
