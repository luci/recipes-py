# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import absolute_import
import bisect
import collections
import contextlib
import copy
import hashlib
import json
import keyword
import os
import pprint
import re
import types

from functools import wraps

from .recipe_test_api import DisabledTestData, ModuleTestData
from .config import Single
from .types import StepData
from .util import ModuleInjectionSite, Placeholder

from . import env

from .source_manifest_pb2 import Manifest
from libs.logdog import streamname
from libs.logdog.bootstrap import ButlerBootstrap, NotBootstrappedError


# The source manifest ContentType.
#
# This must match the ContentType for the source manifest binary protobuf, which
# is specified in "<luci-go>/common/proto/milo/util.go".
SOURCE_MANIFEST_CONTENT_TYPE = 'text/x-chrome-infra-source-manifest; version=1'


class UnknownRequirementError(object):
  """Raised by a requirement function when the referenced requirement is
  unknown.
  """

  def __init__(self, req):
    super(UnknownRequirementError, self).__init__(
        'Unknown requirement [%s]' % (req,))
    self.typ = req._typ
    self.name = req._name


class _UnresolvedRequirement(object):
  """Internal placeholder type for an unresolved module/recipe requirement."""

  def __init__(self, typ, name):
    self._typ = typ
    self._name = name

  def __str__(self):
    return '%s:%s' % (self._typ, self._name)

  def __getattr__(self, key):
    raise AttributeError(
        'Cannot reference [%s] in unresolved requirement [%s]' % (
            key, str(self,)))

  def __call__(self, *args, **kwargs):
    raise AttributeError('Cannot call unresolved requirement [%s]' % (
        str(self,)))


def RequireClient(name):
  """Returns: A dependency injection placeholder for a recipe engine client.

  Recipes and Recipe APIs can call this function to install a placeholder for
  the dependency injection of a recipe engine client. This dependency will be
  noted by the recipe engine and resolved prior to recipe execution.

  Clients are intended to be used to interface between the recipe engine and
  low-level modules (e.g., "step"). As a general rule of thumb, higher-level
  modules should not use clients and interface with the low-level modules
  instead.

  Recipe engine clients are referenced by name and resolved directly by the
  recipe engine. Modules must require them as class member variables in their
  recipe API subclass, and recipes must require them as top-level variables.

  For example:

  class MyCollRecipeApi(recipe_api.RecipeApi):

    step_client = recipe_api.RequireClient('step')

    def do_something(self):
      self.step_client.whatever()

  Args:
    name (str): the name of the recipe engine client to install.
  """
  return _UnresolvedRequirement('client', name)


class PathsClient(object):
  """A recipe engine client which exposes all known base paths.

  In particular, you can use this client to discover all known:
    * recipe resource path
    * loaded module resource paths
    * loaded package repo paths
  """

  IDENT = 'paths'

  def __init__(self):
    self.paths = []
    self.path_strings = []

  def _initialize_with_recipe_api(self, root_api):
    """This method is called once before the start of every recipe.

    It is passed the recipe's `api` object. This method crawls the api object
    and extracts every resource base path it can find."""
    paths_found = {}
    def add_found(path):
      if path is not None:
        paths_found[str(path)] = path

    search_set = [root_api]
    found_api_id_set = {id(root_api)}
    while search_set:
      api = search_set.pop()

      add_found(api.resource())
      add_found(api.package_repo_resource())

      for name in dir(api.m):
        sub_api = getattr(api.m, name)
        if not isinstance(sub_api, RecipeApiPlain):
          continue
        if id(sub_api) not in found_api_id_set:
          found_api_id_set.add(id(api))
          search_set.append(sub_api)

    # transpose
    #   [(path_string, path), ...]
    #   into
    #   ([path_string, ...], [path, ...])
    self.path_strings, self.paths = zip(*sorted(paths_found.items()))

  def find_longest_prefix(self, target, sep):
    """Identifies a known resource path which would contain the `target` path.

    sep must be the current path separator (can vary from os.path.sep when
    running under simulation).

    Returns (str(Path), Path) if the prefix path is found, or (None, None) if no
    such prefix exists.
    """
    idx = bisect.bisect_left(self.path_strings, target)
    if idx == len(self.paths):
      return (None, None) # off the end

    sPath, path = self.path_strings[idx], self.paths[idx]
    if target == sPath :
      return sPath, path

    if idx > 0:
      sPath, path = self.path_strings[idx-1], self.paths[idx-1]
      if target.startswith(sPath+sep):
        return sPath, path

    return (None, None)


class PropertiesClient(object):
  """A recipe engine client representing the recipe engine properties."""

  IDENT = 'properties'

  def __init__(self, engine):
    self._engine = engine

  def get_properties(self):
    return copy.deepcopy(self._engine.properties)


