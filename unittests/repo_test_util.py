# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Utilities for testing with real repos (e.g. git)."""


import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'recipe_engine', 'third_party'))
sys.path.insert(0, ROOT_DIR)


from recipe_engine import fetch
from recipe_engine import package
from recipe_engine import package_pb2


@contextlib.contextmanager
def in_directory(target_dir):
  """Context manager that restores original working directory on exit."""
  old_dir = os.getcwd()
  os.chdir(target_dir)
  try:
    yield
  finally:
    os.chdir(old_dir)


@contextlib.contextmanager
def temporary_file():
  """Context manager that returns a path of temporary file."""
  fd, path = tempfile.mkstemp()
  os.close(fd)
  try:
    yield path
  finally:
    os.remove(path)


class RepoTest(unittest.TestCase):
  def setUp(self):
    self._root_dir = tempfile.mkdtemp()
    self._recipe_tool = os.path.join(ROOT_DIR, 'recipes.py')

    self._context = package.PackageContext(
      recipes_dir='foo',
      package_dir=self._root_dir,
      repo_root='bar',
      allow_fetch=False
    )

  def tearDown(self):
    shutil.rmtree(self._root_dir)

  def get_git_repo_spec(self, repo):
    """Returns GitRepoSpec corresponding to given repo."""
    return package.GitRepoSpec(
        repo['name'],
        repo['root'],
        'master',
        repo['revision'],
        '',
        fetch.GitBackend())

  def get_root_repo_spec(self, repo):
    """Returns RootRepoSpec corresponding to given repo."""
    config_file = os.path.join(repo['root'], 'infra', 'config', 'recipes.cfg')
    return package.RootRepoSpec(config_file)

  def get_package_spec(self, repo):
    """Returns PackageSpec corresponding to given repo."""
    config_file = os.path.join(repo['root'], 'infra', 'config', 'recipes.cfg')
    return package.PackageSpec.load_proto(package.ProtoFile(config_file))

  def create_repo(self, name, spec):
    """Creates a real git repo with simple recipes.cfg."""
    repo_dir = os.path.join(self._root_dir, name)
    os.mkdir(repo_dir)
    with in_directory(repo_dir):
      subprocess.check_output(['git', 'init'])
      subprocess.check_output(['git', 'remote', 'add', 'origin', repo_dir])
      with open('recipes.py', 'w') as f:
        f.write('import subprocess, sys\n'
                'sys.exit(subprocess.call(\n'
                '    [sys.executable, %r, "--package", %r] + sys.argv[1:]))' % (
                    self._recipe_tool,
                    os.path.join(repo_dir, 'infra', 'config', 'recipes.cfg')))
      subprocess.check_output(['git', 'add', 'recipes.py'])
    rev = self.update_recipes_cfg(name, spec)
    return {
        'name': name,
        'root': repo_dir,
        'revision': rev,
        'spec': spec,
    }

  def repo_setup(self, repo_deps):
    """Creates a set of repos with recipes.cfg reflecting requested
    dependencies.

    In order to avoid a topsort, we require that repo names are in
    alphebetical dependency order -- i.e. later names depend on earlier
    ones.
    """
    repos = {}
    for k in sorted(repo_deps):
      repos[k] = self.create_repo(k, package_pb2.Package(
          api_version=1,
          project_id=k,
          recipes_path='',
          deps=[
              package_pb2.DepSpec(
                  project_id=d,
                  url=repos[d]['root'],
                  branch='master',
                  revision=repos[d]['revision'],
              )
              for d in repo_deps[k]
          ],
      ))
    return repos

  def updated_package_spec_pb(self, repo, dep_name, dep_revision):
    """Returns package spec for given repo, with specified revision
    for given dependency.
    """
    spec = self.get_package_spec(repo)
    spec.deps[dep_name].revision = dep_revision
    return spec.dump()

  def update_recipes_cfg(self, name, spec_pb, message='recipes.cfg update'):
    """Creates a commit setting recipes.cfg to have provided protobuf
    contents.
    """
    repo_dir = os.path.join(self._root_dir, name)
    with in_directory(repo_dir):
      config_file = os.path.join('infra', 'config', 'recipes.cfg')
      # This supports both updating existing recipes.cfg, as well as adding
      # new one in an empty git repo.
      config_dir = os.path.dirname(config_file)
      if not os.path.exists(config_dir):
        os.makedirs(config_dir)
      package.ProtoFile(config_file).write(spec_pb)
      subprocess.check_output(['git', 'add', config_file])
      subprocess.check_output(['git', 'commit', '-m', message])
      rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()
      subprocess.check_call(['git', 'branch', '-f', 'origin/master', rev])
      return rev

  def commit_in_repo(self, repo, message='Empty commit',
                     author_name='John Doe',
                     author_email='john.doe@example.com'):
    """Creates a commit in given repo."""
    with in_directory(repo['root']):
      env = dict(os.environ)
      env['GIT_AUTHOR_NAME'] = author_name
      env['GIT_AUTHOR_EMAIL'] = author_email
      subprocess.check_output(
          ['git', 'commit', '-a', '--allow-empty', '-m', message], env=env)
      rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()
      subprocess.check_call(['git', 'branch', '-f', 'origin/master', rev])
    return {
        'root': repo['root'],
        'revision': rev,
        'spec': repo['spec'],
        'author_name': author_name,
        'author_email': author_email,
        'message': message,
    }

  def update_recipe(self, repo, name, deps, calls):
    """Updates or creates a recipe in given repo.
    Commits the change.

    Arguments:
      repo(dict): one of the repos returned by |repo_setup|
      name(str): name of the recipe (without .py)
      deps(iterable(str)): list of recipe dependencies (DEPS)
      calls(iterable((str, str))): list of calls to recipe module
          methods to make in the recipe; first element of the tuple
          is the module name, and second is the method name

    """
    with in_directory(repo['root']):
      recipes_dir = 'recipes'
      if not os.path.exists(recipes_dir):
        os.makedirs(recipes_dir)
      with open(os.path.join(recipes_dir, '%s.py' % name), 'w') as f:
        f.write('\n'.join([
          'DEPS = %r' % deps,
          '',
          'def RunSteps(api):',
        ] + ['  api.%s.%s()' % c for c in calls] + [
          '',
          'def GenTests(api):',
          '  yield api.test("basic")',
        ]))

      subprocess.check_output([
          sys.executable, self._recipe_tool,
          '--package', os.path.join(
              repo['root'], 'infra', 'config', 'recipes.cfg'),
          'simulation_test',
          'train',
      ])

      subprocess.check_call(
          ['git', 'add', os.path.join(recipes_dir, '%s.py' % name)])
      subprocess.check_call(
          ['git', 'add', os.path.join(recipes_dir, '%s.expected' % name)])
      return self.commit_in_repo(repo, message='recipe update')

  def update_recipe_module(self, repo, name, methods):
    """Updates or creates a recipe module in given repo.
    Commits the change.

    Arguments:
      repo(dict): one of the repos returned by |repo_setup|
      name(str): name of the module
      methods(iterable((str, iterable(str)))): list of methods
          provided by the module; first element of the tuple
          is method name (also used for the step name); second element
          is argv of the command that method should call as a step
    """
    with in_directory(repo['root']):
      module_dir = os.path.join('recipe_modules', name)
      if not os.path.exists(module_dir):
        os.makedirs(module_dir)
      with open(os.path.join(module_dir, '__init__.py'), 'w') as f:
        f.write('DEPS = []')
      with open(os.path.join(module_dir, 'api.py'), 'w') as f:
        f.write('\n'.join([
          'from recipe_engine import recipe_api',
          '',
          'class MyApi(recipe_api.RecipeApi):',
        ] + [
          '\n'.join([
            '',
            '  def %s(self):' % m_name,
            '    return self._engine.run_step(%r)' % {
                'name': m_name,
                'cmd': m_cmd,
                'ok_ret': [0],
                'infra_step': False
            },
            '',
          ]) for m_name, m_cmd in methods.iteritems()
        ]))

      subprocess.check_output([
          sys.executable, self._recipe_tool,
          '--package', os.path.join(
              repo['root'], 'infra', 'config', 'recipes.cfg'),
          'simulation_test',
          'train',
      ])

      subprocess.check_call(['git', 'add', module_dir])
      message = ' '.join(
        ['update %r recipe_module: ' % name] +
        ['%s(%s)' % t for t in methods.iteritems()]
      )
      return self.commit_in_repo(repo, message)

  def reset_repo(self, repo, revision):
    """Resets repo contents to given revision."""
    with in_directory(repo['root']):
      subprocess.check_output(['git', 'reset', '--hard', revision])
