# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Entry point for running recipes for real (not in testing mode)."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from google.protobuf import json_format as jsonpb
import psutil

import recipe_engine

from .... import util
from ....third_party import luci_context

from ... import engine
from ... import global_shutdown
from ... import legacy
from ...step_runner import subproc
from ...stream import annotator
from ...stream import invariants
from ...turboci import common as turboci_common
from ...turboci import fake as turboci_fake


def main(args: argparse.Namespace) -> int:
  with global_shutdown.install_signal_handlers():
    return _main_impl(args)


def _main_impl(args: argparse.Namespace) -> int:
  if args.props:
    for p in args.props:
      args.properties.update(p)

  turboci_common.CLIENT = turboci_fake.FakeTurboCIOrchestrator(test_mode=False)

  properties = args.properties

  properties['recipe'] = args.recipe

  properties = util.fix_json_object(properties)

  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'

  # TODO(iannucci): this is horrible; why do we want to set a workdir anyway?
  # Shouldn't the caller of recipes just CD somewhere if they want a different
  # workdir?
  workdir = (args.workdir or
      os.path.join(recipe_engine.__path__[0], os.path.pardir, 'workdir'))
  logging.info('Using %s as work directory' % workdir)
  if not os.path.exists(workdir):
    os.makedirs(workdir)

  stream_engine = annotator.AnnotatorStreamEngine(sys.stdout)

  # Have a top-level set of invariants to enforce StreamEngine expectations.
  raw_result, _ = engine.RecipeEngine.run_steps(
      args.recipe_deps,
      properties,
      invariants.StreamEngineInvariants.wrap(stream_engine),
      subproc.SubprocessStepRunner(),
      os.environ,
      os.path.abspath(workdir),
      luci_context.read_full(),
      psutil.cpu_count(),
      psutil.virtual_memory().total,
      emit_initial_properties=True)
  result = legacy.to_legacy_result(raw_result)

  if args.output_result_json:
    with open(args.output_result_json, 'w') as fil:
      fil.write(
          str(
              jsonpb.MessageToJson(
                  result, always_print_fields_with_no_presence=True)))

  return 1 if result.HasField("failure") else 0