class StepClient(object):
  """A recipe engine client representing step running and introspection."""

  IDENT = 'step'


  class StepConfig(collections.namedtuple('_StepConfig', (
      'name', 'base_name', 'cmd', 'cwd', 'env', 'env_prefixes', 'env_suffixes',
      'allow_subannotations', 'trigger_specs', 'timeout', 'infra_step',
      'stdout', 'stderr', 'stdin', 'ok_ret', 'step_test_data', 'nest_level'))):

    """
    StepConfig is the representation of a raw step as the recipe_engine sees it.
    You should use the standard 'step' recipe module, which will construct and
    pass this data to the engine for you, instead. The only reason why you would
    need to worry about this object is if you're modifying the step module
    itself.

    Fields:
      name (str): name of the step, will appear in buildbots waterfall
      base_name (str): the base name of the step. If the step has a derived
          name (e.g., nested may be concatenated with its parent), this is the
          name component of just this step. If None, this will be set to "name".
      cmd: command to run. Acceptable types: str, Path, Placeholder, or None.
      cwd (str or None): absolute path to working directory for the command
      env (dict): overrides for environment variables, described above.
      env_prefixes (dict): environment prefix variables, mapping environment
        variable names to EnvAffix values.
      env_suffixes (dict): environment suffix variables, mapping environment
        variable names to EnvAffix values.
      allow_subannotations (bool): if True, lets the step emit its own
          annotations. NOTE: Enabling this can cause some buggy behavior. Please
          strongly consider using step_result.presentation instead. If you have
          questions, please contact infra-dev@chromium.org.
      trigger_specs: a list of trigger specifications, see also _trigger_builds.
      timeout: if not None, a datetime.timedelta for the step timeout.
      infra_step: if True, this is an infrastructure step. Failures will raise
          InfraFailure instead of StepFailure.
      stdout: Placeholder to put step stdout into. If used, stdout won't appear
          in annotator's stdout (and |allow_subannotations| is ignored).
      stderr: Placeholder to put step stderr into. If used, stderr won't appear
          in annotator's stderr.
      stdin: Placeholder to read step stdin from.
      ok_ret (iter, ALL_OK): set of return codes allowed. If the step process
          returns something not on this list, it will raise a StepFailure (or
          InfraFailure if infra_step is True). If omitted, {0} will be used.
          Alternatively, the sentinel StepConfig.ALL_OK can be used to allow any
          return code.
      step_test_data (func -> recipe_test_api.StepTestData): A factory which
          returns a StepTestData object that will be used as the default test
          data for this step. The recipe author can override/augment this object
          in the GenTests function.
      nest_level (int): the step's nesting level.

    The optional "env" parameter provides optional overrides for environment
    variables. Each value is % formatted with the entire existing os.environ. A
    value of `None` will remove that envvar from the environ. e.g.

      {
          "envvar": "%(envvar)s;%(envvar2)s;extra",
          "delete_this": None,
          "static_value": "something",
      }

    The optional "env_prefixes" (and similarly "env_suffixes") parameters
    contains values that, if specified, will transform an environment variable
    into a "pathsep"-delimited sequence of items:
      - If an environment variable is also specified for this key, it will be
        appended as the last element: <prefix0>:...:<prefixN>:ENV
      - If no environment variable is specified, the current environment's value
        will be appended, unless it's empty: <prefix0>:...:<prefixN>[:ENV]?
      - If an environment variable with a value of None (delete) is specified,
        nothing will be appeneded: <prefix0>:...:<prefixN>

    There is currently no way to remove prefix paths; once they're there,
    they're there for good. If you think you need to remove paths from the
    prefix lists, please talk to infra-dev@chromium.org.
    """

    ALL_OK = StepData.ALL_OK

    class EnvAffix(collections.namedtuple('_EnvAffix', (
        'mapping', 'pathsep'))):
      """Expresses a mapping of environment keys to a list of paths.

      This is used as StepConfig's "env_prefixes" and "env_suffixes" value.
      """

      @classmethod
      def empty(cls):
        return cls(mapping={}, pathsep=None)

      def render_step_value(self):
        rendered = {k: (self.pathsep or ':').join(str(x) for x in v)
                    for k, v in self.mapping.iteritems()}
        return pprint.pformat(rendered, width=1024)


    _RENDER_WHITELIST=frozenset((
      'cmd',
    ))

    _RENDER_BLACKLIST=frozenset((
      'base_name',
      'nest_level',
      'ok_ret',
      'step_test_data',
    ))

    def __new__(cls, **kwargs):
      for field in cls._fields:
        kwargs.setdefault(field, None)
      sc = super(StepClient.StepConfig, cls).__new__(cls, **kwargs)

      return sc._replace(
          cmd=[(x if isinstance(x, Placeholder) else str(x))
               for x in (sc.cmd or ())],
          cwd=(str(sc.cwd) if sc.cwd else (None)),
          env=sc.env or {},
          env_prefixes=sc.env_prefixes or cls.EnvAffix.empty(),
          env_suffixes=sc.env_suffixes or cls.EnvAffix.empty(),
          base_name=sc.base_name or sc.name,
          allow_subannotations=bool(sc.allow_subannotations),
          trigger_specs=sc.trigger_specs or (),
          infra_step=bool(sc.infra_step),
          ok_ret=(sc.ok_ret if sc.ok_ret is StepClient.StepConfig.ALL_OK
                  else frozenset(sc.ok_ret or (0,))),
          nest_level=int(sc.nest_level or 0),
      )

    def render_to_dict(self):
      sc = self._replace(
          env_prefixes={k: list(str(e) for e in v)
                        for k, v in self.env_prefixes.mapping.iteritems()},
          env_suffixes={k: list(str(e) for e in v)
                        for k, v in self.env_suffixes.mapping.iteritems()},
          trigger_specs=[trig._render_to_dict()
                         for trig in (self.trigger_specs or ())],
      )
      return dict((k, v) for k, v in sc._asdict().iteritems()
                  if (v or k in sc._RENDER_WHITELIST)
                  and k not in sc._RENDER_BLACKLIST)


  class TriggerSpec(collections.namedtuple('_TriggerSpec', (
      'bucket', 'builder_name', 'properties', 'buildbot_changes', 'tags',
      'critical'))):

    """
    TriggerSpec is the internal representation of a raw trigger step. You should
    use the standard 'step' recipe module, which will construct trigger specs
    via API.

    Fields:
      builder_name (str): The name of the builder to trigger.
      bucket (str or None): The name of the trigger bucket.
      properties (dict or None): Key/value properties dictionary.
      buildbot_changes (list or None): Optional list of BuildBot change dicts.
      tags (list or None): Optional list of tag strings.
      critical (bool or None): If true and triggering fails asynchronously, fail
          the entire build. If None, the step defaults to being True.
    """

    def __new__(cls, **kwargs):
      for field in cls._fields:
        kwargs.setdefault(field, None)
      trig = super(StepClient.TriggerSpec, cls).__new__(cls, **kwargs)
      return trig._replace(
          critical=bool(trig.critical),
      )

    def _render_to_dict(self):
      d = dict((k, v) for k, v in self._asdict().iteritems() if v)
      if d['critical']:
        d.pop('critical')
      return d


  def __init__(self, engine):
    self._engine = engine

  def previous_step_result(self):
    """Allows api.step to get the active result from any context.

    This always returns the innermost nested step that is still open --
    presumably the one that just failed if we are in an exception handler."""
    step = self._engine.active_step
    if not step:
      raise ValueError(
          'No steps have been run yet, and you are asking for a previous step '
          'result.')
    return step.step_result

  def run_step(self, step_config):
    """
    Runs a step from a StepConfig.

    Args:
      step_config: Keyword arguments to use to instantiate a StepConfig.

    Returns:
      A StepData object containing the result of running the step.
    """
    assert isinstance(step_config, self.StepConfig)
    return self._engine.run_step(step_config)


