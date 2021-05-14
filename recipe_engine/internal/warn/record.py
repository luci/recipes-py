# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""record warnings during recipe executions."""

import os
import types

from collections import defaultdict

import attr

from future.utils import iteritems, itervalues

from .cause import CallSite, Frame, ImportSite
from .escape import escape_warning_predicate

from ..attr_util import attr_type, attr_seq_type
from ..class_util import cached_property
from ..recipe_deps import Recipe, RecipeDeps, RecipeModule

from ...types import FrozenDict
from ...util import sentinel


# The sentinel that instructs recipe engine not to record warnings.
NULL_WARNING_RECORDER = sentinel('NULL_WARNING_RECORDER',
    recorded_warnings=FrozenDict(),
    record_execution_warning=(lambda _self, _name, _frames: None),
    record_import_warning=(lambda _self, _name, _importer: None),
)


@attr.s(frozen=True, slots=True)
class _AnnotatedFrame(object):
  """A wrapper class over built-in frame which associates additional attributes
  with the wrapped frame.
  """
  # The wrapped frame
  frame = attr.ib(validator=attr_type(types.FrameType))

  # If set, the human-readable reason why the wrapped frame is skipped for the
  # purposes of warning attribution. Examples:
  #   * 'user escape at /path/to/file:123
  #   * 'python built-in'
  skip_reason = attr.ib(validator=attr.validators.optional(attr_type(str)))

