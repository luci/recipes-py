# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Utilities for testing with real repos (e.g. git)."""


import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
import recipe_engine.env


from recipe_engine import fetch
from recipe_engine import package
from recipe_engine import package_io
from recipe_engine import package_pb2


class CapturableHandler(logging.StreamHandler):
  """Allows unittests to capture log output.

  From: http://stackoverflow.com/a/33271004
  """
  @property
  def stream(self):
    return sys.stdout

  @stream.setter
  def stream(self, value):
    pass


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
    self.maxDiff = None

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
        fetch.GitBackend(
          self._context.project_checkout_dir(repo['name']),
          repo['root'],
          self._context.allow_fetch
        ))

  def get_root_repo_spec(self, repo):
    """Returns RootRepoSpec corresponding to given repo."""
    config_file = os.path.join(repo['root'], 'infra', 'config', 'recipes.cfg')
    return package.RootRepoSpec(config_file)

  def get_package_spec(self, repo):
    """Returns PackageSpec corresponding to given repo."""
    config_file = os.path.join(repo['root'], 'infra', 'config', 'recipes.cfg')
    return package.PackageSpec.from_package_pb(
      self._context, package_io.PackageFile(config_file).read())

  def create_repo(self, name, spec):
    """Creates a real git repo with simple recipes.cfg."""
    repo_dir = os.path.join(self._root_dir, name)
    subprocess.check_output(['git', 'init', repo_dir])
    with in_directory(repo_dir):
      subprocess.check_output(['git', 'remote', 'add', 'origin', repo_dir])
      with open('recipes.py', 'w') as f:
        f.write('\n'.join([
          'import subprocess, sys, os',
          '#### PER-REPO CONFIGURATION (editable) ####',
          'REPO_ROOT = "."',
          'RECIPES_CFG = os.path.join("infra", "config", "recipes.cfg")',
          '#### END PER-REPO CONFIGURATION ####',
          'if sys.argv[1] != "fetch":',
          '  sys.exit(subprocess.call(',
          '      [sys.executable, %r, "--package", %r] + sys.argv[1:]))' % (
            self._recipe_tool,
            os.path.join(repo_dir, 'infra', 'config', 'recipes.cfg')),
        ]))
      with open('some_file', 'w') as f:
        print >> f, 'I\'m a file'
      subprocess.check_output(['git', 'add', 'recipes.py', 'some_file'])
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
      deps = {
        'recipe_engine': package_pb2.DepSpec(url="file://"+ROOT_DIR),
      }
      for d in repo_deps[k]:
        deps[d] = package_pb2.DepSpec(
          url=repos[d]['root'],
          branch='master',
          revision=repos[d]['revision'],
        )

      repos[k] = self.create_repo(k, package_pb2.Package(
          api_version=2,
          project_id=k,
          recipes_path='',
          deps=deps,
      ))
    return repos

  def updated_package_spec_pb(self, repo, dep_name, dep_revision):
    """Returns package spec for given repo, with specified revision
    for given dependency.
    """
    spec = self.get_package_spec(repo).spec_pb
    spec.deps[dep_name].revision = dep_revision
    return spec

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
      package_io.PackageFile(config_file).write(spec_pb)
      subprocess.check_output(['git', 'add', config_file])
      subprocess.check_output(['git', 'commit', '-m', message])
      rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()
      return rev

  def commit_in_repo(self, repo, message='Empty commit',
                     author_name='John Doe',
                     author_email='john.doe@example.com'):
    """Creates a commit in given repo."""
    root = repo['root']

    env = dict(os.environ)
    env['GIT_AUTHOR_NAME'] = author_name
    env['GIT_AUTHOR_EMAIL'] = author_email
    with open(os.path.join(root, 'some_file'), 'a') as f:
      print >> f, message
    subprocess.check_output(
      ['git', '-C', root, 'commit',
       '-a', '-m', message], env=env)
    rev = subprocess.check_output(
      ['git', '-C', root, 'rev-parse', 'HEAD']).strip()
    return {
        'root': repo['root'],
        'revision': rev,
        'spec': repo['spec'],
        'author_name': author_name,
        'author_email': author_email,
        'message_lines': message.splitlines(),
    }

  def train_recipes(self, repo, overrides=None):
    """Trains recipe tests in given repo.

    Arguments:
      repo(dict): one of the repos returned by |repo_setup|
      overrides: iterable((str, str)): optional list of overrides
          first element of the tuple is the module name, and second
          is the overriding path
    """
    if not overrides:
      overrides = []
    with in_directory(repo['root']):
      args = [
          sys.executable, self._recipe_tool,
          '--package', os.path.join(
              repo['root'], 'infra', 'config', 'recipes.cfg'),
      ]
      for repo, path in overrides:
        args.extend(['-O', '%s=%s' % (repo, path)])
      args.extend([
          '--use-bootstrap',
          'test', 'train',
      ])
      try:
        subprocess.check_output(args, stderr=subprocess.STDOUT)
      except subprocess.CalledProcessError as e:
        print >> sys.stdout, e.output
        raise


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

      self.train_recipes(repo)

      subprocess.check_call(
          ['git', 'add', os.path.join(recipes_dir, '%s.py' % name)])
      subprocess.check_call(
          ['git', 'add', os.path.join(recipes_dir, '%s.expected' % name)])
      return self.commit_in_repo(repo, message='recipe update')

  def update_recipe_module(self, repo, name, methods, generate_example=True,
                           disable_strict_coverage=False):
    """Updates or creates a recipe module in given repo.
    Commits the change.

    Arguments:
      repo(dict): one of the repos returned by |repo_setup|
      name(str): name of the module
      methods(iterable((str, iterable(str)))): list of methods
          provided by the module; first element of the tuple
          is method name (also used for the step name); second element
          is argv of the command that method should call as a step
      generate_example(bool or iterable(str)):
          if bool: whether to generate example.py covering the module
          if iterable(str): which methods to cover in generated example.py
      disable_strict_coverage(bool): whether to disable strict coverage
          (http://crbug.com/693058)
    """
    with in_directory(repo['root']):
      module_dir = os.path.join('recipe_modules', name)
      if not os.path.exists(module_dir):
        os.makedirs(module_dir)
      with open(os.path.join(module_dir, '__init__.py'), 'w') as f:
        f.write('DEPS = []')
        if disable_strict_coverage:
          f.write('\nDISABLE_STRICT_COVERAGE = True')
      with open(os.path.join(module_dir, 'api.py'), 'w') as f:
        f.write('\n'.join([
          'from recipe_engine import recipe_api',
          '',
          'class MyApi(recipe_api.RecipeApi):',
          '  step_client = recipe_api.RequireClient(\'step\')',
        ] + [
          '\n'.join([
            '',
            '  def %s(self):' % m_name,
            '    return self.step_client.run_step(%r)' % {
                'name': m_name,
                'cmd': m_cmd,
                'ok_ret': [0],
                'infra_step': False
            },
            '',
          ]) for m_name, m_cmd in methods.iteritems()
        ]))
      if generate_example:
        with open(os.path.join(module_dir, 'example.py'), 'w') as f:
          f.write('\n'.join([
            'DEPS = [%r]' % name,
            '',
            'def RunSteps(api):',
          ] + ['  api.%s.%s()' % (name, m_name)
               for m_name in methods.keys()
               if generate_example is True or m_name in generate_example
          ] + [
            '',
            'def GenTests(api):',
            '  yield api.test("basic")',
          ]))
      elif os.path.exists(os.path.join(module_dir, 'example.py')):
        os.unlink(os.path.join(module_dir, 'example.py'))

      self.train_recipes(repo)

      subprocess.check_call(['git', 'add', module_dir])
      message = ' '.join(
        ['update %r recipe_module: ' % name] +
        ['%s(%s)' % t for t in methods.iteritems()]
      )
      return self.commit_in_repo(repo, message)