class SourceManifestClient(object):
  """A recipe engine client allowing the upload of Source Manifests.

  The Source Manifest definition is in `recipe_engine/source_manifest.proto`.
  """

  class ManifestUploadException(Exception):
    pass

  class BadManifestName(Exception):
    pass

  class DuplicateManifestException(Exception):
    pass

  class NoActiveStep(Exception):
    pass

  IDENT = 'source_manifest'

  def __init__(self, engine, properties):
    self._engine = engine

    self._debug_dir = None
    self._logdog_client = None
    self._manifest_names = set()
    self._prod = True

    try:
      self._debug_dir = (
        properties['$recipe_engine/source_manifest']['debug_dir'])
      self._prod = False
    except (KeyError, TypeError):
      pass

    if not self._prod:
      if not isinstance(self._debug_dir, (type(None), str)):
        raise TypeError(
          '$recipe_engine/source_manifest["debug_dir"] must be null or str: %r'
          % self._debug_dir)
      if self._debug_dir and not os.path.isdir(self._debug_dir):
        # let it fail
        os.makedirs(self._debug_dir)
    else:
      try:
        self._logdog_client = ButlerBootstrap.probe().stream_client()
      except NotBootstrappedError:
        # This will become an exception in upload_manifest later.
        pass

  def upload_manifest(self, name, manifest_pb):
    if not isinstance(manifest_pb, Manifest):
      raise TypeError('expected source_manifest_pb2.Manifest, got %r'
                      % type(manifest_pb))

    if self._prod and not self._logdog_client:
      raise self.ManifestUploadException(
        'LogDog not configured; if debugging locally, set the '
        '"$recipe_engine/source_manifest"={"debug_dir": "some/local/directory"}'
        ' property. You may also set debug_dir to `null` to disable all source '
        ' manifest saving.')

    if name.startswith('luci/'):
      raise self.BadManifestName('Manifest names beginning with "luci/" are '
                                 'reserved: %r' % name)

    try:
      streamname.validate_stream_name(name)
    except ValueError:
      raise self.BadManifestName('Manifest name must be a valid LogDog name: '
                                 '%r' % name)

    if not self._engine.active_step:
      raise self.NoActiveStep('Uploading a manifest requires an active step.')

    if name in self._manifest_names:
      raise self.DuplicateManifestException(name)

    self._manifest_names.add(name)

    data = manifest_pb.SerializeToString()
    sha256 = hashlib.sha256(data).digest()

    if self._debug_dir:
      path = os.path.join(self._debug_dir, name)
      with open(path, 'wb') as f:
        f.write(data)
      with open(path+'.sha256', 'wb') as f:
        f.write(sha256)
    elif self._prod:
      logdog_name = '/'.join(['source_manifest', name])
      with self._logdog_client.binary(
          name=logdog_name,
          content_type=SOURCE_MANIFEST_CONTENT_TYPE) as bs:
        bs.write(data)
      host = self._logdog_client.coordinator_host
      project = self._logdog_client.project
      path = self._logdog_client.get_stream_path(logdog_name)
      self._engine.active_step.open_step.stream.set_manifest_link(
        name, sha256, 'logdog://%s/%s/%s' % (host, project, path))


