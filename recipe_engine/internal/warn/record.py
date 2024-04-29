# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""record warnings during recipe executions."""

import inspect
import os
import re
import types

from collections import defaultdict
from functools import cached_property

import attr
import gevent


from .cause import CallSite, Frame, ImportSite
from . import escape

from ..attr_util import attr_type
from ..recipe_deps import Recipe, RecipeDeps, RecipeModule

from ...engine_types import FrozenDict
from ...util import sentinel


# The sentinel that instructs recipe engine not to record warnings.
class NULL_WARNING_RECORDER:
  @property
  def recorded_warnings(self):
    return FrozenDict()

  def record_execution_warning(self, name, skip=0):
    pass

  def record_import_warning(self, name, importer):
    pass

  def reset_recorded_warning_names(self):
    pass

  @property
  def recorded_warning_names(self):
    return frozenset()


@attr.s(frozen=True, slots=True)
class _AnnotatedFrame:
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
class WarningRecorder:
  """A WarningRecorder records and analyzes warnings, preserves all unique
  causes for a given warning.

  There're two types of warnings; Execution warnings and Import warnings:
    * Execution Warning: issued within the execution of recipe code.
    * Import Warning: issued during dependency resolution (DEPS), when a recipe
      or recipe module depends on a module with warning declared.
  """
  # The RecipeDeps object for current recipe execution.
  recipe_deps: RecipeDeps = attr.ib(validator=attr_type(RecipeDeps))

  # Filter function that all execution warnings will be filtered through
  # before storing. If the function returns False, the warning will be
  # discarded. The function takes following two arguments and returns a bool.
  #   * name (str) - Fully qualified warning name e.g. 'repo/WARNING_NAME'
  #   * cause (warning_pb.Cause) - Cause of the warning
  call_site_filter = attr.ib(default=lambda name, cause: True)

  # Same functionality and function signature as call_site_filter but applies
  # to import warnings.
  import_site_filter = attr.ib(default=lambda name, cause: True)

  # Internal holder for recorded warnings.
  # key: fully qualified warning name (str)
  # value: Set[CallSite|ImportSite] (defined in cause.py, not the proto message)
  _recorded_warnings: dict[str, set] = attr.ib(init=False, factory=lambda: defaultdict(set))

  # Internal, resettable, set of warning names encountered.
  #
  # This is used by the test runner to populate Outcome.Results.warnings.
  _recorded_warning_names: set[str] = attr.ib(init=False, factory=set)

  @property
  def recorded_warnings(self):
    """Returns all recorded warnings in the form of

    {
      "repo_name_1/WARNING_NAME_1": tuple[warning_pb.Cause]
      "repo_name_2/WARNING_NAME_2": tuple[warning_pb.Cause]
    }

    cause inside the tuple is guaranteed to be unique for each warning.
    """
    return {
      name: tuple(site.cause_pb for site in sites)
      for (name, sites) in self._recorded_warnings.items()
    }

  def reset_recorded_warning_names(self):
    """Called from the test runner immediately prior to executing a test case."""
    self._recorded_warning_names = set()

  @property
  def recorded_warning_names(self) -> frozenset[str]:
    """Used by the test runner to see if any deadline warnings were caught
    during the execution of a test case."""
    return frozenset(self._recorded_warning_names)

  def record_execution_warning(self, name: str, skip: int = 0):
    """Record the warning issued during recipe execution and its cause (
    warning_pb.CallSite). A frame will be attributed as call site frame if it
    is the first frame in the supplied frames matching the following
    conditions:
      * The source code of the frame is 'recipe code' (i.e. in the current
        recipe repo or one of its dependencies).
      * The function that the frame executes is not escaped from the issued
        warning.

    Args:
      * name: Warning name (e.g. repo_name/WARNING_NAME or WARNING_NAME). If the
        name is not fully qualified, this will resolve the warning name based on
        the location of the caller of record_execution_warning(). So if the
        caller is in a file in some recipe repo X, WARNING_NAME will resolve to
        X/WARNING_NAME.
      * skip (int): Count of how many stack frames to skip to start
        attributing the warning to user code. The default of 1 skips the
        immediate caller.
    """
    stack = inspect.stack()[skip+1:]
    # [1] is the frame filename, but unfortunately python2 uses a bare tuple.
    name = self._resolve_name(name, stack[0][1])

    # grab all the frames and then ensure the stack is freed.
    frames = [frame_tup[0] for frame_tup in stack]
    del stack

    # Now make sure the caller of record_execution_warning is immune to
    # attribution for this warning. This is able to see through multiple
    # levels of decorators.
    self._ensure_caller_escaped(name, frames[0])

    frames.extend(getattr(gevent.getcurrent(), 'spawning_frames', ()))

    # TODO(yiwzhang): update proto to include skip reason and populate
    call_site_frame, _ = self._attribute_call_site(name, frames)
    if call_site_frame is escape.IGNORE:
      return
    call_site = CallSite(
      site=Frame.from_built_in_frame(call_site_frame) if (
        call_site_frame) else Frame(),
    )

    # return if call_site_frame isn't in the main repo; We don't want to report
    # warnings from other repos. It's possible to have a warning where ALL
    # frames are skipped, so only do this check if we actually had an attributed
    # call_site.
    if call_site.site.file:
      if not call_site.site.file.startswith(self._main_repo_paths):
        return

    if not call_site_frame:
      # Capture call stack if attributing call site fails
      call_site = attr.evolve(
        call_site,
        call_stack=[Frame.from_built_in_frame(f) for f in frames]
      )
    if (call_site not in self._recorded_warnings[name]) and (
      self.call_site_filter(name, call_site.cause_pb)):
      self._recorded_warnings[name].add(call_site)
      self._recorded_warning_names.add(name)

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

    # return if the import isn't from the main repo; We don't want to report
    # warnings from other repos.
    if importer.repo.name != self.recipe_deps.main_repo.name:
      return

    import_site = ImportSite(
      repo=importer.repo.name,
      module=importer.name if isinstance(importer, RecipeModule) else None,
      recipe=importer.name if isinstance(importer, Recipe) else None,
    )
    if (import_site not in self._recorded_warnings[name]) and (
        self.import_site_filter(name, import_site.cause_pb)):
      self._recorded_warnings[name].add(import_site)
      self._recorded_warning_names.add(name)

  def _resolve_name(self, name, issuer_file):
    """Returns the fully-qualified, validated warning name for the given
    warning.

    The repo that contains the issuer_file is considered as where the
    warning is defined.

    Args:
      * name (str): the warning name to be resolved. If fully-qualified name
        is provided, returns as it is.
      * issuer_file (str): The file path where warning is issued.

    Raise ValueError if none of the repo contains the issuer_file.
    """
    if '/' in name:
      self._validate_warning_name(name)
      return name

    abs_issuer_path = os.path.abspath(issuer_file)
    for _, (repo_name, repo_path) in enumerate(self._repo_paths):
      if abs_issuer_path.startswith(repo_path):
        name = '/'.join((repo_name, name))
        self._validate_warning_name(name)
        return name
    raise ValueError('Failed to resolve warning: %r issued in %s. To '
        'disambiguate, please provide fully-qualified warning name '
        '(i.e. $repo_name/WARNING_NAME)' % (name, abs_issuer_path))

  @staticmethod
  def _ensure_caller_escaped(name, frame):
    """Ensures that the function associated with `frame` is immune to
    attribution from the `name` warning.

    Args:
      * name - fully-qualified, validated warning name.
      * frame - the inspect stack frame of the function to immunize.
    """
    loc = escape.FuncLoc.from_code_obj(frame.f_code)
    pattern = re.compile('^%s$' % name)

    escaped_warnings = escape.WARNING_ESCAPE_REGISTRY.get(loc, ())
    if pattern not in escaped_warnings:
      escaped_warnings = (pattern,) + escaped_warnings
    escape.WARNING_ESCAPE_REGISTRY[loc] = escaped_warnings

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
  def _repo_paths(self):
    """A list of (repo name, repo path) inverse sorted by length of repo path.

    A repo may locate inside another repo (e.g. generally, deps repos are
    inside main repo). So we should start with the repo with the longest
    path to decide which repo contains the issuer file.
    """
    return sorted(
        ((repo_name, repo.path)
        for repo_name, repo in self.recipe_deps.repos.items()),
        key=lambda r: r[1],
        reverse=True,
    )

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
    Returns escape.IGNORE if the warning should be ignored.
    """
    return (
      self._non_recipe_code_predicate,
      escape.escape_warning_predicate
    )

  def _attribute_call_site(self, name, frames):
    """Walk up the given stack frames and attribute the first non-skipped frame
    as call site. self._skip_frame_predicates is used to decide whether to skip
    a frame or not.

    Returns a tuple of (frame, List[AnnotatedFrames]) where frame is the
    attributed call site and the annotated frames in the list are all skipped
    frames with their skipped reasons. Call site frame will be returned as None
    if all of the frames are skipped.

    Returns (escape.IGNORE, escape.IGNORE) if the warning should be ignored.
    """
    skipped_frames = []
    for frame in frames:
      lazy_skip_reasons = (p(name, frame) for p in self._skip_frame_predicates)
      reason = next((r for r in lazy_skip_reasons if r is not None), None)
      if reason is escape.IGNORE:
        return escape.IGNORE, escape.IGNORE
      if reason is None:
        return frame, skipped_frames # culprit found
      skipped_frames.append(_AnnotatedFrame(frame=frame, skip_reason=reason))
    return None, skipped_frames

  @cached_property
  def _main_repo_paths(self):
    """A tuple of root paths of all recipe code in the current recipe repo.
    """
    return (
      self.recipe_deps.main_repo.recipes_dir,
      self.recipe_deps.main_repo.modules_dir,
    )

  @cached_property
  def _all_repo_paths(self):
    """A tuple of root paths of all recipe code in the current executing
    recipe deps.
    """
    ret = []
    for repo in self.recipe_deps.repos.values():
      ret.append(repo.recipes_dir)
      ret.append(repo.modules_dir)
    return tuple(ret)

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


# The global warning recorder. This is set by each test runner to an instance of
# WarningRecorder.
GLOBAL: NULL_WARNING_RECORDER|WarningRecorder = NULL_WARNING_RECORDER()
