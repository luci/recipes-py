# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from collections import OrderedDict

import attr

from future.utils import iteritems
from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2

from ...recipe_test_api import StepTestData, BaseTestData
from ...step_data import ExecutionResult
from ...third_party import luci_context
from ...engine_types import ResourceCost

from ..engine_env import FakeEnviron
from ..global_shutdown import GLOBAL_SHUTDOWN

from . import StepRunner, Step


class SimulationStepRunner(StepRunner):
  """Pretends to run steps, instead recording what would have been run.

  This is the main workhorse of recipes.py simulation_test.  Returns the log of
  steps that would have been run in steps_ran.  Uses test_data to mock return
  values.
  """

  def __init__(self, test_data):
    self._test_data = test_data

    # dot-name -> StepTestData
    self._used_steps = {}

    # (dot-name, namespace, name) -> PlaceholderTestData
    self._used_placeholders = {}

    # (dot-name, handle_name) -> PlaceholderTestData
    self._used_handle_placeholders = {}

    # dot-name -> {
    #   env_prefixes: {str: List[str]}
    #   env_suffixes: {str: List[str]}
    #   env: {str: str}
    #   infra_step: bool
    #   timeout: int
    #   allow_subannotations: bool
    # }
    #
    # NOTE: This data is merged with the ordered presentation (UI) data in the
    # test command implementation. Thus this dictionary doesn't need to be
    # ordered.
    #
    # TODO(iannucci): Make this expectation data a real type (either @attr.s or
    # a protobuf message)
    self._step_precursor_data = {}

    # dot-name -> Step
    self._step_history = {}

  def register_step_config(self, name_tokens, step_config):
    dot_name = '.'.join(name_tokens)

    # This moves the test data from _test_data to _used_steps. This will return
    # StepData() if `dot_name` isn't in self._test_data.
    self._used_steps[dot_name] = self._test_data.pop_step_test_data(
        dot_name, step_config.step_test_data or StepTestData)

    if self._used_steps[dot_name].global_shutdown_event == 'before':
      GLOBAL_SHUTDOWN.set()

    self._step_precursor_data[dot_name] = {
      'env_prefixes': step_config.env_prefixes.mapping,
      'env_suffixes': step_config.env_suffixes.mapping,
      'env': {
        k: v for k, v in iteritems(step_config.env)
        # Trim out LUCI_CONTEXT because it's useless information in tests, since
        # the entire luci_context data is included in the test output.
        if k.upper() != luci_context.ENV_KEY
      },
      'timeout': step_config.timeout,
      'infra_step': step_config.infra_step,
      'allow_subannotations': step_config.allow_subannotations,
    }

    if step_config.cost != ResourceCost():
      self._step_precursor_data[dot_name]['cost'] = step_config.cost

  def placeholder(self, name_tokens, placeholder):
    dot_name = '.'.join(name_tokens)
    # TODO(iannucci): this is janky; simplify all the placeholder naming stuff.
    # See comment on step_data.StepData.
    module_name, method_name = placeholder.namespaces
    name = placeholder.name

    key = (dot_name, module_name, method_name, name)
    if key not in self._used_placeholders:
      self._used_placeholders[key] = self._used_steps[dot_name].pop_placeholder(
          module_name, method_name, name)
    ret = self._used_placeholders[key]
    return ret

  def handle_placeholder(self, name_tokens, handle_name):
    dot_name = '.'.join(name_tokens)

    key = (dot_name, handle_name)
    if key not in self._used_placeholders:
      self._used_placeholders[key] = getattr(
          self._used_steps[dot_name], handle_name)
    return self._used_placeholders[key]

  def now(self):
    # Note that we COULD coordinate with some simulatable time system (e.g. the
    # recipe_engine/time module)... however this is just used for adjusting
    # the soft_deadline in LUCI_CONTEXT['deadline'] prior to invoking
    # write_luci_context where the simulation currently discards it anyway.
    return 0

  def write_luci_context(self, section_values):
    # We ignore this environment variable anyway.
    return ""

  def run(self, name_tokens, debug_log, step):
    del debug_log  # unused

    dot_name = '.'.join(name_tokens)

    # Create the "recipe expectation" dict for this step.
    # TODO(iannucci): Rationalize these:
    #   * use step.env instead of precursor
    #   * Always omit empty fields (right now cmd is kept)
    step_obj = attr.asdict(
        step, filter=lambda attr, value: bool(value))
    step_obj['name'] = dot_name
    if 'cmd' not in step_obj:
      step_obj['cmd'] = []
    precursor = self._step_precursor_data[dot_name]

    step_obj.pop('luci_context', None)
    if step.luci_context:
      lctx = {}
      for name, section in iteritems(step.luci_context):
        if name == 'deadline':
          # This is the default deadline and is fully specified by the
          # `timeout` parameter below. To avoid blowing out expectations, we
          # omit the section.
          default_deadline = sections_pb2.Deadline(
              soft_deadline=precursor['timeout'],
              grace_period=30,
          )
          if section == default_deadline:
            continue
        lctx[name] = jsonpb.MessageToDict(section)
      # Finally, if any sections actually made it through, set it on step_obj
      # here.
      if lctx:
        step_obj['luci_context'] = lctx

    for handle_name in ('stdout', 'stderr'):
      step_obj.pop(handle_name, None)
    if 'cost' in precursor:
      if precursor['cost'] is None:
        step_obj['cost'] = None
      else:
        step_obj['cost'] = attr.asdict(precursor['cost'])
    if precursor['env_prefixes']:
      step_obj['env_prefixes'] = precursor['env_prefixes']
    if precursor['env_suffixes']:
      step_obj['env_suffixes'] = precursor['env_suffixes']
    if precursor['env']:
      fake_env = FakeEnviron()
      step_obj['env'] = {
        k: (v if v is None else v % fake_env)
        for k, v in iteritems(precursor['env'])
      }
    else:
      step_obj.pop('env', None)
    if precursor['infra_step']:
      step_obj['infra_step'] = True
    if precursor['allow_subannotations']:
      step_obj['allow_subannotations'] = True
    if precursor['timeout']:
      step_obj['timeout'] = precursor['timeout']
    self._step_history.setdefault(dot_name, {}).update(step_obj)

    tdata = self._used_steps[dot_name]

    if tdata.global_shutdown_event == 'after':
      GLOBAL_SHUTDOWN.set()

    if tdata.times_out_after and precursor['timeout']:
      if tdata.times_out_after > precursor['timeout']:
        return ExecutionResult(had_timeout=True)

    if tdata.cancel:
      return ExecutionResult(was_cancelled=True, retcode=tdata.retcode)

    return ExecutionResult(retcode=tdata.retcode or 0)

  def run_noop(self, name_tokens, debug_log):
    return self.run(name_tokens, debug_log, Step(
        cmd=[],
        cwd='',
        stdin=None,
        stdout='',
        stderr='',
        env={},
        luci_context={},
    ))

  def export_steps_ran(self):
    """Returns a dictionary of all steps run.

    This maps from the step's dot-name to dictionaries of:

      * name (str) - The step's dot-name
      * cmd (List[str]) - The command
      * cwd (str) - The current working directory
      * env (Dict[str, (str|None)]) - Mapping of direct environment
        replacements.
      * env_prefixes (Dict[str, List[str]]) - Mapping of direct environment
        replacements which should be joined at the beginning of the env key with
        os.pathsep.
      * env_suffixes (Dict[str, List[str]]) - Mapping of direct environment
        replacements which should be joined at the end of the env key with
        os.pathsep.
      * infra_step (bool) - If this step was intended to be an 'infra step' or
        not.
      * timeout (int) - The timeout, in seconds.
      * luci_context (Dict[str, Dict{...}]) - The luci_context data for this
        step.

    TODO(iannucci): Make this map to a real type.
    """
    return self._step_history.copy()
