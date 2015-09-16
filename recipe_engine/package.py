import ast
import collections
import contextlib
import copy
import functools
import itertools
import logging
import os
import subprocess
import sys
import tempfile

from .third_party.google.protobuf import text_format
from . import package_pb2


class UncleanFilesystemError(Exception):
  pass


class InconsistentDependencyGraphError(Exception):
  pass


class CyclicDependencyError(Exception):
  pass


class InfraRepoConfig(object):
  def to_recipes_cfg(self, repo_root):
    # TODO(luqui): This is not always correct.  It can be configured in
    # infra/config:refs.cfg.
    return os.path.join(repo_root, 'infra', 'config', 'recipes.cfg')

  def from_recipes_cfg(self, recipes_cfg):
    return os.path.dirname( # <repo root>
            os.path.dirname( # infra
              os.path.dirname( # config
                os.path.abspath(recipes_cfg)))) # recipes.cfg


class ProtoFile(object):
  """A collection of functions operating on a proto path.

  This is an object so that it can be mocked in the tests.
  """
  def __init__(self, path):
    self._path = path

  @property
  def path(self):
    return os.path.realpath(self._path)

  def read_text(self):
    with open(self._path, 'r') as fh:
      return fh.read()

  def read(self):
    text = self.read_text()
    buf = package_pb2.Package()
    text_format.Merge(text, buf)
    return buf

  def to_text(self, buf):
    return text_format.MessageToString(buf)

  def write(self, buf):
    with open(self._path, 'w') as fh:
      fh.write(self.to_text(buf))


class PackageContext(object):
  """Contains information about where the root package and its dependency
  checkouts live.

  - recipes_dir is the location of recipes/ and recipe_modules/ which contain
    the actual recipes of the root package.
  - package_dir is where dependency checkouts live, e.g.
    package_dir/recipe_engine/recipes/...
  - repo_root is the root of the repository containing the root package.
  """

  def __init__(self, recipes_dir, package_dir, repo_root):
    self.recipes_dir = recipes_dir
    self.package_dir = package_dir
    self.repo_root = repo_root

  @classmethod
  def from_proto_file(cls, repo_root, proto_file):
    proto_path = proto_file.path
    buf = proto_file.read()

    recipes_path = buf.recipes_path.replace('/', os.sep)

    return cls(os.path.join(repo_root, recipes_path),
               os.path.join(repo_root, recipes_path, '.recipe_deps'),
               repo_root)


@functools.total_ordering
class RepoUpdate(object):
  """Wrapper class that specifies the sort order of roll updates when merging.
  """

  def __init__(self, spec):
    self.spec = spec

  @property
  def id(self):
    return self.spec.id

  def __eq__(self, other):
    return (self.id, self.spec.revision) == (other.id, other.spec.revision)

  def __le__(self, other):
    return (self.id, self.spec.revision) <= (other.id, other.spec.revision)


class RepoSpec(object):
  """RepoSpec is the specification of a repository to check out.

  The prototypical example is GitRepoSpec, which includes a url, revision,
  and branch.
  """

  def checkout(self, context):
    """Fetches the specified package and returns the path of the package root
    (the directory that contains recipes and recipe_modules).
    """
    raise NotImplementedError()

  def check_checkout(self, context):
    """Checks that the package is already fetched and in a good state, without
    actually changing anything.

    Returns None in normal conditions, otherwise raises some sort of exception.
    """
    raise NotImplementedError()

  def repo_root(self, context):
    """Returns the root of this repository."""
    raise NotImplementedError()

  def proto_file(self, context):
    """Returns the ProtoFile of the recipes config file in this repository. 
    Requires a good checkout."""
    return ProtoFile(InfraRepoConfig().to_recipes_cfg(self.repo_root(context)))


