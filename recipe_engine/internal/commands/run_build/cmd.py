# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


import logging
import os
import sys

from recipe_engine.third_party import logdog

from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.buildbucket.proto.build import Build

from . import RunBuildContractViolation


LOG = logging.getLogger(__name__)


def _contract_in_env(key):
  if key not in os.environ:
    raise RunBuildContractViolation('Expected $%s in environment.' % key)
  return os.environ[key]


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
      'cache_dir': _contract_in_env('LUCI_CACHE_DIR'),
    },
  }
  LOG.info('Synthesized properties: %r', synth_props)
  return synth_props


def main(args):
  LOG.info('run_build started, parsing Build message from stdin.')
  build = Build()
  build.ParseFromString(sys.stdin.read())
  LOG.info('finished parsing Build message')
  LOG.debug('build proto: %s', jsonpb.MessageToJson(build))

  butler = logdog.bootstrap.ButlerBootstrap.probe()

  props = jsonpb.MessageToDict(build.input.properties)
  props.update(_synth_properties(build))

  LOG.fatal('Remainder of run_build not implemented')
  return 1
