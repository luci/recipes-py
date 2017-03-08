# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy
import difflib
import logging
import operator
import os
import subprocess
import sys

from . import env

from google.protobuf import text_format
from . import package_pb2
from . import fetch


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
  def from_proto_file(cls, repo_root, proto_file, allow_fetch, deps_path=None):
    buf = proto_file.read()

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
  def __init__(self, project_id, repo, branch, revision, path, backend):
    self.project_id = project_id
    self.repo = repo
    self.branch = branch
    self.revision = revision
    self.path = path
    self.backend = backend

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
    checkout_dir = self._dep_dir(context)
    self.backend.checkout(
        self.repo, self.revision, checkout_dir, context.allow_fetch)
    cleanup_pyc(checkout_dir)

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

    # Only dump repo_type if it's different from default. This preserves
    # compatibility e.g. with recipes.py bootstrap scripts in client repos
    # which may not handle repo_type correctly.
    # TODO(phajdan.jr): programmatically extract the default value.
    if self.backend.repo_type != package_pb2.DepSpec.GIT:
      buf.repo_type = self.backend.repo_type

    return buf

  def updates(self, context, other_revision=None):
    """Returns a list of all updates to the branch since the revision this
    repo spec refers to.
    """
    raw_updates = self.raw_updates(
        context, (other_revision or self.backend.branch_spec(self.branch)))
    updates = []
    for rev in raw_updates:
      # TODO(somebody): 'info' is not used.
      info = self._get_commit_info(rev, context)
      updates.append(GitRepoSpec(
          self.project_id,
          self.repo,
          self.branch,
          rev,
          self.path,
          self.backend))
    return updates

  def commit_infos(self, context, other_revision):
    """Returns a list of commit infos on the branch between the pinned revision
    and |other_revision|.
    """
    raw_updates = self.raw_updates(context, other_revision)
    return [self._get_commit_info(rev, context) for rev in raw_updates]

  def raw_updates(self, context, other_revision):
    """Returns a list of revisions on the branch between the pinned revision
    and |other_revision|.
    """
    checkout_dir = self._dep_dir(context)

    paths = []
    subdir = self.proto_file(context).read().recipes_path
    if subdir:
      # We add proto_file to the list of paths to check because it might contain
      # other upstream rolls, which we want.
      paths.extend([subdir + os.path.sep, self.proto_file(context).path])

    return self.backend.updates(
        self.repo, self.revision, checkout_dir, context.allow_fetch,
        other_revision, paths)

  def get_more_recent_revision(self, context, r1, r2):
    """Returns the more recent revision."""
    self.checkout(context)
    if context.allow_fetch:
      self.run_git(context, 'fetch')
    args = [
        'rev-list',
        '%s...%s' % (r1, r2),  # Note three dots (...) here.
    ]
    return self.run_git(context, *args).strip().split('\n')[0]

  def _get_commit_info(self, rev, context):
    checkout_dir = self._dep_dir(context)
    metadata = self.backend.commit_metadata(
        self.repo, rev, checkout_dir, context.allow_fetch)
    return CommitInfo(metadata['author'], metadata['message'], self.project_id,
                      rev)

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

  def __init__(self, project_id, path):
    self.project_id = project_id
    self.path = path

  def __str__(self):
    return (
      'PathRepoSpec{project_id="%(project_id)s", path="%(path)s"}'
      % self.__dict__
    )

  def checkout(self, context):
    pass

  def repo_root(self, _context):
    return self.path

  def proto_file(self, context):
    """Returns the ProtoFile of the recipes config file in this repository.
    Requires a good checkout."""
    return ProtoFile(InfraRepoConfig().to_recipes_cfg(self.path))

  def updates(self, _context, _other_revision=None):
    """Returns (empty) list of potential updates for this spec."""
    return []

  def dump(self):
    """Returns the package.proto DepSpec form of this RepoSpec."""
    return package_pb2.DepSpec(
        project_id=self.project_id,
        url="file://"+self.path)

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
  def __init__(self, name, repo_spec, deps, repo_root, relative_recipes_dir,
               canonical_base_url):
    self.name = name
    self.repo_spec = repo_spec
    self.deps = deps
    self.repo_root = repo_root
    self.relative_recipes_dir = relative_recipes_dir
    self.canonical_base_url = canonical_base_url

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
    return 'Package(%r, %r, %r, %r, %r)' % (
        self.name, self.repo_spec, self.deps, self.recipe_dir,
        self.canonical_base_url)

  def __str__(self):
    return 'Package %s, with dependencies %s' % (self.name, self.deps.keys())