class GitRepoSpec(RepoSpec):
  def __init__(self, id, repo, branch, revision, path):
    self.id = id
    self.repo = repo
    self.branch = branch
    self.revision = revision
    self.path = path

  def checkout(self, context):
    package_dir = context.package_dir
    dep_dir = os.path.join(package_dir, self.id)
    logging.info('Freshening repository %s' % dep_dir)

    if not os.path.isdir(dep_dir):
      _run_cmd([self._git, 'clone', self.repo, dep_dir])
    elif not os.path.isdir(os.path.join(dep_dir, '.git')):
      raise UncleanFilesystemError('%s exists but is not a git repo' % dep_dir)

    try:
      subprocess.check_output([self._git, 'rev-parse', '-q', '--verify',
                               '%s^{commit}' % self.revision], cwd=dep_dir)
    except subprocess.CalledProcessError:
      _run_cmd([self._git, 'fetch'], cwd=dep_dir)
    _run_cmd([self._git, 'reset', '-q', '--hard', self.revision], cwd=dep_dir)

  def check_checkout(self, context):
    dep_dir = os.path.join(context.package_dir, self.id)
    if not os.path.isdir(dep_dir):
      raise UncleanFilesystemError('Dependency %s does not exist' %
                                   dep_dir)
    elif not os.path.isdir(os.path.join(dep_dir, '.git')):
      raise UncleanFilesystemError('Dependency %s is not a git repo' %
                                   dep_dir)

    git_status_command = [self._git, 'status', '--porcelain']
    logging.info('%s', git_status_command)
    output = subprocess.check_output(git_status_command, cwd=dep_dir)
    if output:
      raise UncleanFilesystemError('Dependency %s is unclean:\n%s' %
                                   (dep_dir, output))

  def repo_root(self, context):
    return os.path.join(context.package_dir, self.id, self.path)

  def dump(self):
    buf = package_pb2.DepSpec(
        project_id=self.id,
        url=self.repo,
        branch=self.branch,
        revision=self.revision)
    if self.path:
      buf.path_override = self.path
    return buf

  def updates(self, context):
    """Returns a list of all updates to the branch since the revision this
    repo spec refers to, paired with their commit timestamps; i.e.
    (timestamp, GitRepoSpec).

    Although timestamps are not completely reliable, they are the best tool we
    have to approximate global coherence.
    """
    lines = filter(bool, self._raw_updates(context).strip().split('\n'))
    return [ RepoUpdate(
                 GitRepoSpec(self.id, self.repo, self.branch, rev, self.path))
             for rev in lines ]

  def _raw_updates(self, context):
    self.checkout(context)
    # XXX(luqui): Should this just focus on the recipes subtree rather than
    # the whole repo?
    git = subprocess.Popen([self._git, 'log',
                            '%s..origin/%s' % (self.revision, self.branch),
                            '--pretty=%H',
                            '--reverse'],
                           stdout=subprocess.PIPE,
                           cwd=os.path.join(context.package_dir, self.id))
    (stdout, _) = git.communicate()
    return stdout

  @property
  def _git(self):
    if sys.platform.startswith(('win', 'cygwin')):
      return 'git.bat'
    else:
      return 'git'

  def _components(self):
    return (self.id, self.repo, self.revision, self.path)

  def __eq__(self, other):
    return self._components() == other._components()

  def __ne__(self, other):
    return not self.__eq__(other)


class RootRepoSpec(RepoSpec):
  def __init__(self, proto_file):
    self._proto_file = proto_file

  def checkout(self, context):
    # We assume this is already checked out.
    pass

  def check_checkout(self, context):
    pass

  def repo_root(self, context):
    return context.repo_root

  def proto_file(self, context):
    return self._proto_file




class Package(object):
  """Package represents a loaded package, and contains path and dependency
  information.

  This is accessed by loader.py through RecipeDeps.get_package.
  """
  def __init__(self, repo_spec, deps, recipes_dir):
    self.repo_spec = repo_spec
    self.deps = deps
    self.recipes_dir = recipes_dir

  @property
  def recipe_dirs(self):
    return [os.path.join(self.recipes_dir, 'recipes')]

  @property
  def module_dirs(self):
    return [os.path.join(self.recipes_dir, 'recipe_modules')]

  def find_dep(self, dep_name):
    return self.deps[dep_name]

  def module_path(self, module_name):
    return os.path.join(self.recipes_dir, 'recipe_modules', module_name)


