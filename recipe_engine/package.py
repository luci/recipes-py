# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy
import logging
import operator
import os
import subprocess
import sys

from . import package_io
from . import fetch

from . import env

from . import package_pb2

LOGGER = logging.getLogger(__name__)


class InconsistentDependencyGraphError(Exception):
  def __init__(self, project_id, specs):
    self.project_id = project_id
    self.specs = specs

  def __str__(self):
    return 'Package specs for %s do not match: %s vs %s' % (
        self.project_id, self.specs[0], self.specs[1])


class CyclicDependencyError(Exception):
  pass


def cleanup_pyc(path):
  """Removes any .pyc files from |path|'s directory tree.

  This ensures we always use the fresh code.
  """
  for root, _dirs, files in os.walk(path):
    for f in files:
      if f.endswith('.pyc'):
        os.unlink(os.path.join(root, f))


class InfraRepoConfig(object):
  def to_recipes_cfg(self, repo_root):
    return os.path.join(repo_root, self.relative_recipes_cfg)

  @property
  def relative_recipes_cfg(self):
    # TODO(luqui): This is not always correct.  It can be configured in
    # infra/config:refs.cfg.
    return os.path.join('infra', 'config', 'recipes.cfg')

  def from_recipes_cfg(self, recipes_cfg):
    return os.path.dirname( # <repo root>
            os.path.dirname( # infra
              os.path.dirname( # config
                os.path.abspath(recipes_cfg)))) # recipes.cfg


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

  def __repr__(self):
    return 'PackageContext(%r, %r, %r, %s)' % (
      self.recipes_dir, self.package_dir, self.repo_root, self.allow_fetch)

  def project_checkout_dir(self, project_id):
    return os.path.join(self.package_dir, project_id)

  @classmethod
  def from_package_file(cls, repo_root, package_file, allow_fetch,
                        deps_path=None):
    buf = package_file.read()

    recipes_path = str(buf.recipes_path).replace('/', os.sep)

    if not deps_path:
      deps_path = os.path.join(repo_root, recipes_path, '.recipe_deps')

    return cls(os.path.join(repo_root, recipes_path),
               os.path.abspath(deps_path),
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


class RepoSpec(object):
  """RepoSpec is the specification of a repository to check out.

  The prototypical example is GitRepoSpec, which includes a url, revision,
  and branch.
  """

  def fetch(self):
    """Do any network fetching stuff."""
    raise NotImplementedError()

  def checkout(self, context):
    """Fetches the specified package and returns the path of the package root
    (the directory that contains recipes and recipe_modules).
    """
    raise NotImplementedError()

  def repo_root(self, context):
    """Returns the root of this repository."""
    raise NotImplementedError()

  def updates(self, other_revision=None):
    """Returns a list of all updates to the branch since the revision this
    repo spec refers to.

    Args:
      other_revision (str|None) - The target other revision to return the list
      to. If None, it uses this spec's target branch.

    Returns list(RepoSpec), one per available update.
    """
    raise NotImplementedError()

  def __eq__(self, other):
    raise NotImplementedError()

  def __ne__(self, other):
    return not (self == other)

  def spec_pb(self):
    """Returns the PackageFile of the recipes config file in this repository."""
    raise NotImplementedError()


class GitRepoSpec(RepoSpec):
  def __init__(self, project_id, repo, branch, revision, path, backend):
    """
    Args:
      project_id (str): The id of the project (e.g. "recipe_engine").
      repo (str): The url of the remote git repo.
      branch (str): The git branch of the repo.
      revision (str): The target revision for this dependency.
      path (str): The subdirectory in the repo where the recipes live.
      backend (fetch.Backend): The git backend managing this directory.
    """
    self.project_id = project_id
    self.repo = repo
    self.branch = branch
    self.revision = revision
    self.path = path
    self.backend = backend

  def __repr__(self):
    return ('GitRepoSpec{project_id="%(project_id)s", repo="%(repo)s", '
            'branch="%(branch)s", revision="%(revision)s", '
            'path="%(path)s"}' % self.__dict__)

  def fetch(self):
    return self.backend.fetch(self.branch)

  def spec_pb(self):
    return self.backend.commit_metadata(self.revision).spec

  def checkout(self, context):
    self.backend.checkout(self.revision)
    cleanup_pyc(self._dep_dir(context))

  def repo_root(self, context):
    return os.path.join(self._dep_dir(context), self.path)

  def dump(self):
    return package_pb2.DepSpec(
      url=self.repo,
      branch=self.branch,
      revision=self.revision,
      path_override = self.path)

  @property
  def _branch_for_remote(self):
    if self.branch.startswith('refs/'):
      return self.branch
    return 'refs/heads/' + self.branch

  def updates(self, other_revision=None):
    updates = []
    for rev in self.raw_updates(other_revision):
      updates.append(GitRepoSpec(
          self.project_id,
          self.repo,
          self.branch,
          rev,
          self.path,
          self.backend))
    return updates

  def commit_infos(self, other_refspec):
    """Returns a list of commit infos on the branch between the pinned revision
    and |other_revision|.
    """
    raw_updates = self.raw_updates(other_refspec)
    return [self._get_commit_info(rev) for rev in raw_updates]

  def raw_updates(self, other_refspec):
    """Returns a list of revisions on the branch between the pinned revision
    and |other_refspec|.
    """
    paths = []
    subdir = self.spec_pb().recipes_path
    if subdir:
      # We add package_file to the list of paths to check because it might
      # contain other upstream rolls, which we want.
      paths.extend([subdir + os.path.sep,
                    InfraRepoConfig().relative_recipes_cfg])

    if other_refspec is None:
      other_refspec = self._branch_for_remote
    other_revision = self.backend.resolve_refspec(other_refspec)
    return self.backend.updates(self.revision, other_revision, paths)

  def _get_commit_info(self, rev):
    metadata = self.backend.commit_metadata(rev)
    return CommitInfo(
      metadata.author_email, '\n'.join(metadata.message_lines),
      self.project_id, rev)

  def _dep_dir(self, context):
    return os.path.join(context.package_dir, self.project_id)

  def _components(self):
    return (self.project_id, self.repo, self.revision, self.path)

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self._components() == other._components()


class PathRepoSpec(RepoSpec):
  """A RepoSpec implementation that uses a local filesystem path."""

  def __init__(self, project_id, path):
    self.project_id = project_id
    self.path = path

  def __str__(self):
    return (
      'PathRepoSpec{project_id="%(project_id)s", path="%(path)s"}'
      % self.__dict__
    )

  def fetch(self):
    pass

  def checkout(self, context):
    pass

  def repo_root(self, _context):
    return self.path

  def spec_pb(self):
    return package_io.PackageFile(
      InfraRepoConfig().to_recipes_cfg(self.path)).read()

  def updates(self, other_revision=None):
    return []

  def dump(self):
    """Returns the package.proto DepSpec form of this RepoSpec."""
    return package_pb2.DepSpec(
        url='file://'+self.path)

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self.path == other.path


class RootRepoSpec(RepoSpec):
  def __init__(self, package_file):
    self._package_file = package_file

  def fetch(self):
    # We assume this is already checked out.
    pass

  def updates(self, other_revision=None):
    raise NotImplementedError()

  def checkout(self, context):
    # We assume this is already checked out.
    pass

  def repo_root(self, context):
    return context.repo_root

  def spec_pb(self):
    return self._package_file.read()

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self._package_file == other._package_file


class Package(object):
  """Package represents a loaded package, and contains path and dependency
  information.

  This is accessed by loader.py through RecipeDeps.get_package.
  """
  def __init__(self, name, repo_spec, deps, repo_root, relative_recipes_dir):
    self.name = name
    self.repo_spec = repo_spec
    self.deps = deps
    self.repo_root = repo_root
    self.relative_recipes_dir = relative_recipes_dir

  @property
  def recipes_dir(self):
    return os.path.join(self.repo_root, self.relative_recipes_dir)

  @property
  def recipe_dir(self):
    return os.path.join(self.recipes_dir, 'recipes')

  @property
  def module_dir(self):
    return os.path.join(self.recipes_dir, 'recipe_modules')

  def find_dep(self, dep_name):
    if dep_name == self.name:
      return self

    assert dep_name in self.deps, (
        '%s does not exist or is not declared as a dependency of %s' % (
            dep_name, self.name))
    return self.deps[dep_name]

  def module_path(self, module_name):
    return os.path.join(self.recipes_dir, 'recipe_modules', module_name)

  def __repr__(self):
    return 'Package(%r, %r, %r, %r)' % (
        self.name, self.repo_spec, self.deps, self.recipe_dir)

  def __str__(self):
    return 'Package %s, with dependencies %s' % (self.name, self.deps.keys())


class RollCandidate(object):
  """RollCandidate represents a recipe roll candidate, i.e. updates
  to pinned revisions of recipe dependencies.

  This is mostly used by recipes.py autoroll command.
  """

  def __init__(self, package_spec, update):
    self._package_spec = package_spec
    self._updates = {
      update.project_id: update,
    }

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self.__dict__ == other.__dict__

  def get_affected_projects(self):
    return self._updates.keys()

  def make_consistent(self, context, root_spec):
    """Attempts to make the after-roll dependency graph consistent by rolling
    other package dependencies (changing their revisions). A consistent
    dependency graph means that all of the repos in the graph are pinned
    at the same revision.

    Returns True on success.
    """
    while True:
      try:
        package_deps = PackageDeps()
        package_deps._create_from_spec(context, root_spec,
                                       self.get_rolled_spec())
        return True
      except InconsistentDependencyGraphError as e:
        # Don't update the same project twice - that'd mean we have two
        # conflicting updates anyway.
        if e.project_id in self._updates:
          return False

        # Get the spec that is different from the one we already have.
        # The order in which they're returned is not guaranteed.
        current_revision = self._package_spec.deps[e.project_id].revision
        other_spec = e.specs[1]
        if other_spec.revision == current_revision:
          other_spec = e.specs[0]

        # Prevent rolling backwards.
        more_recent_revision = other_spec.backend.get_more_recent_revision(
          current_revision, other_spec.revision)
        if more_recent_revision != other_spec.revision:
          return False

        self._updates[other_spec.project_id] = other_spec

  def get_rolled_spec(self):
    """Returns a PackageSpec with all the deps updates from this roll."""
    new_deps = _updated(
        self._package_spec.deps,
        { project_id: spec for project_id, spec in
          self._updates.iteritems() })
    return PackageSpec(
        self._package_spec.api_version,
        self._package_spec.project_id,
        self._package_spec.recipes_path,
        new_deps)

  def get_commit_infos(self):
    """Returns a mapping project_id -> list of commits from that repo
    that are getting pulled by this roll.
    """
    commit_infos = {}

    for project_id, update in self._updates.iteritems():
      commit_infos[project_id] = self._package_spec.deps[
          project_id].commit_infos(update.revision)

    return commit_infos

  def to_dict(self):
    return {
        'spec': str(self.get_rolled_spec().dump()),
        'commit_infos': self.get_commit_infos(),
    }


class PackageSpec(object):
  def __init__(self, api_version, project_id, recipes_path, deps):
    self._api_version = api_version
    self._project_id = project_id
    self._recipes_path = recipes_path
    self._deps = deps

  def __repr__(self):
    return 'PackageSpec(%s, %s, %r)' % (self._project_id, self._recipes_path,
                                        self._deps)

  @classmethod
  def load_package(cls, context, package_file):
    return cls.from_package(context, package_file.read())

  @classmethod
  def from_package(cls, context, buf):
    deps = { pid: cls.spec_for_dep(context, pid, dep)
             for pid, dep in buf.deps.iteritems() }
    return cls(buf.api_version, str(buf.project_id), str(buf.recipes_path),
               deps)

  @classmethod
  def spec_for_dep(cls, context, project_id, dep):
    """Returns a RepoSpec for the given dependency protobuf."""
    url = str(dep.url)
    if url.startswith('file://'):
      return PathRepoSpec(str(project_id), url[len('file://'):])

    backend_class = fetch.Backend.class_for_type(dep.repo_type)

    return GitRepoSpec(
      str(project_id),
      url,
      str(dep.branch),
      str(dep.revision),
      str(dep.path_override),
      backend_class(
        context.project_checkout_dir(project_id),
        dep.url,
        context.allow_fetch))

  @property
  def project_id(self):
    return self._project_id

  @property
  def recipes_path(self):
    return self._recipes_path

  @property
  def deps(self):
    return self._deps

  @property
  def api_version(self):
    return self._api_version

  def dump(self):
    return package_pb2.Package(
        api_version=self._api_version,
        project_id=self._project_id,
        recipes_path=self._recipes_path,
        deps={k: v.dump() for k, v in self._deps.iteritems()})

  def roll_candidates(self, root_spec, context):
    """Returns list of consistent roll candidates, and rejected roll candidates.

    The first one is sorted by score, descending. The more commits are pulled by
    the roll, the higher score.

    Second list is included to distinguish between a situation where there are
    no roll candidates from one where there are updates but they're not
    consistent.

    context.allow_fetch must be True.
    """
    # First, pre-fetch all the available data from the remotes.
    if not context.allow_fetch:
      raise ValueError('Calling roll_candidates with allow_fetch==False.')

    for repo_spec in self.deps.values():
      repo_spec.fetch()

    candidates = []
    rejected_candidates = []
    for dep in sorted(self._deps.keys()):
      for update in self._deps[dep].updates():
        candidate = RollCandidate(self, update)
        if not candidate.make_consistent(context, root_spec):
          rejected_candidates.append(candidate)
          continue
        # Computing the score requires running git commands to get info
        # about commits. This is potentially expensive, so do it once
        # and store results.
        score = sum(len(ci) for ci in candidate.get_commit_infos().values())
        candidates.append((candidate, score))

    return ([t[0] for t in
             sorted(candidates, key=operator.itemgetter(1), reverse=True)],
            rejected_candidates)

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
  def __init__(self, overrides=None):
    self._packages = {}
    self._overrides = overrides or {}
    self._root_package = None

  @property
  def root_package(self):
    return self._root_package

  @classmethod
  def create(cls, repo_root, package_file, deps_path=None, allow_fetch=False,
             overrides=None):
    """Creates a PackageDeps object.

    Arguments:
      repo_root: the root of the repository containing this package.
      package_file: a PackageFile object corresponding to the repos recipes.cfg
      allow_fetch: whether to fetch dependencies rather than just checking for
                   them.
      overrides: if not None, a dictionary of project overrides. Dictionary keys
                 are the `project_id` field to override, and dictionary values
                 are the override path.
    """
    context = PackageContext.from_package_file(
      repo_root, package_file, allow_fetch, deps_path=deps_path)

    if overrides:
      overrides = {project_id: PathRepoSpec(project_id, path)
                   for project_id, path in overrides.iteritems()}
    package_deps = cls(overrides=overrides)

    if allow_fetch:
      # initialize all repos to their intended state.
      package_spec = PackageSpec.from_package(
        context, RootRepoSpec(package_file).spec_pb())
      for repo_spec in package_spec.deps.values():
        repo_spec.checkout(context)

    package_deps._root_package = package_deps._create_package(
      context, RootRepoSpec(package_file))

    return package_deps

  def _create_package(self, context, repo_spec):
    package_spec = PackageSpec.from_package(
      context, repo_spec.spec_pb())
    return self._create_from_spec(context, repo_spec, package_spec)

  def _create_from_spec(self, context, repo_spec, package_spec):
    project_id = package_spec.project_id
    repo_spec = self._overrides.get(project_id, repo_spec)
    if project_id in self._packages:
      # TODO(phajdan.jr): Are exceptions the best way to report these errors?
      # The way this is used in practice, especially inconsistent dependency
      # graph condition, might be considered as using exceptions for control
      # flow.
      if self._packages[project_id] is None:
        raise CyclicDependencyError(
            'Package %s depends on itself' % project_id)
      if repo_spec != self._packages[project_id].repo_spec:
        raise InconsistentDependencyGraphError(
            project_id, (repo_spec, self._packages[project_id].repo_spec))
    self._packages[project_id] = None

    deps = {}
    for dep, dep_repo in sorted(package_spec.deps.items()):
      dep_repo = self._overrides.get(dep, dep_repo)
      deps[dep] = self._create_package(context, dep_repo)

    package = Package(
        project_id, repo_spec, deps,
        repo_spec.repo_root(context),
        package_spec.recipes_path)

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
    return os.path.join(
      self._packages['recipe_engine'].repo_root, 'recipes.py')


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