class StepFailure(Exception):
  """
  This is the base class for all step failures.

  Raising a StepFailure counts as 'running a step' for the purpose of
  infer_composite_step's logic.

  FIXME: This class is as a general way to fail, but it should be split up.
  See crbug.com/892792 for more information.
  """
  def __init__(self, name_or_reason, result=None):
    # Raising a StepFailure counts as running a step.
    _DEFER_CONTEXT.mark_ran_step()
    if result:
      self.name = name_or_reason
      self.result = result
      self.reason = self.reason_message()
    else:
      self.name = None
      self.result = None
      self.reason = name_or_reason

    super(StepFailure, self).__init__(self.reason)

  def reason_message(self):
    return "Step({!r}) failed with return_code {}".format(
        self.name, self.result.retcode)

  def __str__(self):  # pragma: no cover
    return "Step Failure in %s" % self.name

  @property
  def retcode(self):
    """
    Returns the retcode of the step which failed. If this was a manual
    failure, returns None
    """
    if not self.result:
      return None
    return self.result.retcode


class StepWarning(StepFailure):
  """
  A subclass of StepFailure, which still fails the build, but which is
  a warning. Need to figure out how exactly this will be useful.
  """
  def reason_message(self):  # pragma: no cover
    return "Warning: Step({!r}) returned {}".format(
          self.name, self.result.retcode)

  def __str__(self):  # pragma: no cover
    return "Step Warning in %s" % self.name


class InfraFailure(StepFailure):
  """
  A subclass of StepFailure, which fails the build due to problems with the
  infrastructure.
  """
  def reason_message(self):
    return "Infra Failure: Step({!r}) returned {}".format(
          self.name, self.retcode)

  def __str__(self):
    return "Infra Failure in %s" % self.name


class StepTimeout(StepFailure):
  """
  A subclass of StepFailure, where a step times out and is killed.
  """
  def __init__(self, name, timeout):
    self.timeout = timeout
    self.name = name
    super(StepTimeout, self).__init__(self.reason_message())

  def reason_message(self):
    return "Step Timeout: Step({!r}) timed out after {}".format(
        self.name, self.timeout)

  def __str__(self):
    return "Step Timeout in %s" % self.name


class AggregatedStepFailure(StepFailure):
  def __init__(self, result):
    super(AggregatedStepFailure, self).__init__(
            "Aggregate step failure.", result=result)

  def reason_message(self):
    msg = "{!r} out of {!r} aggregated steps failed: ".format(
        len(self.result.failures), len(self.result.all_results))
    msg += ', '.join((f.reason or f.name) for f in self.result.failures)
    return msg

  def __str__(self):  # pragma: no cover
    return "Aggregate Step Failure"


class AggregatedResult(object):
  """Holds the result of an aggregated run of steps.

  Currently this is only used internally by defer_results, but it may be exposed
  to the consumer of defer_results at some point in the future. For now it's
  expected to be easier for defer_results consumers to do their own result
  aggregation, as they may need to pick and chose (or label) which results they
  really care about.
  """
  def __init__(self):
    self.successes = []
    self.failures = []
    self.contains_infra_failure = False

    # Needs to be here to be able to treat this as a step result
    self.retcode = None

  @property
  def all_results(self):
    """
    Return a list of two item tuples (x, y), where
      x is whether or not the step succeeded, and
      y is the result of the run
    """
    res = [(True, result) for result in self.successes]
    res.extend([(False, result) for result in self.failures])
    return res

  def add_success(self, result):
    self.successes.append(result)

  def add_failure(self, exception):
    self.failures.append(exception)


