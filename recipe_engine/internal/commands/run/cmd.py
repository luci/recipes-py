# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Entry point for running recipes for real (not in testing mode)."""

import logging
import os
import sys

from google.protobuf import json_format as jsonpb

from recipe_engine import __path__ as RECIPE_ENGINE_PATH

from .... import util

from ...engine import run_steps
from ...step_runner.subproc import SubprocessStepRunner
from ...stream.annotator import AnnotatorStreamEngine
from ...stream.invariants import StreamEngineInvariants


def handle_recipe_return(recipe_result, result_filename, stream_engine):
  if result_filename:
    with open(result_filename, 'w') as fil:
      fil.write(jsonpb.MessageToJson(
          recipe_result, including_default_value_fields=True))

  if recipe_result.json_result:
    with stream_engine.make_step_stream('recipe result') as s:
      with s.new_log_stream('result') as l:
        l.write_split(recipe_result.json_result)

  if recipe_result.HasField('failure'):
    f = recipe_result.failure
    with stream_engine.make_step_stream('Failure reason') as s:
      s.set_step_status(
         'FAILURE' if recipe_result.failure.HasField('failure') else 'EXCEPTION')
      with s.new_log_stream('reason') as l:
        l.write_split(f.human_reason)

    return 1

  return 0


def main(args):
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

  # This only applies to 'annotation' mode and will go away with build.proto.
  # It is slightly hacky, but this property is the officially documented way
  # to communicate to the recipes that they are in LUCI-mode, so we might as
  # well use it.
  emit_initial_properties = bool(
    properties.
    get('$recipe_engine/runtime', {}).
    get('is_luci', False)
  )

  # Have a top-level set of invariants to enforce StreamEngine expectations.
  with StreamEngineInvariants.wrap(stream_engine) as stream_engine:
    ret = run_steps(
        args.recipe_deps, properties, stream_engine,
        SubprocessStepRunner(stream_engine),
        os.path.abspath(workdir),
        emit_initial_properties=emit_initial_properties)

    return handle_recipe_return(ret, args.output_result_json, stream_engine)
