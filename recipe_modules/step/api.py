# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Step is the primary API for running steps (external programs, scripts,
etc.)."""

import contextlib
import sys
import types
import multiprocessing

import enum

from recipe_engine import recipe_api
from recipe_engine.config_types import Path
from recipe_engine.types import StepPresentation
from recipe_engine.types import ResourceCost as _ResourceCost
from recipe_engine.util import Placeholder, sentinel


# Inherit from RecipeApiPlain because the only thing which is a step is
# run_from_dict()
class StepApi(recipe_api.RecipeApiPlain):
  step_client = recipe_api.RequireClient('step')

  def __init__(self, step_properties, **kwargs):
    super(StepApi, self).__init__(**kwargs)
    self._prefix_path = step_properties.get('prefix_path', [])

  EXCEPTION = 'EXCEPTION'
  FAILURE = 'FAILURE'
  SUCCESS = 'SUCCESS'
  WARNING = 'WARNING'

  def ResourceCost(self, cpu=500, memory=50, disk=0, net=0):
    """A structure defining the resources that a given step may need.

    The four resources are:

      * cpu (measured in millicores) - The amount of cpu the step is expected to
        take. Defaults to 500.
      * memory (measured in MB) - The amount of memory the step is expected to
        take. Defaults to 50.
      * disk (as percentage of max disk bandwidth) - The amount of "disk
        bandwidth" the step is expected to take. This is a very simplified
        percentage covering IOPS, read/write bandwidth, seek time, etc. At 100,
        the step will run exclusively w.r.t. all other steps having a `disk`
        cost. At 0, the step will run regardless of other steps with disk cost.
      * net (as percentage of max net bandwidth) - The amount of "net
        bandwidth" the step is expected to take. This is a very simplified
        percentage covering bandwidth, latency, etc. and is indescriminate of
        the remote hosts, network conditions, etc. At 100, the step will run
        exclusively w.r.t. all other steps having a `net` cost. At 0, the step
        will run regardless of other steps with net cost.

    A step will run when ALL of the resouces are simultaneously available. The
    Recipe Engine currently uses a greedy scheduling algorithm for picking the
    next step to run. If multiple steps are waiting for resources, this will
    pick the largest (cpu, memory, disk, net) step which fits the currently
    available resources and run that. The theory is that, assuming:

      * Recipes are finite tasks, which aim to run ALL of their steps, and want
        to do so as quickly as possible. This is not a typical OS scheduling
        scenario where there's some window of time over which the recipe needs
        to be 'fair'. Additionally, recipes run with finite timeouts attached.
      * The duration of a given step is the same regardless of when during the
        build it runs (i.e. running a step now vs later should take roughly the
        same amount of time).

    It's therefore optimal to run steps as quickly as possible, to avoid wasting
    the timeout attached to the build.

    Note that `bool(ResourceCost(...))` is defined to be True if the
    ResourceCost has at least one non-zero cost, and False otherwise.

    Args:
      * cpu (int) - Millicores that this step will take to run. See `MAX_CPU`
      helper. A value higher than the maximum number of millicores on the system
      is equivalent to `MAX_CPU`.
      * memory (int) - Number of Mebibytes of memory this step will take to run.
      See `MAX_MEMORY` as a helper. A value higher than the maximum amount of
      memory on the system is equivalent to `MAX_MEMORY`.
      * disk (int [0..100]) - The disk IO resource this step will take as
      a percentage of the maximum system disk IO.
      * net (int [0..100]) - The network IO resource this step will take as
      a percentage of the maximum system network IO.

    Returns a ResourceCost suitable for use with `api.step(...)`'s cost kwarg.
    Note that passing `None` to api.step for the cost kwarg is equivalent to
    `ResourceCost(0, 0, 0, 0)`.
    """
    return _ResourceCost(
        min(cpu, self.MAX_CPU),
        min(memory, self.MAX_MEMORY),
        disk,
        net)

  # The number of millicores in a single CPU core.
  CPU_CORE = 1000

  @property
  def MAX_CPU(self):
    """Returns the maximum number of millicores this system has."""
    return self.m.platform.cpu_count * self.CPU_CORE

  @property
  def MAX_MEMORY(self):
    """Returns the maximum amount of memory on the system in MB."""
    return self.m.platform.total_memory

  @property
  def StepFailure(self):
    """This is the base Exception class for all step failures.

    It can be manually raised from recipe code to cause the build to turn red.

    Usage:
      * `raise api.StepFailure("some reason")`
      * `except api.StepFailure:`
    """
    return recipe_api.StepFailure

  @property
  def StepWarning(self):
    """StepWarning is a subclass of StepFailure, and will translate to a yellow
    build."""
    return recipe_api.StepWarning

  @property
  def InfraFailure(self):
    """InfraFailure is a subclass of StepFailure, and will translate to a purple
    build.

    This exception is raised from steps which are marked as `infra_step`s when
    they fail.
    """
    return recipe_api.InfraFailure

  @property
  def active_result(self):
    """The currently active (open) result from the last step that was run. This
    is a `step_data.StepData` object.

    Allows you to do things like:
    ```python
    try:
      api.step('run test', [..., api.json.output()])
    finally:
      result = api.step.active_result
      if result.json.output:
        new_step_text = result.json.output['step_text']
        api.step.active_result.presentation.step_text = new_step_text
    ```

    This will update the step_text of the test, even if the test fails. Without
    this api, the above code would look like:

    ```python
    try:
      result = api.step('run test', [..., api.json.output()])
    except api.StepFailure as f:
      result = f.result
      raise
    finally:
      if result.json.output:
        new_step_text = result.json.output['step_text']
        api.step.active_result.presentation.step_text = new_step_text
    ```
    """
    return self.step_client.previous_step_result()

  def close_non_nest_step(self):
    """Call this to explicitly terminate the currently open non-nest step.

    After calling this, api.step.active_step will return the current nest step
    context (if any).

    No-op if there's no currently active non-nest step.
    """
    return self.step_client.close_non_parent_step()

  # TODO(iannucci): Historically `nest` returned a StepData; there's tons of
  # code which does:
  #
  #    with api.step.nest(...) as nest:
  #      nest.presentation....
  #
  # But we want this code to be:
  #
  #    with api.step.nest(...) as presentation:
  #      presentation....
  #
  # To make migration smoother, we yield a hacky object which passes through
  # everything to the real presentation, except for `.presentation` which
  # returns the StepPresentation directly. Ick.
  class _StepPresentationProxy(object):
    def __init__(self, presentation):
      object.__setattr__(self, 'presentation', presentation)

    def __getattr__(self, name):
      return getattr(self.presentation, name)

    def __setattr__(self, name, value):
      setattr(self.presentation, name, value)

  @contextlib.contextmanager
  def nest(self, name, status='worst'):
    """Nest allows you to nest steps hierarchically on the build UI.

    This generates a dummy step with the provided name in the current namespace.
    All other steps run within this `with` statement will be nested inside of
    this dummy step. Nested steps can also nest within each other.

    The presentation for the dummy step can be updated (e.g. to add step_text,
    step_links, etc.) or set the step's status. If you do not set the status,
    it will be calculated from the status' of all the steps run within this one
    according to the `status` algorithm selected.
      1. If there's an active exception when leaving the `with` statement, the
         status will be one of FAILUR, WARNING or EXCEPTION (depending on the
         type of exception).
      2. Otherwise:
         1. If the status algorithm is 'worst', it will assume the status of the
            worst child step. This is useful for when your nest step runs e.g.
            a bunch of test shards. If any shard fails, you want the nest step
            to fail as well.
         2. If the status algorithm is 'last', it will assume the status of the
            last child step. This is useful for when you're using the nest step
            to encapsulate a sequence operation where only the last step's
            status really matters.

    Example:

        # status='worst'
        with api.step.nest('run test'):
          with api.step.defer_results():
            for shard in xrange(4):
              run_shard('test', shard)

        # status='last'
        with api.step.nest('do upload'):
          for attempt in xrange(4):
            try:
              do_upload()  # first one fails, but second succeeds.
            except api.step.StepFailure:
              pass
          else:
            report_error()

        # manually adjust status
        with api.step.nest('custom thing') as presentation:
          # stuff!
          presentation.status = 'FAILURE'  # or whatever

    NOTE/DEPRECATION: The object yielded also has a '.presentation' field to be
    compatible with code that treats the yielded object as a StepData object. If
    you see such code, please updaet it to treat the yielded object directly as
    StepPresentation instead.

    Args:

      * name (str) - The name of this step.
      * status ('worst'|'last') - The algorithm to use to pick a
        `presentation.status` if the recipe doesn't set one explicitly.

    Yields a StepPresentation for this dummy step, which you may update as you
    please.
    """
    assert status in ('worst', 'last'), 'Got bad status: %r' % (status,)

    with self.step_client.parent_step(name) as (pres, children):
      caught_exc = None
      try:
        yield self._StepPresentationProxy(pres)
      except:
        caught_exc = sys.exc_info()[0]
        raise
      finally:
        # If they didn't set a presentation.status, calculate one.
        if pres.status is None:
          if caught_exc:
            pres.status = {
              recipe_api.StepFailure: self.FAILURE,
              recipe_api.StepWarning: self.WARNING,
            }.get(caught_exc, self.EXCEPTION)
          elif children:
            if status == 'worst':
              worst = self.SUCCESS
              for child in children:
                worst = StepPresentation.status_worst(
                    worst, child.presentation.status)
              pres.status = worst
            else:
              pres.status = children[-1].presentation.status
          else:
            pres.status = self.SUCCESS

  @property
  def defer_results(self):
    """ See recipe_api.py for docs. """
    return recipe_api.defer_results

  @recipe_api.composite_step
  def __call__(self, name, cmd, ok_ret=(0,), infra_step=False, wrapper=(),
               timeout=None, allow_subannotations=None,
               trigger_specs=None, stdout=None, stderr=None, stdin=None,
               step_test_data=None, cost=_ResourceCost()):
    """Returns a step dictionary which is compatible with annotator.py.

    Args:

      * name (string): The name of this step.
      * cmd (List[int|string|Placeholder|Path]): The program arguments to run.
        * Numbers and strings are used as-is.
        * Placeholders are 'rendered' to a string (using their render() method).
          Placeholders are e.g. `api.json.input()` or `api.raw_io.output()`.
          Typically rendering these turns into an absolute path to a file on
          disk, which the program is expected to read from/write to.
        * Paths are rendered to an OS-native absolute path.
      * ok_ret (tuple or set of ints, 'any', 'all'): allowed return codes. Any
        unexpected return codes will cause an exception to be thrown. If you
        pass in the value 'any' or 'all', the engine will allow any return code
        to be returned. Defaults to {0}.
      * infra_step: Whether or not this is an infrastructure step.
        Infrastructure steps will place the step in an EXCEPTION state and raise
        InfraFailure.
      * wrapper: If supplied, a command to prepend to the executed step as a
        command wrapper.
      * timeout: If supplied, the recipe engine will kill the step after the
        specified number of seconds.
      * allow_subannotations (bool): if True, lets the step emit its own
          annotations. NOTE: Enabling this can cause some buggy behavior. Please
          strongly consider using step_result.presentation instead. If you have
          questions, please contact infra-dev@chromium.org.
      * trigger_specs: a list of trigger specifications
      * stdout: Placeholder to put step stdout into. If used, stdout won't
        appear in annotator's stdout (and |allow_subannotations| is ignored).
      * stderr: Placeholder to put step stderr into. If used, stderr won't
        appear in annotator's stderr.
      * stdin: Placeholder to read step stdin from.
      * step_test_data (func -> recipe_test_api.StepTestData): A factory which
          returns a StepTestData object that will be used as the default test
          data for this step. The recipe author can override/augment this object
          in the GenTests function.
      * cost (None|ResourceCost) - The estimated system resource cost of this
        step. See `ResourceCost()`. The recipe_engine will prevent more than the
        machine's maximum resources worth of steps from running at once (i.e.
        steps will wait until there's enough resource available before
        starting). Waiting suprocesses are unblocked in capacitiy-available
        order. This means it's possible for pending tasks with large
        requirements to 'starve' temporarially while other smaller cost tasks
        run in parallel. Equal-weight tasks will start in FIFO order. Steps
        with a cost of None will NEVER wait (which is the equivalent of
        `ResourceCost()`). Defaults to `ResourceCost(cpu=500, memory=50)`.

    Returns a `step_data.StepData` for the running step.
    """
    assert isinstance(cmd, (types.NoneType, list))
    if cmd is not None:
      cmd = list(wrapper) + cmd
      for x in cmd:
        if not isinstance(x, (int, long, basestring, Path, Placeholder)):
          raise AssertionError('Type %s is not permitted. '
                               'cmd is %r' % (type(x), cmd))

    if cost is None:
      cost = _ResourceCost.zero()
    assert isinstance(cost, _ResourceCost), (
      'cost must be a ResourceCost or None, got %r' % (cost,))

    cwd = self.m.context.cwd
    if cwd and cwd == self.m.path['start_dir']:
      cwd = None
    elif cwd is not None:
      cwd = str(cwd)

    with self.m.context(env_prefixes={'PATH': self._prefix_path}):
      env_prefixes = self.m.context.env_prefixes

    if ok_ret in ('any', 'all'):
      ok_ret = self.step_client.StepConfig.ALL_OK

    return self.step_client.run_step(self.step_client.StepConfig(
        name=name,
        cmd=cmd or (),
        cost=cost,
        cwd=cwd,
        env=self.m.context.env,
        env_prefixes=self.step_client.EnvAffix(
          mapping={
            k: map(str, vs)
            for k, vs in env_prefixes.iteritems()
          },
          pathsep=self.m.path.pathsep,
        ),
        env_suffixes=self.step_client.EnvAffix(
          mapping={
            k: map(str, vs)
            for k, vs in self.m.context.env_suffixes.iteritems()
          },
          pathsep=self.m.path.pathsep,
        ),
        allow_subannotations=bool(allow_subannotations),
        trigger_specs=[self._make_trigger_spec(trig)
                       for trig in (trigger_specs or ())],
        timeout=timeout,
        infra_step=self.m.context.infra_step or bool(infra_step),
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        ok_ret=ok_ret,
        step_test_data=step_test_data,
    ))

  def _make_trigger_spec(self, trig):
    critical = trig.get('critical')
    return self.step_client.TriggerSpec(
        builder_name=trig['builder_name'],

        bucket=trig.get('bucket', ''),
        properties=trig.get('properties', {}),
        buildbot_changes=trig.get('buildbot_changes', []),
        tags=trig.get('tags', ()),
        critical=bool(critical) if critical is not None else (True),
    )