class PackageSpec(object):
  API_VERSION = 1

  def __init__(self, project_id, recipes_path, deps):
    self._project_id = project_id
    self._recipes_path = recipes_path
    self._deps = deps

  @classmethod
  def load_proto(cls, proto_file):
    buf = proto_file.read()
    assert buf.api_version == cls.API_VERSION

    deps = { dep.project_id: GitRepoSpec(dep.project_id,
                                         dep.url,
                                         dep.branch,
                                         dep.revision,
                                         dep.path_override)
             for dep in buf.deps }
    return cls(buf.project_id, buf.recipes_path, deps)

  @property
  def project_id(self):
    return self._project_id

  @property
  def recipes_path(self):
    return self._recipes_path

  @property
  def deps(self):
    return self._deps

  def dump(self):
    return package_pb2.Package(
        api_version=self.API_VERSION,
        project_id=self._project_id,
        recipes_path=self._recipes_path,
        deps=[ self._deps[dep].dump() for dep in sorted(self._deps.keys()) ])

  def updates(self, context):
    """Returns a list of RepoUpdate<PackageSpec>s, corresponding to the updates
    in self's dependencies.

    See iterate_consistent_updates below."""

    dep_updates = _merge([
        self._deps[dep].updates(context) for dep in sorted(self._deps.keys()) ])

    deps_so_far = self._deps
    ret_updates = []
    for update in dep_updates:
      deps_so_far = _updated(deps_so_far, { update.id: update.spec })
      ret_updates.append(RepoUpdate(PackageSpec(
          self._project_id, self._recipes_path, deps_so_far)))
    return ret_updates

  def iterate_consistent_updates(self, proto_file, context):
    """Returns a list of RepoUpdate<PackageSpec>s, corresponding to the updates
    in self's dependencies, with inconsistent dependency graphs filtered out.

    This is the entry point of the rolling logic, which is called by recipes.py.

    To roll, we look at all updates on the specified branches in each of our
    direct dependencies. We don't look at transitive dependencies because
    our direct dependencies are responsible for rolling those. If we have two
    dependencies A and B, each with three updates, we can visualize this in
    a two-dimensional space like so:

           A1 A2 A3
          +--------
       B1 | .  .  .
       B2 | .  .  .
       B3 | .  .  .

    Each of the 9 locations here corresponds to a possible PackageSpec.  Some
    of these will be inconsistent; e.g. A and B depend on the same package at
    different versions.  Let's mark a few with X's to indicate inconsistent
    dependencies:

           A1 A2 A3
          +--------
       B1 | .  .  X
       B2 | .  X  .
       B3 | X  X  .

    We are trying to find which consistent versions to commit, and in which
    order.  We only want to commit in monotone order (left to right and top to
    bottom); i.e. committing a spec depending on A3 then in the next commit
    depending on A2 doesn't make sense.  But as we can see here, there are
    multiple monotone paths.

      A1B1 A2B1 A3B2 A3B3
      A1B1 A1B2 A3B2 A3B3

    So we necessarily need to choose one over the other.  We would like to go
    for as fine a granularity as possible, so it would seem we need to choose
    the longest one.  But since the granularity of our updates depends on the
    granularity of our dependencies' updates, what we would actually aim for is
    "global coherence"; i.e. everybody chooses mutually consistent paths.  So if
    we update A2B1, somebody else who also depends on A and B will update to
    A2B1, in order to be consistent for anybody downstream.

    It also needs to be consistent with the future; e.g. we don't want to choose
    A2B1 if there is an A2 and A1B2 otherwise, because in the future A2 might
    become available, which would make the order of rolls depend on when you
    did the roll.  That leads to, as far as I can tell, the only global
    coherence strategy, which is to roll along whichever axis has the smallest
    time delta from the current configuration.

    HOWEVER timestamps on git commits are not reliable, so we don't do any of
    this logic.  Instead, we rely on the fact that we expect the auto-roller bot
    to roll frequently, which means that we will roll in minimum-time-delta
    order anyway (at least up to an accuracy of the auto-roller bot's cycle
    time).  So in the rare that there are multiple commits to roll, we naively
    choose to roll them in lexicographic order: roll all of A's commits, then
    all of B's.

    In the case that we need rolling to be more distributed, it will be
    important to solve the timestamp issue so we ensure coherence.
    """

    root_spec = RootRepoSpec(proto_file)
    for update in self.updates(context):
      try:
        package_deps = PackageDeps(context)
        # Inconsistent graphs will throw an exception here, thus skipping the
        # yield.
        package_deps._create_from_spec(root_spec, update.spec, allow_fetch=True)
        yield update
      except InconsistentDependencyGraphError:
        pass

  def __eq__(self, other):
    return (
        self._project_id == other._project_id and
        self._recipes_path == other._recipes_path and
        self._deps == other._deps)

  def __ne__(self, other):
    return not self.__eq__(other)


