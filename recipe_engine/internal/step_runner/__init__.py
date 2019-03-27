# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import contextlib
import itertools

from ... import util
from ...types import StepData


class StepRunner(object):
  """A StepRunner is the interface to actually running steps.

  These can actually make subprocess calls (SubprocessStepRunner), or just
  pretend to run the steps with mock output (SimulationStepRunner).
  """
  @property
  def stream_engine(self):
    """Return the stream engine that this StepRunner uses, if meaningful.

    Users of this method must be prepared to handle None.
    """
    return None

  def open_step(self, step_config):
    """Constructs an OpenStep object which can be used to actually run a step.

    Args:
      step_config (StepConfig): The step data.

    Returns: an OpenStep object.
    """
    raise NotImplementedError()

  @contextlib.contextmanager
  def run_context(self):
    """A context in which the entire engine run takes place.

    This is typically used to catch exceptions thrown by the recipe.
    """
    yield


class OpenStep(object):
  """An object that can be used to run a step.

  We use this object instead of just running directly because, after a step
  is run, it stays open (can be modified with step_text and links and things)
  until another step at its nest level or lower is started.
  """
  def run(self):
    """Starts the step, running its command."""
    raise NotImplementedError()

  def finalize(self):
    """Closes the step and finalizes any stored presentation."""
    raise NotImplementedError()

  @property
  def stream(self):
    """The stream.StepStream that this step is using for output.

    It is permitted to use this stream between run() and finalize() calls. """
    raise NotImplementedError()


# Placeholders associated with a rendered step.
Placeholders = collections.namedtuple('Placeholders',
    ('inputs_cmd', 'outputs_cmd', 'stdout', 'stderr', 'stdin'))

# Result of 'render_step'.
#
# Fields:
#   config (StepConfig): The step configuration.
#   placeholders (Placeholders): Placeholders for this rendered step.
#   followup_annotations (list): A list of followup annotation, populated during
#       simulation test.
RenderedStep = collections.namedtuple('RenderedStep',
    ('config', 'placeholders', 'followup_annotations'))


# Singleton object to indicate a value is not set.
UNSET_VALUE = object()


def render_step(step_config, step_test):
  """Renders a step so that it can be fed to annotator.py.

  Args:
    step_config (StepConfig): The step config to render.
    step_test: The test data json dictionary for this step, if any.
               Passed through unaltered to each placeholder.

  Returns (RenderedStep): the rendered step, including a Placeholders object
      representing any placeholder instances that were found while rendering.
  """
  # Process 'cmd', rendering placeholders there.
  input_phs = collections.defaultdict(lambda: collections.defaultdict(list))
  output_phs = collections.defaultdict(
      lambda: collections.defaultdict(collections.OrderedDict))
  new_cmd = []
  for item in (step_config.cmd or ()):
    if isinstance(item, util.Placeholder):
      module_name, placeholder_name = item.namespaces
      tdata = step_test.pop_placeholder(
          module_name, placeholder_name, item.name)
      new_cmd.extend(item.render(tdata))
      if isinstance(item, util.InputPlaceholder):
        input_phs[module_name][placeholder_name].append((item, tdata))
      else:
        assert isinstance(item, util.OutputPlaceholder), (
            'Not an OutputPlaceholder: %r' % item)
        # This assert ensures that:
        #   no two placeholders have the same name
        #   at most one placeholder has the default name
        assert item.name not in output_phs[module_name][placeholder_name], (
            'Step "%s" has multiple output placeholders of %s.%s. Please '
            'specify explicit and different names for them.' % (
              step_config.name, module_name, placeholder_name))
        output_phs[module_name][placeholder_name][item.name] = (item, tdata)
    else:
      new_cmd.append(item)
  step_config = step_config._replace(cmd=map(str, new_cmd))

  # Process 'stdout', 'stderr' and 'stdin' placeholders, if given.
  stdio_placeholders = {}
  for key in ('stdout', 'stderr', 'stdin'):
    placeholder = getattr(step_config, key)
    tdata = None
    if placeholder:
      if key == 'stdin':
        assert isinstance(placeholder, util.InputPlaceholder), (
            '%s(%r) should be an InputPlaceholder.' % (key, placeholder))
      else:
        assert isinstance(placeholder, util.OutputPlaceholder), (
            '%s(%r) should be an OutputPlaceholder.' % (key, placeholder))
      tdata = getattr(step_test, key)
      placeholder.render(tdata)
      assert placeholder.backing_file is not None
      step_config = step_config._replace(**{key:placeholder.backing_file})
    stdio_placeholders[key] = (placeholder, tdata)

  return RenderedStep(
      config=step_config,
      placeholders=Placeholders(
          inputs_cmd=input_phs,
          outputs_cmd=output_phs,
          **stdio_placeholders),
      followup_annotations=None,
  )


