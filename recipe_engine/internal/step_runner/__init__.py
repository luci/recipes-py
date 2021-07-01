# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import attr

from google.protobuf.message import Message

from ..attr_util import attr_list_type, attr_type, attr_dict_type
from ..stream import StreamEngine

from ...recipe_test_api import BaseTestData
from ...step_data import ExecutionResult


@attr.s(frozen=True)
class Step(object):
  """Step is the full definition of a step to run for a StepRunner."""
  # The full command line as a list of strings. cmd0 will be an absolute path to
  # an executable.
  cmd = attr.ib(validator=attr_list_type(str))

  # The absolute path for the step's current working directory.
  cwd = attr.ib(validator=attr_type(str))

  # File path or None. If None, stdin for the subprocess should be closed.
  stdin = attr.ib(validator=attr_type((str, type(None))))

  # File path, Stream or a file descriptor.
  #
  # Note that Streams may return a file .fileno() if they support subprocess
  # redirection. Otherwise the step runner implementation is expected to read
  # the output from the step and then write it into the Stream.
  stdout = attr.ib(validator=attr_type((str, StreamEngine.Stream)))
  stderr = attr.ib(validator=attr_type((str, StreamEngine.Stream)))

  # The full environment that this step should execute with.
  env = attr.ib(validator=attr_dict_type(str, str))

  # The sectionname->Message mapping of LUCI_CONTEXT modifications.
  luci_context = attr.ib(validator=attr_dict_type(str, Message))


class StepRunner(object):
  """A StepRunner is the interface to actually run steps and resolve
  placeholders.

  NONE of the methods in this class should raise exceptions. If they do, it will
  be treated as an Engine Crash and the whole recipe will be aborted (with
  appropriate logging, of course).
  """
  # pylint: disable=no-self-use
  # pylint: disable=unused-argument

  def register_step_config(self, name_token, step_config):
    """Called to register the precursor of the step (the StepConfig).

    Only used for the simulation API.

    TODO(iannucci): Change all step expectations to instead reflect the engine's
    intent (i.e. the Step object passed to `run`). Currently this is used to
    provide env_prefixes, env_suffixes as distinct from env. However, it may be
    "just fine" to instead only record env in the test expectations (i.e. using
    FakeEnviron as a basis environment).

    Args:
      * name_tokens (List[str]) - The full name of the step.
      * step_config (StepConfig) - The full precursor of the step.
    """
    pass

  def placeholder(self, name_tokens, placeholder):
    """Returns PlaceholderTestData for the given step and placeholder
    combination.

    Note: This may be called multiple times for the same step/placeholder
    combination. It should always return the same test data.

    Args:

      * name_tokens (List[str]) - The full name of the step.
      * placeholder (Placeholder) - The actual placeholder to resolve for.
        This may inspect the placeholder's namespaces and/or name.

    Returns PlaceholderTestData (or BaseTestData with enabled=False).
    """
    return BaseTestData(False)

  def handle_placeholder(self, name_tokens, handle_name):
    """Returns PlaceholderTestData for the given step and handle name
    combination.

    Note: This may be called multiple times for the same step/handle
    combination. It should always return the same test data.

    Args:
      * name_tokens (List[str]) - The full name of the step.
      * handle_name ('stdout'|'stderr'|'stdin') - The name of the handle we're
        inquiring for.

    Returns PlaceholderTestData (or BaseTestData with enabled=False).
    """
    return BaseTestData(False)

  def isabs(self, name_tokens, path):
    """Return True iff `path` is os.path.isabs."""
    return True

  def isdir(self, name_tokens, path):
    """Return True iff `path` is os.path.isdir."""
    return True

  def access(self, name_tokens, path, mode):
    """Return True iff `path` is os.access(path, mode)."""
    return True

  def resolve_cmd0(self, name_tokens, debug_log, cmd0, cwd, paths):
    """Should resolve the 0th argument of the command (`cmd0`) to an absolute
    path to the intended executable.

    Args:
      * name_tokens (List[str]) - The full name of the step.
      * debug_log (Stream) - The log where debugging information about the
        StepRunner's thought process should go.
      * cmd0 (str) - The executable to resolve. Note that this may be a relative
        path (e.g. './foo').
      * cwd (str) - The absolute cwd for the step.
      * paths (List[str]) - The current split value of $PATH.

    Returns the absolute path to the intended executable, if found, or None if
    it couldn't be discovered.
    """
    return cmd0

  def now(self):
    """Should return time.time().

    Used as the basis for adjusting the LUCI_CONTEXT['deadline'] section with
    the step's timeout.
    """
    raise NotImplementedError()

  def write_luci_context(self, section_values):
    """Writes a mapping of str->dict to disk (as a temp file), returning that
    path.

    `section_values` represents the 'diff' against LUCI_CONTEXT for the
    recipe engine process. The standard LUCI_CONTEXT merge rules should apply.
    """
    raise NotImplementedError()

  def run(self, name_tokens, debug_log, step):
    """Runs the step defined by step_config.

    Args:
      * name_tokens (List[str]) - The full name of the step.
      * debug_log (Stream) - The log where debugging information about the
        StepRunner's thought process should go.
      * step (Step) - The step to run.

    Returns recipe_engine.step_data.ExecutionResult.
    """
    raise NotImplementedError()

  def run_noop(self, name_tokens, debug_log):
    """Runs a no-op step.

    This may occur because the recipe needs to establish some step for UI
    purposes, but is also used for some recipes which run test steps without
    actual content (and so the simulations need an API point to return mocked
    ExecutionResult data).

    Args:
      * name_tokens (List[str]) - The full name of the step.
      * debug_log (Stream) - The log where debugging information about the
        StepRunner's thought process should go.

    Returns recipe_engine.step_data.ExecutionResult.
    """
    return ExecutionResult(retcode=0)