class DeferredResult(object):
  def __init__(self, result, failure):
    self._result = result
    self._failure = failure

  @property
  def is_ok(self):
    return self._failure is None

  def get_result(self):
    if not self.is_ok:
      raise self.get_error()
    return self._result

  def get_error(self):
    assert self._failure, "WHAT IS IT ARE YOU DOING???!?!?!? SHTAP NAO"
    return self._failure


class _DEFER_CONTEXT_OBJ(object):
  """This object keeps track of state pertaining to the behavior of
  defer_results and composite_step.
  """

  def __init__(self):
    """The object starts in a state where no steps have been run, and there's no
    current aggregated_result."""
    self._ran_step = [False]
    self._aggregated_result = [None]

  @property
  def ran_step(self):
    """Returns True if a step has run within this defer_results context."""
    return self._ran_step[-1]

  def mark_ran_step(self):
    """Marks that a step has run within this defer_results context."""
    self._ran_step[-1] = True

  @property
  def aggregated_result(self):
    """Returns the current AggregatedResult() or None, if we're not currently
    deferring results."""
    return self._aggregated_result[-1]

  @contextlib.contextmanager
  def begin_aggregate(self):
    """Begins aggregating new results. Use with a with statement:

      with _DEFER_CONTEXT.begin_aggregate() as agg:
        ...

    Where `agg` is the AggregatedResult() for that with section.
    """
    try:
      yield self._enter(AggregatedResult())
    finally:
      self._exit()

  @contextlib.contextmanager
  def begin_normal(self):
    """Returns the context to normal (stop aggregating results).

      with _DEFER_CONTEXT.begin_normal():
        ...
    """
    try:
      yield self._enter(None)
    finally:
      self._exit()

  def _enter(self, agg):
    self._ran_step.append(False)
    self._aggregated_result.append(agg)
    return agg

  def _exit(self):
    self._ran_step.pop()
    self._aggregated_result.pop()


_DEFER_CONTEXT = _DEFER_CONTEXT_OBJ()


def non_step(func):
  """A decorator which prevents a method from automatically being wrapped as
  a infer_composite_step by RecipeApiMeta.

  This is needed for utility methods which don't run any steps, but which are
  invoked within the context of a defer_results().

  @see infer_composite_step, defer_results, RecipeApiMeta
  """
  assert not hasattr(func, "_skip_inference"), \
         "Double-wrapped method %r?" % func
  func._skip_inference = True # pylint: disable=protected-access
  return func

_skip_inference = non_step


def infer_composite_step(func):
  """A decorator which possibly makes this step act as a single step, for the
  purposes of the defer_results function.

  Behaves as if this function were wrapped by composite_step, unless this
  function:
    * is already wrapped by non_step
    * returns a result without calling api.step
    * raises an exception which is not derived from StepFailure

  In any of these cases, this function will behave like a normal function.

  This decorator is automatically applied by RecipeApiMeta (or by inheriting
  from RecipeApi). If you want to decalare a method's behavior explicitly, you
  may decorate it with either composite_step or with non_step.
  """
  if getattr(func, "_skip_inference", False):
    return func

  @_skip_inference # to prevent double-wraps
  @wraps(func)
  def _inner(*a, **kw):
    agg = _DEFER_CONTEXT.aggregated_result

    # We're not deferring results, so run the function normally.
    if agg is None:
      return func(*a, **kw)

    # Stop deferring results within this function; the ultimate result of the
    # function will be added to our parent context's aggregated results and
    # we'll return a DeferredResult.
    with _DEFER_CONTEXT.begin_normal():
      try:
        ret = func(*a, **kw)
        # This is how we differ from composite_step; if we didn't actually run
        # a step or throw a StepFailure, return normally.
        if not _DEFER_CONTEXT.ran_step:
          return ret
        agg.add_success(ret)
        return DeferredResult(ret, None)
      except StepFailure as ex:
        if isinstance(ex, InfraFailure):
          agg.contains_infra_failure = True
        agg.add_failure(ex)
        return DeferredResult(None, ex)
  _inner.__original = func
  return _inner