def construct_step_result(rendered_step, retcode):
  """Constructs a StepData step result from step return data.

  The main purpose of this function is to add output placeholder results into
  the step result where output placeholders appeared in the input step.
  Also give input placeholders the chance to do the clean-up if needed.
  """
  step_result = StepData(rendered_step.config, retcode)

  class BlankObject(object):
    pass

  # Input placeholders inside step |cmd|.
  placeholders = rendered_step.placeholders
  for _, pholders in placeholders.inputs_cmd.iteritems():
    for _, items in pholders.iteritems():
      for ph, td in items:
        ph.cleanup(td.enabled)

  # Output placeholders inside step |cmd|.
  for module_name, pholders in placeholders.outputs_cmd.iteritems():
    assert not hasattr(step_result, module_name)
    o = BlankObject()
    setattr(step_result, module_name, o)

    for placeholder_name, instances in pholders.iteritems():
      named_results = {}
      default_result = UNSET_VALUE
      for _, (ph, td) in instances.iteritems():
        result = ph.result(step_result.presentation, td)
        if ph.name is None:
          default_result = result
        else:
          named_results[ph.name] = result
      setattr(o, placeholder_name + "s", named_results)

      if default_result is UNSET_VALUE and len(named_results) == 1:
        # If only 1 output placeholder with an explicit name, we set the default
        # output.
        default_result = named_results.values()[0]

      # If 2+ placeholders have explicit names, we don't set the default output.
      if default_result is not UNSET_VALUE:
        setattr(o, placeholder_name, default_result)

  # Placeholders that are used with IO redirection.
  for key in ('stdout', 'stderr', 'stdin'):
    assert not hasattr(step_result, key)
    ph, td = getattr(placeholders, key)
    if ph:
      if isinstance(ph, util.OutputPlaceholder):
        setattr(step_result, key, ph.result(step_result.presentation, td))
      else:
        assert isinstance(ph, util.InputPlaceholder), (
            '%s(%r) should be an InputPlaceholder.' % (key, ph))
        ph.cleanup(td.enabled)

  return step_result


class FakeEnviron(object):
  """This is a fake dictionary which is meant to emulate os.environ strictly for
  the purposes of interacting with _merge_envs.

  It supports:
    * Any key access is answered with <key>, allowing this to be used as
      a % format argument.
    * Deleting/setting items sets them to None/value, appropriately.
    * `in` checks always returns True
    * copy() returns self

  The 'formatted' result can be obtained by looking at .data.
  """
  def __init__(self):
    self.data = {}

  def __getitem__(self, key):
    return '<%s>' % key

  def get(self, key, default=None):
    return self[key]

  def keys(self):
    return self.data.keys()

  def pop(self, key, default=None):
    result = self.data.get(key, default)
    self.data[key] = None
    return result

  def __delitem__(self, key):
    self.data[key] = None

  def __contains__(self, key):
    return True

  def __setitem__(self, key, value):
    self.data[key] = value

  def copy(self):
    return self


def merge_envs(original, overrides, prefixes, suffixes, pathsep):
  """Merges two environments.

  Returns a new environment dict with entries from |override| overwriting
  corresponding entries in |original|. Keys whose value is None will completely
  remove the environment variable. Values can contain %(KEY)s strings, which
  will be substituted with the values from the original (useful for amending, as
  opposed to overwriting, variables like PATH).

  See StepConfig for environment construction rules.
  """
  result = original.copy()
  subst = (original if isinstance(original, FakeEnviron)
           else collections.defaultdict(lambda: '', **original))

  if not any((prefixes, suffixes, overrides)):
    return result

  merged = set()
  for k in set(suffixes).union(prefixes):
    pfxs = prefixes.get(k, ())
    sfxs = suffixes.get(k, ())
    if not (pfxs or sfxs):
      continue

    # If the same key is defined in "overrides", we need to incorporate with it.
    # We'll do so here, and skip it in the "overrides" construction.
    merged.add(k)
    if k in overrides:
      val = overrides[k]
      if val is not None:
        val = str(val) % subst
    else:
      # Not defined. Append "val" iff it is defined in "original" and not empty.
      val = original.get(k, '')
    if val:
      pfxs += (val,)
    result[k] = pathsep.join(
      str(v) for v in itertools.chain(pfxs, sfxs))

  for k, v in overrides.iteritems():
    if k in merged:
      continue
    if v is None:
      result.pop(k, None)
    else:
      result[k] = str(v) % subst
  return result
