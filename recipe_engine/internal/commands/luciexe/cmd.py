# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import logging
import os
import sys

import psutil

from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.go.chromium.org.luci.buildbucket.proto.build import Build

from ....third_party import luci_context
from ....util import strip_unicode

from ...engine import RecipeEngine
from ...step_runner.subproc import SubprocessStepRunner
from ...stream.invariants import StreamEngineInvariants
from ...stream.luci import LUCIStreamEngine

from . import RunBuildContractViolation


LOG = logging.getLogger(__name__)


def _contract_in_env(key):
  if key not in os.environ:
    raise RunBuildContractViolation('Expected $%s in environment.' % key)
  return os.environ[key]


def _contract_in_luci_context(section_name, key):
  section = luci_context.read(section_name)
  if section is None or key not in section:
    raise RunBuildContractViolation('Expected %r in $LUCI_CONTEXT[%r].' % (
      key, section_name))
  return section[key]


def _synth_properties(build, current_properties):
  # TODO(iannucci): expose this data natively as a Build message.
  synth_props = {
    '$recipe_engine/runtime': {
      'is_experimental': build.input.experimental,
      'is_luci': True,
    },
    '$recipe_engine/buildbucket': {
      'build': jsonpb.MessageToDict(build),
    },
    '$recipe_engine/path': {
      'temp_dir': _contract_in_env('TMP'),
      'cache_dir': _contract_in_luci_context('luciexe', 'cache_dir'),
    },
  }

  # TODO(iannucci): These are all deprecated and have proper apis.
  #
  # When we have the warnings functionality in recipes, update the properties
  # module to issue warnings for accessing these.
  if 'buildername' not in current_properties and build.builder.builder:
    synth_props['buildername'] = build.builder.builder
  if 'buildnumber' not in current_properties and build.number:
    synth_props['buildnumber'] = build.number
  if 'bot_id' not in current_properties and 'SWARMING_BOT_ID' in os.environ:
    synth_props['bot_id'] = os.environ['SWARMING_BOT_ID']
  LOG.info('Synthesized properties: %r', synth_props)
  return synth_props


def _tweak_env():
  # These tweaks are recipe-engine-specific tweaks to be compatible with the
  # behavior of `recipes.py run`.
  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'


def main(args):
  LOG.info('luciexe started, parsing Build message from stdin.')
  build = Build()
  build.ParseFromString(sys.stdin.read())
  LOG.info('finished parsing Build message')
  LOG.debug('build proto: %s', jsonpb.MessageToJson(build))

  properties = jsonpb.MessageToDict(build.input.properties)
  properties.update(_synth_properties(build, properties))
  properties = strip_unicode(properties)

  _tweak_env()

  luciexe_engine = LUCIStreamEngine(args.build_proto_jsonpb)

  raw_result = None
  with StreamEngineInvariants.wrap(luciexe_engine) as stream_engine:
    try:
      raw_result, _ = RecipeEngine.run_steps(
          args.recipe_deps, properties, stream_engine,
          SubprocessStepRunner(), os.environ, os.getcwd(),
          psutil.cpu_count(), psutil.virtual_memory().total)
      stream_engine.write_result(raw_result)
    except:
      LOG.exception("RecipeEngine.run_steps uncaught exception.")
      raise

  return 0 if (raw_result and raw_result.status == common.SUCCESS) else 1