@attr.s
class WarningRecorder(object):
  """A WarningRecorder records and analyzes warnings, preserves all unique
  causes for a given warning.

  There're two types of warnings; Execution warnings and Import warnings:
    * Execution Warning: issued within the execution of recipe code.
    * Import Warning: issued during dependency resolution (DEPS), when a recipe
      or recipe module depends on a module with warning declared.
  """
  # The RecipeDeps object for current recipe execution.
  recipe_deps = attr.ib(validator=attr_type(RecipeDeps))

  # Filter function that all execution warnings will be filtered through
  # before storing. If the function returns False, the warning will be
  # discarded. The function takes following two arguments and returns a bool.
  #   * name (str) - Fully qualified warning name e.g. 'repo/WARNING_NAME'
  #   * cause (warning_pb.Cause) - Cause of the warning
  call_site_filter = attr.ib(default=lambda name, cause: True)

  # Same functionality and function signature as call_site_filter but applies
  # to import warnings.
  import_site_filter = attr.ib(default=lambda name, cause: True)

  # Boolean tells whether to perserve entire call stack for execution warning
  # or not.
  include_call_stack = attr.ib(validator=attr_type(bool), default=False)

  # Internal holder for recorded warnings.
  # key: fully qualified warning name (str)
  # value: Set[CallSite|ImportSite] (defined in cause.py, not the proto message)
  _recorded_warnings = attr.ib(init=False, factory=lambda: defaultdict(set))

  @property
  def recorded_warnings(self):
    """Returns all recorded warnings in the form of

    {
      "repo_name_1/WARNING_NAME_1": Tuple[warning_pb.Cause]
      "repo_name_2/WARNING_NAME_2": Tuple[warning_pb.Cause]
    }

    cause inside the tuple is guaranteed to be unique for each warning.
    """
    return {
      name: tuple(site.cause_pb for site in sites)
      for (name, sites) in iteritems(self._recorded_warnings)
    }

  def record_execution_warning(self, name, frames):
    """Record the warning issued during recipe execution and its cause (
    warning_pb.CallSite). A frame will be attributed as call site frame if it
    is the first frame in the supplied frames matching the following
    conditions:
      * The source code of the frame is 'recipe code' (i.e. in the current
        recipe repo or one of its dependencies).
      * The function that the frame executes is not escaped from the issued
        warning.

    Args:
      * name (str): Fully qualified warning name (e.g. repo_name/WARNING_NAME).
      * frames (List[Frame]): List of frames captured at the time the given
        warning is issued.
    """
    self._validate_warning_name(name)
    # TODO(yiwzhang): update proto to include skip reason and populate
    call_site_frame, _ = self._attribute_call_site(name, frames)
    call_site = CallSite(
      site=Frame.from_built_in_frame(call_site_frame) if (
        call_site_frame) else Frame(),
    )
    if self.include_call_stack or not call_site_frame:
      # Capture call stack if explicitly requested or attributing call site
      # fails
      call_site = attr.evolve(
        call_site,
        call_stack=[Frame.from_built_in_frame(f) for f in frames]
      )
    if (call_site not in self._recorded_warnings[name]) and (
      self.call_site_filter(name, call_site.cause_pb)):
      self._recorded_warnings[name].add(call_site)

  def record_import_warning(self, name, importer):
    """Record the warning issued during DEPS resolution and its cause (
    warning_pb.ImportSite).

    Args:
      * name (str): Fully qualified warning name (e.g. repo_name/WARNING_NAME).
      * importer (Recipe|RecipeModule): The recipe or recipe module which
        depends on a recipe module with given warning name declared.

    Raise ValueError if the importer is not instance of Recipe or RecipeModule
    """
    self._validate_warning_name(name)
    if not isinstance(importer, (Recipe, RecipeModule)):
      raise ValueError(
        "Expect importer to be either type %s or %s. Got %s" % (
          RecipeModule.__name__, Recipe.__name__, type(importer)))
    import_site = ImportSite(
      repo=importer.repo.name,
      module=importer.name if isinstance(importer, RecipeModule) else None,
      recipe=importer.name if isinstance(importer, Recipe) else None,
    )
    if (import_site not in self._recorded_warnings[name]) and (
        self.import_site_filter(name, import_site.cause_pb)):
        self._recorded_warnings[name].add(import_site)

  def _validate_warning_name(self, name):
    """Checks whether the given warning name is fully-qualified and defined in
    the recipe repo.
    """
    if '/' not in name:
      raise ValueError('expected fully-qualified warning name, got %s' % name)
    if name not in self.recipe_deps.warning_definitions:
      repo, warning = name.split('/', 1)
      raise ValueError(
          'warning "%s" is not defined in recipe repo %s' % (warning, repo))

  @cached_property
  def _skip_frame_predicates(self):
    """A tuple of predicate functions to decide whether or not to skip a given
    frame for warning attribution. The predicates are connected with logic OR,
    meaning that if one of the predicates says to skip, the frame will be
    skipped. A predicate function will have signature as follows.

    Args:
      * name (str) - Fully qualified warning name e.g. 'repo/WARNING_NAME'.
      * frame (types.FrameType) - A frame in call stack that the predicate
        function is currently evaluating against.

    Returns a human-readable reason (str) why the given frame should be skipped.
    Returns None if the warning can be attributed to the given frame.
    """
    return (
      self._non_recipe_code_predicate,
      escape_warning_predicate
    )

  def _attribute_call_site(self, name, frames):
    """Walk up the given stack frames and attribute the first non-skipped frame
    as call site. self._skip_frame_predicates is used to decide whether to skip
    a frame or not.

    Returns a tuple of (frame, List[AnnotatedFrames]) where frame is the
    attributed call site and the annotated frames in the list are all skipped
    frames with their skipped reasons. Call site frame will be returned as None
    if all of the frames are skipped.
    """
    skipped_frames = []
    for frame in frames:
      lazy_skip_reasons = (p(name, frame) for p in self._skip_frame_predicates)
      reason = next((r for r in lazy_skip_reasons if r is not None), None)
      if reason is None:
        return frame, skipped_frames # culprit found
      skipped_frames.append(_AnnotatedFrame(frame=frame, skip_reason=reason))
    return None, skipped_frames

  @cached_property
  def _all_repo_paths(self):
    """A tuple of root paths of all recipe repos in the current executing
    recipe deps.
    """
    return tuple(repo.recipes_root_path for repo in (
      list(itervalues(self.recipe_deps.repos))))

  def _non_recipe_code_predicate(self, _name, frame):
    """A predicate that skips a frame when it is executing a code object whose
    source is not in any of the recipe repos in the currently executing
    recipe_deps.
    """
    code_file_path = os.path.abspath(frame.f_code.co_filename)
    for repo_path in self._all_repo_paths:
      if code_file_path.startswith(repo_path):
        return None
    return 'non recipe code'