def composite_step(func):
  """A decorator which makes this step act as a single step, for the purposes of
  the defer_results function.

  This means that this function will not quit during the middle of its execution
  because of a StepFailure, if there is an aggregator active.

  You may use this decorator explicitly if infer_composite_step is detecting
  the behavior of your method incorrectly to force it to behave as a step. You
  may also need to use this if your Api class inherits from RecipeApiPlain and
  so doesn't have its methods automatically wrapped by infer_composite_step.
  """
  @_skip_inference  # to avoid double-wraps
  @wraps(func)
  def _inner(*a, **kw):
    # composite_steps always count as running a step.
    _DEFER_CONTEXT.mark_ran_step()

    agg = _DEFER_CONTEXT.aggregated_result

    # If we're not aggregating
    if agg is None:
      return func(*a, **kw)

    # Stop deferring results within this function; the ultimate result of the
    # function will be added to our parent context's aggregated results and
    # we'll return a DeferredResult.
    with _DEFER_CONTEXT.begin_normal():
      try:
        ret = func(*a, **kw)
        agg.add_success(ret)
        return DeferredResult(ret, None)
      except StepFailure as ex:
        if isinstance(ex, InfraFailure):
          agg.contains_infra_failure = True
        agg.add_failure(ex)
        return DeferredResult(None, ex)
  _inner.__original = func
  return _inner


@contextlib.contextmanager
def defer_results():
  """
  Use this to defer step results in your code. All steps which would previously
    return a result or throw an exception will instead return a DeferredResult.

  Any exceptions which were thrown during execution will be thrown when either:
    a. You call get_result() on the step's result.
    b. You exit the lexical scope inside of the with statement

  Example:
    with defer_results():
      api.step('a', ..)
      api.step('b', ..)
      result = api.m.module.im_a_composite_step(...)
      api.m.echo('the data is', result.get_result())

  If 'a' fails, 'b' and 'im a composite step'  will still run.
  If 'im a composite step' fails, then the get_result() call will raise
    an exception.
  If you don't try to use the result (don't call get_result()), an aggregate
    failure will still be raised once you exit the lexical scope inside
    the with statement.
  """
  assert _DEFER_CONTEXT.aggregated_result is None, (
      "may not call defer_results in an active defer_results context")
  with _DEFER_CONTEXT.begin_aggregate() as agg:
    yield
  if agg.failures:
    raise AggregatedStepFailure(agg)


class RecipeApiMeta(type):
  WHITELIST = ('__init__',)
  def __new__(mcs, name, bases, attrs):
    """Automatically wraps all methods of subclasses of RecipeApi with
    @infer_composite_step. This allows defer_results to work as intended without
    manually decorating every method.
    """
    wrap = lambda f: infer_composite_step(f) if f else f
    for attr in attrs:
      if attr in RecipeApiMeta.WHITELIST:
        continue
      val = attrs[attr]
      if isinstance(val, types.FunctionType):
        attrs[attr] = wrap(val)
      elif isinstance(val, property):
        attrs[attr] = property(
          wrap(val.fget),
          wrap(val.fset),
          wrap(val.fdel),
          val.__doc__)
    return super(RecipeApiMeta, mcs).__new__(mcs, name, bases, attrs)


class RecipeApiPlain(object):
  """
  Framework class for handling recipe_modules.

  Inherit from this in your recipe_modules/<name>/api.py . This class provides
  wiring for your config context (in self.c and methods, and for dependency
  injection (in self.m).

  Dependency injection takes place in load_recipe_modules() in loader.py.

  USE RecipeApi INSTEAD, UNLESS your RecipeApi subclass derives from something
  which defines its own __metaclass__. Deriving from RecipeApi instead of
  RecipeApiPlain allows your RecipeApi subclass to automatically work with
  defer_results without needing to decorate every methods with
  @infer_composite_step.
  """

  def __init__(self, module=None, test_data=DisabledTestData(), **_kwargs):
    """Note: Injected dependencies are NOT available in __init__()."""
    super(RecipeApiPlain, self).__init__()

    self._module = module

    assert isinstance(test_data, (ModuleTestData, DisabledTestData))
    self._test_data = test_data

    # If we're the 'root' api, inject directly into 'self'.
    # Otherwise inject into 'self.m'
    if not isinstance(module, types.ModuleType):
      self.m = self
    else:
      self.m = ModuleInjectionSite(self)

    # If our module has a test api, it gets injected here.
    self.test_api = None

    # Config goes here.
    self.c = None

  def initialize(self):
    """
    Initializes the recipe module after it has been instantiated with all
    dependencies injected and available.
    """
    pass

  def get_config_defaults(self):  # pylint: disable=R0201
    """
    Allows your api to dynamically determine static default values for configs.
    """
    return {}

  def make_config(self, config_name=None, optional=False, **CONFIG_VARS):
    """Returns a 'config blob' for the current API."""
    return self.make_config_params(config_name, optional, **CONFIG_VARS)[0]

  def make_config_params(self, config_name, optional=False, **CONFIG_VARS):
    """Returns a 'config blob' for the current API, and the computed params
    for all dependent configurations.

    The params have the following order of precendence. Each subsequent param
    is dict.update'd into the final parameters, so the order is from lowest to
    higest precedence on a per-key basis:
      * if config_name in CONFIG_CTX
        * get_config_defaults()
        * CONFIG_CTX[config_name].DEFAULT_CONFIG_VARS()
        * CONFIG_VARS
      * else
        * get_config_defaults()
        * CONFIG_VARS
    """
    generic_params = self.get_config_defaults()  # generic defaults
    generic_params.update(CONFIG_VARS)           # per-invocation values

    ctx = self._module.CONFIG_CTX
    if optional and not ctx:
      return None, generic_params

    assert ctx, '%s has no config context' % self
    try:
      params = self.get_config_defaults()         # generic defaults
      itm = ctx.CONFIG_ITEMS[config_name] if config_name else None
      if itm:
        params.update(itm.DEFAULT_CONFIG_VARS())  # per-item defaults
      params.update(CONFIG_VARS)                  # per-invocation values

      base = ctx.CONFIG_SCHEMA(**params)
      if config_name is None:
        return base, params
      else:
        return itm(base), params
    except KeyError:
      if optional:
        return None, generic_params
      else:  # pragma: no cover
        raise  # TODO(iannucci): raise a better exception.

  def set_config(self, config_name=None, optional=False, **CONFIG_VARS):
    """Sets the modules and its dependencies to the named configuration."""
    assert self._module
    config, _ = self.make_config_params(config_name, optional, **CONFIG_VARS)
    if config:
      self.c = config

  def apply_config(self, config_name, config_object=None, optional=False):
    """Apply a named configuration to the provided config object or self."""
    assert config_name in self._module.CONFIG_CTX.CONFIG_ITEMS, (
        config_name, self._module.CONFIG_CTX.CONFIG_ITEMS)
    self._module.CONFIG_CTX.CONFIG_ITEMS[config_name](
        config_object or self.c, optional=optional)

  def resource(self, *path):
    """Returns path to a file under <recipe module>/resources/ directory.

    Args:
      path: path relative to module's resources/ directory.
    """
    # TODO(vadimsh): Verify that file exists. Including a case like:
    #  module.resource('dir').join('subdir', 'file.py')
    return self._module.RESOURCE_DIRECTORY.join(*path)

  def package_repo_resource(self, *path):
    """Returns a resource path, where path is relative to the root of
    the package repo where this module is defined.
    """
    return self._module.PACKAGE_REPO_ROOT.join(*path)

  @property
  def name(self):
    return self._module.NAME


