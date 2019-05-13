# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import contextlib
import traceback

import attr

from ... import recipe_api
from ... import recipe_test_api

from .. import stream
from ..engine_env import FakeEnviron, merge_envs

from . import StepRunner, OpenStep
from . import construct_step_result, render_step



class SimulationStepRunner(StepRunner):
  """Pretends to run steps, instead recording what would have been run.

  This is the main workhorse of recipes.py simulation_test.  Returns the log of
  steps that would have been run in steps_ran.  Uses test_data to mock return
  values.
  """

  def __init__(self, stream_engine, test_data, annotator):
    self._test_data = test_data
    self._stream_engine = stream_engine
    self._annotator = annotator
    self._step_history = collections.OrderedDict()

  @property
  def stream_engine(self):
    return self._stream_engine

  def open_step(self, step_config):
    try:
      test_data_fn = step_config.step_test_data or recipe_test_api.StepTestData
      step_test = self._test_data.pop_step_test_data(step_config.name,
                                                     test_data_fn)
      rendered_step = render_step(step_config, step_test)

      # Merge our environment. Note that do NOT apply prefixes when rendering
      # expectations, as they are rendered independently.
      step_env, removed = merge_envs(
          FakeEnviron(), rendered_step.config.env, {}, {}, None)
      # We want envvar deletions to show up in the test expectations, so add
      # them back into step_env.
      step_env.update((k, None) for k in removed)

      rendered_step = rendered_step._replace(
          config=attr.evolve(rendered_step.config, env=step_env))
      step_config = None  # Make sure we use rendered step config.

      # Layer the simulation step on top of the given stream engine.
      step_stream = self._stream_engine.new_step_stream(rendered_step.config)
    except:
      with self.stream_engine.make_step_stream('Step Preparation Exception') as s:
        s.set_step_status('EXCEPTION')
        with s.new_log_stream('exception') as l:
          l.write_split(traceback.format_exc())
      raise

    class ReturnOpenStep(OpenStep):
      # pylint: disable=no-self-argument
      def run(inner):
        timeout = rendered_step.config.timeout
        if (timeout and step_test.times_out_after and
            step_test.times_out_after > timeout):
          raise recipe_api.StepTimeout(rendered_step.config.name, timeout)

        # Install a placeholder for order.
        self._step_history[rendered_step.config.name] = None
        return construct_step_result(rendered_step, step_test.retcode)

      def finalize(inner):
        rs = rendered_step

        # note that '~' sorts after 'z' so that this will be last on each
        # step. also use _step to get access to the mutable step
        # dictionary.
        buf = self._annotator.step_buffer(rs.config.name)
        lines = filter(None, buf.getvalue()).splitlines()
        # Only keep @@@annotation@@@ lines.
        lines = [stream.encode_str(x) for x in lines if x.startswith('@@@')]
        if lines:
          # This magically floats into step_history, which we have already
          # added step_config to.
          rs = rs._replace(followup_annotations=lines)
        step_stream.close()
        self._step_history[rs.config.name] = rs

      @property
      def stream(inner):
        return step_stream

    return ReturnOpenStep()

  @contextlib.contextmanager
  def run_context(self):
    try:
      yield
    except Exception as ex:
      with self._test_data.should_raise_exception(ex) as should_raise:
        if should_raise:
          raise

    assert_msg = (
        "Unconsumed test data for steps: %s. Ran the following steps "
        "(in order):\n%s" % (
            self._test_data.step_data.keys(),
            '\n'.join(repr(s) for s in self._step_history.keys())))
    if self._test_data.expected_exception:
      assert_msg += ", (exception %s)" % self._test_data.expected_exception
    assert self._test_data.consumed, assert_msg

  def _rendered_step_to_dict(self, rs):
    d = rs.config._asdict()
    if rs.followup_annotations:
      d['~followup_annotations'] = rs.followup_annotations
    return d

  @property
  def steps_ran(self):
    return collections.OrderedDict(
      (name, self._rendered_step_to_dict(rs))
      for name, rs in self._step_history.iteritems())


