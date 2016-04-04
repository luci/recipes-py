# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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


class FetchNotAllowedError(Exception):
  pass


class InconsistentDependencyGraphError(Exception):
  pass


class CyclicDependencyError(Exception):
  pass


def cleanup_pyc(path):
  """Removes any .pyc files from |path|'s directory tree.
  This ensures we always use the fresh code.
  """
  for root, dirs, files in os.walk(path):
    for f in files:
      if f.endswith('.pyc'):
        os.unlink(os.path.join(root, f))


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
  - allow_fetch controls whether automatic fetching latest repo contents
    from origin is allowed
  """

  def __init__(self, recipes_dir, package_dir, repo_root, allow_fetch):
    self.recipes_dir = recipes_dir
    self.package_dir = package_dir
    self.repo_root = repo_root
    self.allow_fetch = allow_fetch

  @classmethod
  def from_proto_file(cls, repo_root, proto_file, allow_fetch):
    buf = proto_file.read()

    recipes_path = str(buf.recipes_path).replace('/', os.sep)

    return cls(os.path.join(repo_root, recipes_path),
               os.path.join(repo_root, recipes_path, '.recipe_deps'),
               repo_root,
               allow_fetch)


class CommitInfo(object):
  """Holds the stuff we need to know about a commit."""
  def __init__(self, author, message, repo_id, revision):
    self.author = author
    self.message = message
    self.repo_id = repo_id
    self.revision = revision

  def dump(self):
    return {
      'author': self.author,
      'message': self.message,
      'repo_id': self.repo_id,
      'revision': self.revision,
    }


@functools.total_ordering
class RepoUpdate(object):
  """Wrapper class that specifies the sort order of roll updates when merging.
  """

  def __init__(self, spec, commit_infos=()):
    self.spec = spec
    self.commit_infos = commit_infos

  @property
  def project_id(self):
    return self.spec.project_id

  def __eq__(self, other):
    return ((self.project_id, self.spec.revision) ==
            (other.project_id, other.spec.revision))

  def __le__(self, other):
    return ((self.project_id, self.spec.revision) <=
            (other.project_id, other.spec.revision))

  def __str__(self):
    return '%s@%s' % (self.project_id, getattr(self.spec, 'revision', None))


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

  def repo_root(self, context):
    """Returns the root of this repository."""
    raise NotImplementedError()

  def __eq__(self, other):
    raise NotImplementedError()

  def __ne__(self, other):
    return not (self == other)

  def proto_file(self, context):
    """Returns the ProtoFile of the recipes config file in this repository. 
    Requires a good checkout."""
    return ProtoFile(InfraRepoConfig().to_recipes_cfg(self.repo_root(context)))


class GitRepoSpec(RepoSpec):
  def __init__(self, project_id, repo, branch, revision, path):
    self.project_id = project_id
    self.repo = repo
    self.branch = branch
    self.revision = revision
    self.path = path

  def __str__(self):
    return ('GitRepoSpec{project_id="%(project_id)s", repo="%(repo)s", '
            'branch="%(branch)s", revision="%(revision)s", '
            'path="%(path)s"}' % self.__dict__)

  def run_git(self, context, *args):
    cmd = [self._git]
    if context is not None:
      cmd += ['-C', self._dep_dir(context)]
    cmd += list(args)

    logging.info('Running: %s', cmd)
    return subprocess.check_output(cmd)

  def checkout(self, context):
    dep_dir = self._dep_dir(context)
    logging.info('Freshening repository %s', dep_dir)

    if not os.path.isdir(dep_dir):
      if context.allow_fetch:
        self.run_git(None, 'clone', self.repo, dep_dir)
      else:
        raise FetchNotAllowedError(
            'need to clone %s but fetch not allowed' % self.repo)
    elif not os.path.isdir(os.path.join(dep_dir, '.git')):
      raise UncleanFilesystemError('%s exists but is not a git repo' % dep_dir)

    try:
      self.run_git(context, 'rev-parse', '-q', '--verify',
                   '%s^{commit}' % self.revision)
    except subprocess.CalledProcessError:
      if context.allow_fetch:
        self.run_git(context, 'fetch')
      else:
        raise FetchNotAllowedError(
            'need to fetch %s but fetch not allowed' % self.repo)
    self.run_git(context, 'reset', '-q', '--hard', self.revision)
    cleanup_pyc(dep_dir)

  def repo_root(self, context):
    return os.path.join(self._dep_dir(context), self.path)

  def dump(self):
    buf = package_pb2.DepSpec(
        project_id=self.project_id,
        url=self.repo,
        branch=self.branch,
        revision=self.revision)
    if self.path:
      buf.path_override = self.path
    return buf

  def updates(self, context):
    """Returns a list of all updates to the branch since the revision this
    repo spec refers to.
    """
    subdir = self.proto_file(context).read().recipes_path

    lines = filter(bool, self._raw_updates(context, subdir).strip().split('\n'))
    updates = []
    for rev in lines:
      info = self._get_commit_info(rev, context)
      updates.append(RepoUpdate(
                 GitRepoSpec(self.project_id, self.repo, self.branch, rev,
                             self.path),
                 commit_infos=(info,)))
    return updates

  def _raw_updates(self, context, subdir):
    self.checkout(context)
    self.run_git(context, 'fetch')
    args = ['rev-list', '--reverse',
            '%s..origin/%s' % (self.revision, self.branch)]
    if subdir:
      # We add proto_file to the list of paths to check because it might contain
      # other upstream rolls, which we want.
      args.extend(['--', subdir + os.path.sep, self.proto_file(context).path])
    return self.run_git(context, *args)

  def _get_commit_info(self, rev, context):
    author = self.run_git(context, 'show', '-s', '--pretty=%aE', rev).strip()
    message = self.run_git(context, 'show', '-s', '--pretty=%B', rev).strip()
    return CommitInfo(author, message, self.project_id, rev)

  def _dep_dir(self, context):
    return os.path.join(context.package_dir, self.project_id)

  @property
  def _git(self):
    if sys.platform.startswith(('win', 'cygwin')):
      return 'git.bat'
    else:
      return 'git'

  def _components(self):
    return (self.project_id, self.repo, self.revision, self.path)

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self._components() == other._components()


class PathRepoSpec(RepoSpec):
  """A RepoSpec implementation that uses a local filesystem path."""

  def __init__(self, path):
    self.path = path

  def __str__(self):
    return 'PathRepoSpec{path="%(path)s"}' % self.__dict__

  def checkout(self, context):
    pass

  def repo_root(self, _context):
    return self.path

  def proto_file(self, context):
    """Returns the ProtoFile of the recipes config file in this repository. 
    Requires a good checkout."""
    return ProtoFile(InfraRepoConfig().to_recipes_cfg(self.path))

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self.path == other.path


class RootRepoSpec(RepoSpec):
  def __init__(self, proto_file):
    self._proto_file = proto_file

  def checkout(self, context):
    # We assume this is already checked out.
    pass

  def repo_root(self, context):
    return context.repo_root

  def proto_file(self, context):
    return self._proto_file

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self._proto_file == other._proto_file


class Package(object):
  """Package represents a loaded package, and contains path and dependency
  information.

  This is accessed by loader.py through RecipeDeps.get_package.
  """
  def __init__(self, name, repo_spec, deps, repo_root, recipes_dir):
    self.name = name
    self.repo_spec = repo_spec
    self.deps = deps
    self.repo_root = repo_root
    self.recipes_dir = recipes_dir

  def __repr__(self):
    return '<Package(name=%r,repo_spec=%r,deps=%r,recipes_dir=%r)>' % (
        self.name, self.repo_spec, self.deps, self.recipes_dir)

  @property
  def recipe_dirs(self):
    return [os.path.join(self.recipes_dir, 'recipes')]

  @property
  def module_dirs(self):
    return [os.path.join(self.recipes_dir, 'recipe_modules')]

  def find_dep(self, dep_name):
    if dep_name == self.name:
      return self

    assert dep_name in self.deps, (
        '%s does not exist or is not declared as a dependency of %s' % (
            dep_name, self.name))
    return self.deps[dep_name]

  def module_path(self, module_name):
    return os.path.join(self.recipes_dir, 'recipe_modules', module_name)

  def loop_over_recipe_modules():
    for path in self.module_dirs:
      if os.path.isdir(path):
        for item in os.listdir(path):
          subpath = os.path.join(path, item)
          if _is_recipe_module_dir(subpath):
            yield subpath

  def __repr__(self):
    return 'Package(%r, %r, %r, %r)' % (
        self.name, self.repo_spec, self.deps, self.recipe_dirs)

  def __str__(self):
    return 'Package %s, with dependencies %s' % (self.name, self.deps.keys())


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

    deps = { str(dep.project_id): cls.spec_for_dep(dep)
             for dep in buf.deps }
    return cls(str(buf.project_id), str(buf.recipes_path), deps)

  @classmethod
  def spec_for_dep(cls, dep):
    """Returns a RepoSpec for the given dependency protobuf.

    This assumes all dependencies are Git dependencies.
    """
    return GitRepoSpec(str(dep.project_id),
                       str(dep.url),
                       str(dep.branch),
                       str(dep.revision),
                       str(dep.path_override))

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
      deps_so_far = _updated(deps_so_far, { update.project_id: update.spec })
      ret_updates.append(RepoUpdate(PackageSpec(
          self._project_id, self._recipes_path, deps_so_far),
          commit_infos=update.commit_infos))
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

    # We keep track of accumulated commit infos, so that we correctly attribute
    # authors even when we skip a state due to inconsistent dependencies.
    commit_infos_accum = []
    for update in self.updates(context):
      commit_infos_accum.extend(update.commit_infos)
      try:
        package_deps = PackageDeps(context)
        # Inconsistent graphs will throw an exception here, thus skipping the
        # yield.
        package_deps._create_from_spec(root_spec, update.spec)
        new_update = RepoUpdate(update.spec, tuple(commit_infos_accum))
        commit_infos_accum = []
        yield new_update
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
  def __init__(self, context, overrides=None):
    self._context = context
    self._packages = {}
    self._overrides = overrides or {}
    self._root_package = None

  @property
  def root_package(self):
    return self._root_package

  @classmethod
  def create(cls, repo_root, proto_file, allow_fetch=False, overrides=None):
    """Creates a PackageDeps object.

    Arguments:
      repo_root: the root of the repository containing this package.
      proto_file: a ProtoFile object corresponding to the repos recipes.cfg
      allow_fetch: whether to fetch dependencies rather than just checking for
                   them.
      overrides: if not None, a dictionary of project overrides. Dictionary keys
                 are the `project_id` field to override, and dictionary values
                 are the override path.
    """
    context = PackageContext.from_proto_file(repo_root, proto_file, allow_fetch)
    if overrides:
      overrides = {project_id: PathRepoSpec(path)
                   for project_id, path in overrides.iteritems()}
    package_deps = cls(context, overrides=overrides)

    package_deps._root_package = package_deps._create_package(RootRepoSpec(proto_file))

    return package_deps

  def _create_package(self, repo_spec):
    repo_spec.checkout(self._context)
    package_spec = PackageSpec.load_proto(repo_spec.proto_file(self._context))
    return self._create_from_spec(repo_spec, package_spec)

  def _create_from_spec(self, repo_spec, package_spec):
    project_id = package_spec.project_id
    repo_spec = self._overrides.get(project_id, repo_spec)
    if project_id in self._packages:
      if self._packages[project_id] is None:
        raise CyclicDependencyError(
            'Package %s depends on itself' % project_id)
      if repo_spec != self._packages[project_id].repo_spec:
        raise InconsistentDependencyGraphError(
            'Package specs do not match: %s vs %s' %
            (repo_spec, self._packages[project_id].repo_spec))
    self._packages[project_id] = None

    deps = {}
    for dep, dep_repo in sorted(package_spec.deps.items()):
      deps[dep] = self._create_package(dep_repo)

    package = Package(
        project_id, repo_spec, deps,
        repo_spec.repo_root(self._context),
        os.path.join(repo_spec.repo_root(self._context),
                     package_spec.recipes_path))

    self._packages[project_id] = package
    return package

  # TODO(luqui): Remove this, so all accesses to packages are done
  # via other packages with properly scoped deps.
  def get_package(self, package_id):
    return self._packages[package_id]

  @property
  def packages(self):
    for p in self._packages.values():
      yield p

  @property
  def engine_recipes_py(self):
    return os.path.join(self._context.repo_root, 'recipes.py')


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
    if x is not nothing:
      yield x
    for x in xs:
      yield x
    if y is not nothing:
      yield y
    for y in ys:
      yield y


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