class RecipeApi(RecipeApiPlain):
  __metaclass__ = RecipeApiMeta


class RecipeScriptApi(RecipeApiPlain, ModuleInjectionSite):
  # TODO(dnj): Delete this and make recipe scripts use standard recipe APIs.
  pass


# This is a sentinel object for the Property system. This allows users to
# specify a default of None that will actually be respected.
PROPERTY_SENTINEL = object()

class BoundProperty(object):
  """
  A bound, named version of a Property.

  A BoundProperty is different than a Property, in that it requires a name,
  as well as all of the arguments to be provided. It's intended to be
  the declaration of the Property, with no mutation, so the logic about
  what a property does is very clear.

  The reason there is a distinction between this and a Property is because
  we want the user interface for defining properties to be
    PROPERTIES = {
      'prop_name': Property(),
    }

  We don't want to have to duplicate the name in both the key of the dictionary
  and then Property constructor call, so we need to modify this dictionary
  before we actually use it, and inject knowledge into it about its name. We
  don't want to actually mutate this though, since we're striving for immutable,
  declarative code, so instead we generate a new BoundProperty object from the
  defined Property object.
  """

  MODULE_PROPERTY = 'module'
  RECIPE_PROPERTY = 'recipe'

  @staticmethod
  def legal_module_property_name(name, full_decl_name):
    """
    If this is a special $package/module name.
    """
    package, module = full_decl_name.split('::', 1)
    return name == '$%s/%s' % (package, module)

  @staticmethod
  def legal_name(name, is_param_name=False):
    """
    If this name is a legal property name.

    is_param_name determines if this name in the name of a property, or a
      param_name. See the constructor documentation for more information.

    The rules are as follows:
      * Cannot start with an underscore.
        This is for internal arguments, namely _engine (for the step module).
      * Cannot be 'self'
        This is to avoid conflict with recipe modules, which use the name self.
      * Cannot be a python keyword
    """
    if name.startswith('_'):
      return False

    if name in ('self',):
      return False

    if keyword.iskeyword(name):
      return False

    regex = r'^[a-zA-Z][a-zA-Z0-9_]*$' if is_param_name else (
        r'^[a-zA-Z][.\w-]*$')
    return bool(re.match(regex, name))

  def __init__(self, default, from_environ, help, kind, name, property_type,
               full_decl_name, param_name=None):
    """
    Constructor for BoundProperty.

    Args:
      default (jsonish): The default value for this Property. Must be
        JSON-encodable or PROPERTY_SENTINEL.
      from_environ (str|None): If given, specifies an environment variable to
        grab the default property value from before falling back to the
        hardcoded default. If the property value is explicitly passed to the
        recipe, it still takes precedence over the environment. If you rely on
        this, 'kind' must be string-compatible (since environ contains strings).
      help (str): The help text for this Property.
      kind (type|ConfigBase): The type of this Property. You can either pass in
        a raw python type, or a Config Type, using the recipe engine config
        system.
      name (str): The name of this Property.
      property_type (str): One of RECIPE_PROPERTY or MODULE_PROPERTY.
      full_decl_name (str): The fully qualified name of the recipe or module
        where this property is defined. This has the form of:
          package_name::module_name
          package_name::path/to/recipe
      param_name (str|None): The name of the python function parameter this
        property should be stored in. Can be used to allow for dotted property
        names, e.g.
          PROPERTIES = {
            'foo.bar.bam': Property(param_name="bizbaz")
          }
    """
    assert property_type in (self.RECIPE_PROPERTY, self.MODULE_PROPERTY), \
      property_type

    # first, check if this is a special '$package/module' property type
    # declaration.
    is_module_property = (
      property_type is self.MODULE_PROPERTY and
      self.legal_module_property_name(name, full_decl_name))
    if not (is_module_property or BoundProperty.legal_name(name)):
      raise ValueError("Illegal name '{}'.".format(name))

    param_name = param_name or name
    if not BoundProperty.legal_name(param_name, is_param_name=True):
      raise ValueError("Illegal param_name '{}'.".format(param_name))

    if default is not PROPERTY_SENTINEL:
      try:
        json.dumps(default)
      except:
        raise TypeError('default=%r is not json-encodable' % (default,))

    self.__default = default
    self.__from_environ = from_environ
    self.__help = help
    self.__kind = kind
    self.__name = name
    self.__property_type = property_type
    self.__param_name = param_name
    self.__full_decl_name = full_decl_name

  @property
  def name(self):
    return self.__name

  @property
  def param_name(self):
    return self.__param_name

  @property
  def default(self):
    if self.__default is PROPERTY_SENTINEL:
      return self.__default
    return copy.deepcopy(self.__default)

  @property
  def from_environ(self):
    return self.__from_environ

  @property
  def kind(self):
    return self.__kind

  @property
  def help(self):
    return self.__help

  @property
  def full_decl_name(self):
    return self.__full_decl_name

  def interpret(self, value, environ):
    """
    Interprets the value for this Property.

    Args:
      value: The value to interpret. May be None, which means no explicit value
             is provided and we should grab a default.
      environ: An environment dict to use for grabbing values for properties
               that use 'from_environ'.

    Returns:
      The value to use for this property. Raises an error if
      this property has no valid interpretation.
    """
    # Pick from environment if not given explicitly.
    if value is PROPERTY_SENTINEL and self.__from_environ:
      value = environ.get(self.__from_environ, PROPERTY_SENTINEL)

    # If have a value (passed explicitly or through environ), check its type.
    if value is not PROPERTY_SENTINEL:
      if self.kind is not None:
        # The config system handles type checking for us here.
        self.kind.set_val(value)
      return value

    if self.__default is not PROPERTY_SENTINEL:
      return self.default

    raise ValueError(
      "No default specified and no value provided for '{}' from {} '{}'".format(
        self.name, self.__property_type, self.full_decl_name))