class PackageDeps(object):
  """An object containing all the transitive dependencies of the root package.
  """
  def __init__(self, context):
    self._context = context
    self._repos = {}

  @classmethod
  def create(cls, repo_root, proto_file, allow_fetch=False):
    """Creates a PackageDeps object.

    Arguments:
      repo_root: the root of the repository containing this package.
      proto_file: a ProtoFile object corresponding to the repos recipes.cfg
      allow_fetch: whether to fetch dependencies rather than just checking for
                   them.
    """
    context = PackageContext.from_proto_file(repo_root, proto_file)
    package_deps = cls(context)

    root_package = package_deps._create_package(
        RootRepoSpec(proto_file), allow_fetch)
    return package_deps

  def _create_package(self, repo_spec, allow_fetch):
    if allow_fetch:
      repo_spec.checkout(self._context)
    else:
      try:
        repo_spec.check_checkout(self._context)
      except UncleanFilesystemError as e:
        logging.warn(
            'Unclean environment. You probably need to run "recipes.py fetch"\n'
            '%s' % e.message)

    package_spec = PackageSpec.load_proto(repo_spec.proto_file(self._context))

    return self._create_from_spec(repo_spec, package_spec, allow_fetch)

  def _create_from_spec(self, repo_spec, package_spec, allow_fetch):
    project_id = package_spec.project_id
    if project_id in self._repos:
      if self._repos[project_id] is None:
        raise CyclicDependencyError(
            'Package %s depends on itself' % project_id)
      if repo_spec != self._repos[project_id].repo_spec:
        raise InconsistentDependencyGraphError(
            'Package specs do not match: %s vs %s' %
            (repo_spec, self._repos[project_id].repo_spec))
    self._repos[project_id] = None

    deps = {}
    for dep, dep_repo in sorted(package_spec.deps.items()):
      deps[dep] = self._create_package(dep_repo, allow_fetch)

    package = Package(
        repo_spec, deps,
        os.path.join(repo_spec.repo_root(self._context),
                     package_spec.recipes_path))

    self._repos[project_id] = package
    return package

  # TODO(luqui): Remove this, so all accesses to packages are done
  # via other packages with properly scoped deps.
  def get_package(self, package_id):
    return self._repos[package_id]

  @property
  def all_recipe_dirs(self):
    for repo in self._repos.values():
      for subdir in repo.recipe_dirs:
        yield str(subdir)

  @property
  def all_module_dirs(self):
    for repo in self._repos.values():
      for subdir in repo.module_dirs:
        yield str(subdir)


def _run_cmd(cmd, cwd=None):
  cwd_str = ' (in %s)' % cwd if cwd else ''
  logging.info('%s%s', cmd, cwd_str)
  subprocess.check_call(cmd, cwd=cwd)


def _merge2(xs, ys, compare=lambda x, y: x <= y):
  """Merges two sorted iterables, preserving sort order.

  >>> list(_merge2([1, 3, 6], [2, 4, 5]))
  [1, 2, 3, 4, 5, 6]
  >>> list(_merge2([1, 2, 3], []))
  [1, 2, 3]
  >>> list(_merge2([], [4, 5, 6]))
  [4, 5, 6]
  >>> list(_merge2([], []))
  []
  >>> list(_merge2([4, 2], [3, 1], compare=lambda x, y: x >= y))
  [4, 3, 2, 1]

  The merge is left-biased and preserves order within each argument.

  >>> list(_merge2([1, 4], [3, 2], compare=lambda x, y: True))
  [1, 4, 3, 2]
  """
  nothing = object()

  xs = iter(xs)
  ys = iter(ys)
  x = nothing
  y = nothing
  try:
    x = xs.next()
    y = ys.next()

    while True:
      if compare(x, y):
        yield x
        x = nothing
        x = xs.next()
      else:
        yield y
        y = nothing
        y = ys.next()
  except StopIteration:
    if x is not nothing: yield x
    for x in xs: yield x
    if y is not nothing: yield y
    for y in ys: yield y


def _merge(xss, compare=lambda x, y: x <= y):
  """Merges a sequence of sorted iterables in sorted order.

  >>> list(_merge([ [1,5], [2,5,6], [], [0,7] ]))
  [0, 1, 2, 5, 5, 6, 7]
  >>> list(_merge([ [1,2,3] ]))
  [1, 2, 3]
  >>> list(_merge([]))
  []
  """
  return reduce(lambda xs, ys: _merge2(xs, ys, compare=compare), xss, [])


def _updated(d, updates):
  """Updates a dictionary without mutation.

  >>> d = { 'x': 1, 'y': 2 }
  >>> sorted(_updated(d, { 'y': 3, 'z': 4 }).items())
  [('x', 1), ('y', 3), ('z', 4)]
  >>> sorted(d.items())
  [('x', 1), ('y', 2)]
  """

  d = copy.copy(d)
  d.update(updates)
  return d