class RollCandidate(object):
  """RollCandidate represents a recipe roll candidate, i.e. updates
  to pinned revisions of recipe dependencies.

  This is mostly used by recipes.py autoroll command.
  """

  def __init__(self, package_spec, context, update):
    self._package_spec = package_spec
    self._context = context
    self._updates = {
      update.project_id: update,
    }

  def __eq__(self, other):
    if not isinstance(other, type(self)):
      return False
    return self.__dict__ == other.__dict__

  def get_affected_projects(self):
    return self._updates.keys()

  def make_consistent(self, root_spec):
    """Attempts to make the after-roll dependency graph consistent by rolling
    other package dependencies (changing their revisions). A consistent
    dependency graph means that all of the repos in the graph are pinned
    at the same revision.

    Returns True on success.
    """
    while True:
      try:
        package_deps = PackageDeps(self._context)
        package_deps._create_from_spec(root_spec, self.get_rolled_spec())
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
        more_recent_revision = other_spec.get_more_recent_revision(
            self._context, current_revision, other_spec.revision)
        if more_recent_revision != other_spec.revision:
          return False

        self._updates[other_spec.project_id] = other_spec

  def get_rolled_spec(self):
    """Returns a PackageSpec with all the deps updates from this roll."""
    # TODO(phajdan.jr): does this preserve comments? should it?
    new_deps = _updated(
        self._package_spec.deps,
        { project_id: spec for project_id, spec in
          self._updates.iteritems() })
    return PackageSpec(
        self._package_spec.project_id,
        self._package_spec.recipes_path,
        new_deps,
        self._package_spec.canonical_base_url)

  def get_commit_infos(self):
    """Returns a mapping project_id -> list of commits from that repo
    that are getting pulled by this roll.
    """
    commit_infos = {}

    for project_id, update in self._updates.iteritems():
      commit_infos[project_id] = self._package_spec.deps[
          project_id].commit_infos(self._context, update.revision)

    return commit_infos

  def to_dict(self):
    return {
        'spec': str(self.get_rolled_spec().dump()),
        'commit_infos': self.get_commit_infos(),
    }

  def get_diff(self):
    """Returns a unified diff between original package spec and one after roll.
    """
    orig = str(self._package_spec.dump()).splitlines()
    new = str(self.get_rolled_spec().dump()).splitlines()
    return '\n'.join(difflib.unified_diff(orig, new, lineterm=''))


class PackageSpec(object):
  API_VERSION = 1

  def __init__(self, project_id, recipes_path, deps, canonical_base_url):
    self._project_id = project_id
    self._recipes_path = recipes_path
    self._deps = deps
    self._canonical_base_url = canonical_base_url

  @classmethod
  def load_proto(cls, proto_file):
    buf = proto_file.read()
    assert buf.api_version == cls.API_VERSION

    deps = { str(dep.project_id): cls.spec_for_dep(dep)
             for dep in buf.deps }
    return cls(str(buf.project_id), str(buf.recipes_path), deps,
               buf.canonical_base_url)

  @classmethod
  def spec_for_dep(cls, dep):
    """Returns a RepoSpec for the given dependency protobuf."""
    url = str(dep.url)
    if url.startswith("file://"):
      return PathRepoSpec(str(dep.project_id), url[len("file://"):])

    if dep.repo_type in (package_pb2.DepSpec.GIT, package_pb2.DepSpec.GITILES):
      if dep.repo_type == package_pb2.DepSpec.GIT:
        backend = fetch.GitBackend()
      elif dep.repo_type == package_pb2.DepSpec.GITILES:
        backend = fetch.GitilesBackend()
      return GitRepoSpec(str(dep.project_id),
                         url,
                         str(dep.branch),
                         str(dep.revision),
                         str(dep.path_override),
                         backend)

    assert False, 'Unexpected repo type: %s' % dep

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
  def canonical_base_url(self):
    return self._canonical_base_url

  def dump(self):
    return package_pb2.Package(
        api_version=self.API_VERSION,
        project_id=self._project_id,
        recipes_path=self._recipes_path,
        deps=[ self._deps[dep].dump() for dep in sorted(self._deps.keys()) ],
        canonical_base_url=self._canonical_base_url)

  def roll_candidates(self, root_spec, context):
    """Returns list of consistent roll candidates, and rejected roll candidates.

    The first one is sorted by score, descending. The more commits are pulled by
    the roll, the higher score.

    Second list is included to distinguish between a situation where there are
    no roll candidates from one where there are updates but they're not
    consistent.
    """
    candidates = []
    rejected_candidates = []
    for dep in sorted(self._deps.keys()):
      for update in self._deps[dep].updates(context):
        candidate = RollCandidate(self, context, update)
        if not candidate.make_consistent(root_spec):
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
  def __init__(self, context, overrides=None):
    self._context = context
    self._packages = {}
    self._overrides = overrides or {}
    self._root_package = None

  @property
  def root_package(self):
    return self._root_package

  @classmethod
  def create(cls, repo_root, proto_file, deps_path=None, allow_fetch=False,
             overrides=None):
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
    context = PackageContext.from_proto_file(repo_root, proto_file, allow_fetch,
                                             deps_path=deps_path)

    if overrides:
      overrides = {project_id: PathRepoSpec(project_id, path)
                   for project_id, path in overrides.iteritems()}
    package_deps = cls(context, overrides=overrides)

    package_deps._root_package = package_deps._create_package(
        RootRepoSpec(proto_file))

    return package_deps

  def _create_package(self, repo_spec):
    repo_spec.checkout(self._context)
    package_spec = PackageSpec.load_proto(repo_spec.proto_file(self._context))
    return self._create_from_spec(repo_spec, package_spec)

  def _create_from_spec(self, repo_spec, package_spec):
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
      deps[dep] = self._create_package(dep_repo)

    package = Package(
        project_id, repo_spec, deps,
        repo_spec.repo_root(self._context),
        package_spec.recipes_path,
        package_spec.canonical_base_url)

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
