# Copyright 2016 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import attr

from google.protobuf import json_format as jsonpb

from PB.go.chromium.org.luci.lucictx import sections as sections_pb

from ... import engine_types
from ... import recipe_test_api
from ... import step_data
from ... import util
from ...third_party import luci_context

from .. import engine_env
from .. import engine_step
from .. import global_shutdown
from .. import step_runner
from .. import stream


class SimulationStepRunner(step_runner.StepRunner):
  """Pretends to run steps, instead recording what would have been run.

  This is the main workhorse of recipes.py simulation_test.  Returns the log of
  steps that would have been run in steps_ran.  Uses test_data to mock return
  values.
  """

  def __init__(self, test_data: recipe_test_api.TestData) -> None:
    self._test_data = test_data

    # dot-name -> StepTestData
    self._used_steps: dict[str, recipe_test_api.StepTestData] = {}

    # (dot-name, namespace, name) -> PlaceholderTestData
    self._used_placeholders: dict[
        tuple[str, ...], recipe_test_api.PlaceholderTestData
    ] = {}

    # (dot-name, handle_name) -> PlaceholderTestData
    self._used_handle_placeholders: dict[
        tuple[str, str], recipe_test_api.PlaceholderTestData
    ] = {}

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
    self._step_precursor_data: dict[str, dict[str, Any]] = {}

    # dot-name -> Step
    self._step_history: dict[str, dict[str, Any]] = {}

  def register_step_config(
      self, name_tokens: Sequence[str], step_config: engine_step.StepConfig
  ) -> None:
    dot_name = '.'.join(name_tokens)

    # This moves the test data from _test_data to _used_steps. This will return
    # StepData() if `dot_name` isn't in self._test_data.
    self._used_steps[dot_name] = self._test_data.pop_step_test_data(
        dot_name,
        step_config.step_test_data or recipe_test_api.StepTestData,
    )

    if self._used_steps[dot_name].global_shutdown_event == 'before':
      global_shutdown.GLOBAL_SHUTDOWN.set()

    self._step_precursor_data[dot_name] = {
      'env_prefixes': step_config.env_prefixes.mapping,
      'env_suffixes': step_config.env_suffixes.mapping,
      'env': {
        k: v for k, v in step_config.env.items()
        # Trim out LUCI_CONTEXT because it's useless information in tests, since
        # the entire luci_context data is included in the test output.
        if k.upper() != luci_context.ENV_KEY
      },
      'timeout': step_config.timeout,
      'infra_step': step_config.infra_step,
      'allow_subannotations': step_config.allow_subannotations,
    }

    if step_config.cost != engine_types.ResourceCost():
      self._step_precursor_data[dot_name]['cost'] = step_config.cost

  def placeholder(
      self, name_tokens: Sequence[str], placeholder: util.Placeholder
  ) -> recipe_test_api.PlaceholderTestData:
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

  def handle_placeholder(
      self, name_tokens: Sequence[str], handle_name: str
  ) -> recipe_test_api.PlaceholderTestData:
    dot_name = '.'.join(name_tokens)

    key = (dot_name, handle_name)
    if key not in self._used_placeholders:
      self._used_placeholders[key] = getattr(
          self._used_steps[dot_name], handle_name)
    return self._used_placeholders[key]

  def now(self) -> float:
    # Note that we COULD coordinate with some simulatable time system (e.g. the
    # recipe_engine/time module)... however this is just used for adjusting
    # the soft_deadline in LUCI_CONTEXT['deadline'] prior to invoking
    # write_luci_context where the simulation currently discards it anyway.
    return 0

  def write_luci_context(self, section_values: Mapping[str, Any]) -> str:
    # We ignore this environment variable anyway.
    return ""

  def run(
      self,
      name_tokens: Sequence[str],
      debug_log: stream.StreamEngine.Stream,
      step: step_runner.Step,
  ) -> step_data.ExecutionResult:
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
      for name, section in step.luci_context.items():
        if name == 'deadline':
          # This is the default deadline and is fully specified by the
          # `timeout` parameter below. To avoid blowing out expectations, we
          # omit the section.
          default_deadline = sections_pb.Deadline(
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
      fake_env = engine_env.FakeEnviron()
      step_obj['env'] = {
        k: (v if v is None else v % fake_env)
        for k, v in precursor['env'].items()
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
    if not step.cmd and tdata.retcode:
      # If you're here, it means that you had recipe code which ran a step with
      # no command at all (e.g. None or []). These sorts of steps are 'display
      # only' and will never have a non-0 exit code when the recipe runs in
      # production (on a builder, etc.).
      #
      # If the intent of the code was just to have a step that raises an
      # exception, use `api.step.empty` with the `status` kwarg set, which will
      # make a display-only step, and also raise an appropriate exception.
      #
      # If the intent of the code was to have a step which can sometimes fail
      # for tests, change this step to actually run a real command, or pick
      # a real step to simulate a non-zero return code for.
      #
      # See CL https://chromium-review.googlesource.com/c/4972935.
      raise ValueError(
          f'Cannot simulate no-op step {"|".join(name_tokens)!r} with a retcode'
          ' other than 0. To simulate a step with a retcode, make it real'
          ' (e.g. give it a command). To just have a step which displays with'
          ' an error, use `api.step.empty()`.')

    if tdata.global_shutdown_event == 'after':
      global_shutdown.GLOBAL_SHUTDOWN.set()

    if tdata.times_out_after and precursor['timeout']:
      if tdata.times_out_after > precursor['timeout']:
        return step_data.ExecutionResult(had_timeout=True)

    if tdata.cancel:
      return step_data.ExecutionResult(was_cancelled=True, retcode=tdata.retcode)

    return step_data.ExecutionResult(retcode=tdata.retcode or 0)

  def run_noop(
      self,
      name_tokens: Sequence[str],
      debug_log: stream.StreamEngine.Stream,
  ) -> step_data.ExecutionResult:
    return self.run(name_tokens, debug_log, step_runner.Step(
        cmd=[],
        cwd='',
        stdin=None,
        stdout='',
        stderr='',
        env={},
        luci_context={},
    ))

  def export_steps_ran(self) -> dict[str, dict[str, Any]]:
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