class Property(object):
  def __init__(self, default=PROPERTY_SENTINEL, from_environ=None, help="",
               kind=None, param_name=None):
    """
    Constructor for Property.

    Args:
      default: The default value for this Property. Note: A default
               value of None is allowed. To have no default value, omit
               this argument. This must be a valid JSON-encodable object.
      from_environ: If given, specifies an environment variable to grab the
                    default property value from before falling back to the
                    hardcoded default. If the property value is explicitly
                    passed to the recipe, it still takes precedence over the
                    environment. If you rely on this, 'kind' must be
                    string-compatible (since environ contains strings).
      help: The help text for this Property.
      kind: The type of this Property. You can either pass in a raw python
            type, or a Config Type, using the recipe engine config system.
    """
    if default is not PROPERTY_SENTINEL:
      try:
        json.dumps(default)
      except:
        raise TypeError('default=%r is not json-encodable' % (default,))

    if from_environ is not None:
      if not isinstance(from_environ, basestring):
        raise TypeError('from_environ=%r must be a string' % (from_environ,))

    self._default = default
    self._from_environ = from_environ
    self.help = help
    self.param_name = param_name

    if isinstance(kind, type):
      if kind in (str, unicode):
        kind = basestring
      kind = Single(kind)
    self.kind = kind

  def bind(self, name, property_type, full_decl_name):
    """
    Gets the BoundProperty version of this Property. Requires a name.
    """
    return BoundProperty(
      self._default, self._from_environ, self.help, self.kind, name,
      property_type, full_decl_name, self.param_name)

class UndefinedPropertyException(TypeError):
  pass
