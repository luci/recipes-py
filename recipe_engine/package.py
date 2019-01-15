# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy
import errno
import logging
import operator
import os
import subprocess
import sys

from . import fetch
from . import package_io
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
        try:
          os.unlink(os.path.join(root, f))
        except OSError as ex:
          # If multiple things are cleaning pyc's at the same time this can
          # race. Fortunately we only care that SOMETHING deleted the pyc :)
          if ex.errno != errno.ENOENT:
            raise


class PackageContext(object):
  """Contains information about where the root package and its dependency
  checkouts live.

  - repo_root is the absolute path to the repository containing the root
    package.
  - recipes_path is the relative path in the repository to where the recipes
    live.
  """

  def __init__(self, repo_root, recipes_path):
    self.repo_root = repo_root
    self.recipes_path = recipes_path

  @property
  def package_dir(self):
    """package_dir is where dependency checkouts live, e.g.
    <repo_root>/path/to/recipes/.recipe_deps/...
    """
    return os.path.join(self.recipes_dir, '.recipe_deps')

  @property
  def recipes_dir(self):
    """recipes_dir is the absolute path to the root repo's recipes subdirectory.
    """
    return os.path.join(self.repo_root, self.recipes_path)

  def __repr__(self):
    return 'PackageContext(%r, %r)' % (self.repo_root, self.recipes_path)

  @classmethod
  def from_package_pb(cls, repo_root, package_pb):
    return cls(
      os.path.abspath(repo_root),
      str(package_pb.recipes_path).replace('/', os.sep))


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

  def current(self):
    """Returns the CommitMetadata for the current revision.

    Returns CommitMetadata.
    """
    raise NotImplementedError()

  def updates(self):
    """Returns a list of all updates to the branch since the revision this
    repo spec refers to.

    Returns list(CommitMetadata), one per available update.
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
    return self.current().spec

  def _dep_dir(self, context):
    return os.path.join(context.package_dir, self.project_id)

  def checkout(self, context):
    self.backend.checkout(self.revision)
    cleanup_pyc(self._dep_dir(context))

  def repo_root(self, context):
    return os.path.join(self._dep_dir(context), self.path)

  @property
  def _branch_for_remote(self):
    if self.branch.startswith('refs/'):
      return self.branch
    return 'refs/heads/' + self.branch

  def current(self):
    return self.backend.commit_metadata(self.revision)

  def updates(self):
    """Returns a list of revisions on the branch between the pinned revision
    and the tracked branch.

    Returns list(CommitMetadata)
    """
    return self.backend.updates(
      self.revision, self.backend.resolve_refspec(self._branch_for_remote))

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

  def __repr__(self):
    return (
      'PathRepoSpec{project_id="%(project_id)s", path="%(path)s"}'
      % self.__dict__
    )

  def current(self):
    return fetch.CommitMetadata(
      '',
      '',
      0,
      (),
      self.spec_pb(),
      False
    )

  def updates(self):
    return []

  def fetch(self):
    pass

  def checkout(self, context):
    pass

  def repo_root(self, _context):
    return self.path

  def spec_pb(self):
    return package_io.PackageFile(
      package_io.InfraRepoConfig().to_recipes_cfg(self.path)).read()

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self.path == other.path


class RootRepoSpec(RepoSpec):
  def __init__(self, package_file):
    self._package_file = package_file

  def current(self):
    raise NotImplementedError()

  def updates(self):
    raise NotImplementedError()

  def fetch(self):
    # We assume this is already checked out.
    pass

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


class PackageSpec(object):
  def __init__(self, api_version, project_id, recipes_path, deps, spec_pb):
    self._api_version = api_version
    self._project_id = project_id
    self._recipes_path = recipes_path
    self._deps = deps
    self.spec_pb = spec_pb

  def __repr__(self):
    return 'PackageSpec(%s, %s, %r)' % (self._project_id, self._recipes_path,
                                        self._deps)

  @classmethod
  def from_package_pb(cls, context, buf):
    deps = { pid: cls._spec_for_dep(context, pid, dep)
             for pid, dep in buf.deps.iteritems() }
    return cls(buf.api_version, str(buf.project_id), str(buf.recipes_path),
               deps, copy.deepcopy(buf))

  @classmethod
  def _spec_for_dep(cls, context, project_id, dep):
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
        os.path.join(context.package_dir, project_id),
        dep.url))

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
  def create(cls, context, package_file, overrides):
    """Creates a PackageDeps object.

    If any of the dependencies are not overridden in overrides, this will do
    network access to bring them up to date.

    Arguments:
      context (PackageContext)
      package_file: a PackageFile object corresponding to the repos recipes.cfg
      overrides: a dictionary of project overrides. Dictionary keys
                 are the `project_id` field to override, and dictionary values
                 are the override path.
    """
    # Apply deps of overrides to ensure consistent dependency graph.
    # We don't need to recurse further, since by design the deps
    # should already be transitive.
    overrides_deep = {}
    for project_id, path in overrides.iteritems():
      repo_spec = PathRepoSpec(project_id, path)
      repo_spec.fetch()
      overrides_deep[project_id] = repo_spec

      package_spec = PackageSpec.from_package_pb(context, repo_spec.spec_pb())
      for sub_project_id, sub_repo_spec in package_spec.deps.iteritems():
        # If there's no explicit override for this dependency, then it becomes
        # an implied ("deep") override.
        if sub_project_id not in overrides:
          sub_repo_spec.fetch()
          overrides_deep[sub_project_id] = sub_repo_spec

    package_deps = cls(overrides=overrides_deep)

    # Initialize all repos to their intended state.
    pspec = PackageSpec.from_package_pb(context, package_file.read())
    for project_id, dep in pspec.deps.iteritems():
      effective_dep = overrides_deep.get(project_id, dep)
      effective_dep.checkout(context)

    package_deps._root_package = package_deps._create_package(
      context, RootRepoSpec(package_file))

    return package_deps

  def _create_package(self, context, repo_spec):
    package_spec = PackageSpec.from_package_pb(
      context, repo_spec.spec_pb())

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
