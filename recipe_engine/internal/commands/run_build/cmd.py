# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


import logging
import os
import sys

from recipe_engine.third_party import logdog, luci_context
from recipe_engine.internal.stream import StreamEngine, StreamEngineInvariants
from recipe_engine.internal import step_runner

from ..run.cmd import run_steps

from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.buildbucket.proto.build import Build

from . import RunBuildContractViolation


LOG = logging.getLogger(__name__)


def _contract_in_env(key):
  if key not in os.environ:
    raise RunBuildContractViolation('Expected $%s in environment.' % key)
  return os.environ[key]

def _contract_in_luci_context(section, key):
  section = luci_context.read(section)
  if section is None or key not in section:
    raise RunBuildContractViolation('Expected %r in $LUCI_CONTEXT[%r].' % (
      key, section))
  return section[key]


def _synth_properties(build):
  # TODO(iannucci): expose this data natively as a Build message.
  synth_props = {
    '$recipe_engine/runtime': {
      'is_experimental': build.input.experimental,
      'is_luci': True,
    },
    '$recipe_engine/buildbucket': jsonpb.MessageToDict(build),
    '$recipe_engine/path': {
      'temp_dir': _contract_in_env('TMP'),
      'cache_dir': _contract_in_luci_context('run_build', 'cache_dir'),
    },
  }
  LOG.info('Synthesized properties: %r', synth_props)
  return synth_props


def _tweak_env():
  # These tweaks are recipe-engine-specific tweaks to be compatible with the
  # behavior of `recipes.py run`.
  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'


class LUCIStreamEngine(StreamEngine):
  def __init__(self):
    self._butler = logdog.bootstrap.ButlerBootstrap.probe()

  @property
  def was_successful(self):
    return 0


def main(args):
  LOG.info('run_build started, parsing Build message from stdin.')
  build = Build()
  build.ParseFromString(sys.stdin.read())
  LOG.info('finished parsing Build message')
  LOG.debug('build proto: %s', jsonpb.MessageToJson(build))

  properties = jsonpb.MessageToDict(build.input.properties)
  properties.update(_synth_properties(build))

  _tweak_env()

  run_build_engine = LUCIStreamEngine()

  with StreamEngineInvariants.wrap(run_build_engine) as stream_engine:
    run_steps(
        args.recipe_deps, properties, stream_engine,
        step_runner.SubprocessStepRunner(stream_engine))

  return 0 if run_build_engine.was_successful else 1
