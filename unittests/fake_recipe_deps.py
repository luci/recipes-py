# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides a 'fake' version of the RecipeDeps object.

This is pretty heavyweight and should be used for integration-testing recipe
functionality.

The objects here manipulate full 'recipe repos' on disk (complete with git
repositories and the ability to make commits in them).

Access this via test_env.RecipeEngineUnitTest.FakeRecipeDeps().
"""

import contextlib
import errno
import json
import os
import shutil
import subprocess
import sys
import textwrap

from cStringIO import StringIO

import attr

from google.protobuf import json_format as jsonpb

from PB.recipe_engine.recipes_cfg import RepoSpec
from recipe_engine import __path__ as RECIPE_ENGINE_PATH
from recipe_engine.internal.fetch import GitBackend, CommitMetadata
from recipe_engine.internal.simple_cfg import RECIPES_CFG_LOCATION_REL
from recipe_engine.internal.test.test_util import filesystem_safe


ROOT_DIR = os.path.dirname(RECIPE_ENGINE_PATH[0])
DEVNULL = open(os.devnull, 'w')
REAL_STDERR = sys.stderr  # capture stderr before tests potentially mess with it


def _get_suite(buf, default, indent='  '):
  """This is a helper function to extract a python code suite from a StringIO
  object.

  This will dedent the buffer's content, split it into lines, and then re-indent
  it by the amount indicated.

  Args:
    * buf (StringIO) - The buffer to take the content from.
    * default (str) - The content to use if `buf` is empty.
    * indent (str) - The string to prepend to all de-indented lines.

  Returns the transformed string.
  """
  value = textwrap.dedent(buf.getvalue() or default).strip('\n')
  return '\n'.join(indent + l for l in value.splitlines())


@attr.s
class FakeRecipeRepo(object):
  """Manipulates a recipe repo on disk (as a git repository)."""

  # The FakeRecipeDeps which owns this repo.
  fake_recipe_deps = attr.ib()  # type: FakeRecipeDeps

  # The name of this repo.
  name = attr.ib()  # type: str

  # The absolute path on disk to the root of this repo.
  path = attr.ib()

  # Set to True by write_file when writing files ending with .proto.
  has_protos = attr.ib(default=False)

  # The GitBackend for this FakeRecipeRepo.
  backend = attr.ib(default=attr.Factory(
      lambda self: GitBackend(self.path, None),
      takes_self=True))

  @contextlib.contextmanager
  def edit_recipes_cfg_pb2(self):
    """Context manager for read/modify/write'ing the recipes.cfg file in this
    repo.

    Usage:

        with repo.edit_recipes_cfg_pb2() as pb:
          pb.deps['some_repo'].revision = 'abcdefg'

    Yields a recipes_cfg_pb2.RepoSpec object decoded from the current state of
    the recipes.cfg file. Any modifications done to this object will be recorded
    back to disk.
    """
    spec = self.recipes_cfg_pb2
    yield spec
    cfg_path = os.path.join(self.path, RECIPES_CFG_LOCATION_REL)
    with open(cfg_path, 'wb') as fil:
      fil.write(jsonpb.MessageToJson(spec, preserving_proto_field_name=True))

  @property
  def recipes_cfg_pb2(self):
    """Returns the current recipes_cfg_pb2.RepoSpec decoded from the recipes.cfg
    file in this repo."""
    cfg_path = os.path.join(self.path, RECIPES_CFG_LOCATION_REL)
    with open(cfg_path, 'rb') as fil:
      return jsonpb.Parse(fil.read(), RepoSpec())

  @contextlib.contextmanager
  def write_file(self, path):
    """Context manager for writing a file inside the repo.

    Any missing directories will be automatically created.

    Usage:

      with repo.write_file('relative/path/filename.ext') as fil:
        fil.write('''
          Content is de-indented.
          So you don't have ugly tests.
        ''')

    Args:
      * path (str) - Path relative to the root of the repo of the file to write.

    Yields a StringIO object which you may write to. For convenience, the data
    written to this StringIO object will be `textwrap.dedent`d to allow nice
    inline strings in test files.
    """
    if path.endswith('.proto'):
      self.has_protos = True
    full_path = os.path.join(self.path, path)
    try:
      os.makedirs(os.path.dirname(full_path))
    except OSError as ex:
      if ex.errno != errno.EEXIST:
        raise

    buf = StringIO()
    yield buf
    with open(full_path, 'wb') as fil:
      fil.write(textwrap.dedent(buf.getvalue()))

  def read_file(self, path):
    """Reads a file inside the repo.

    Args:
      * path (str) - Path relative to the root of the repo of the file to read.

    Returns the file contents as a str. If there is an error reading the file
    this will return None.
    """
    full_path = os.path.join(self.path, path)
    try:
      with open(full_path, 'rb') as fil:
        return fil.read()
    except:  # pylint: disable=bare-except
      return None

  def exists(self, path):
    """Checks to see if a path exists in the repo.

    Args:
      * path (str) - Path relative to the root of the repo to check.

    Returns True iff the item exists.
    """
    return os.path.exists(os.path.join(self.path, path))

  def is_dir(self, path):
    """Checks to see if a path is a directory in the repo.

    Args:
      * path (str) - Path relative to the root of the repo to check.

    Returns True iff the item exists and is a directory.
    """
    return os.path.isdir(os.path.join(self.path, path))

  def is_file(self, path):
    """Checks to see if a path is a file in the repo.

    Args:
      * path (str) - Path relative to the root of the repo to check.

    Returns True iff the item exists and is a regular file.
    """
    return os.path.isfile(os.path.join(self.path, path))

  @attr.s(slots=True)
  class WriteableRecipe(object):
    """Yielded from the `write_recipe` method. Used to generate a recipe on
    disk.

    This contains two string buffers which you may write to, RunSteps and
    GenTests. These represent the body of the RunSteps and GenTests functions in
    the recipe, respectively. Both buffers will be dedent'd as described in
    `write_file`. If you do not write to them, the function bodies will be
    generated with default values:

        RunSteps: pass
        GenTests: yield api.test('basic')

    The RunSteps_args attribute is a list of argument names to be used in the
    RunSteps function definition. It defaults to ['api'] and should generally
    only be extended.

    The imports attribute is a list of 'import' lines you want at the top of the
    recipe. These lines should be an entire valid python import line (i.e
    starting with `import` or `from`).

    The DEPS attribute corresponds exactly to the recipe DEPS field, and you may
    put a python list or dict here, depending on how you want your recipe's DEPS
    to look. The DEPS comes, by default, as a list containing the
    'recipe_engine/step' module. This list may be appended to, or replaced
    entirely (with assignment), if you choose.

    The PROPERTIES attribute is a Python expression to assign to the recipe
    PROPERTIES field.

    The `expectation` dictionary can be populated with expectation JSON data to
    write to disk. The key is the test name (e.g. "basic", "test_on_luci", etc.)
    and the value is list of dicts (i.e. the expectation format). It defaults to
    a single expectation for the test "basic" which has an empty (`None`)
    final result (i.e. the RunSteps function returned None without running
    steps).
    """
    base_path = attr.ib()

    imports = attr.ib(factory=list)
    RunSteps = attr.ib(factory=StringIO)
    RunSteps_args = attr.ib(factory=lambda: ['api'])
    GenTests = attr.ib(factory=StringIO)
    DEPS = attr.ib(factory=lambda: ['recipe_engine/step'])
    PROPERTIES = attr.ib(default='{}')
    ENV_PROPERTIES = attr.ib(default='None')
    expectation = attr.ib(factory=lambda: {
      'basic': [{'name': '$result'}],
    })

    @property
    def path(self):
      """Returns the repo-relative path to the recipe file."""
      return self.base_path + '.py'

    @property
    def expect_path(self):
      """Returns the repo-relative path to the recipe's expectation dir."""
      return self.base_path + '.expected'

  @contextlib.contextmanager
  def write_recipe(self, name_or_module, name=None):
    """Context manager for writing a recipe to the disk in this testing repo.

    Overwrites any existing recipe. This can be called like:

        write_recipe('recipe_name')
        write_recipe('module_name', 'recipe_name')

    If you need to write a malformed recipe, or one with additional top-level
    functions, please use `write_file` to directly write the entire recipe file.

    Usage:

        with repo.write_recipe('my_recipe') as recipe:
          recipe.DEPS.append('my_module')
          recipe.RunSteps.write('''
            api.step('stepname', ['echo', 'something'])
            api.my_module.cool_function()
          ''')

    Args:
      * name_or_module (str) - If the only argument, this is the name of the
        recipe to write. If provided in tandem with `name`, then this is the
        module to write the recipe under.
      * name (str|None) - If provided, this is the name of the recipe, and
        `name_or_module` is the name of the recipe module.

    Yields a WriteableRecipe object. You may manipulate the DEPS, GenTests and
    RunSteps members to craft the recipe you want for your test. See
    WriteableRecipe for details.
    """
    if name:
      base_path = os.path.join('recipe_modules', name_or_module, name)
    else:
      base_path = os.path.join('recipes', name_or_module)

    recipe = self.WriteableRecipe(base_path)
    yield recipe

    dump = self.fake_recipe_deps._ambient_toplevel_code_dump()

    with self.write_file(base_path + '.py') as buf:
      buf.write(textwrap.dedent('''
        {imports}

        {ambient_toplevel_code}

        DEPS = {DEPS!r}

        PROPERTIES = {PROPERTIES}
        ENV_PROPERTIES = {ENV_PROPERTIES}

        def RunSteps({RunSteps_args}):
        {RunSteps}

        def GenTests(api):
        {GenTests}
      ''').format(
          imports='\n'.join(recipe.imports),
          ambient_toplevel_code=dump,
          DEPS=recipe.DEPS,
          PROPERTIES=recipe.PROPERTIES,
          ENV_PROPERTIES=recipe.ENV_PROPERTIES,
          RunSteps_args=', '.join(recipe.RunSteps_args),
          RunSteps=_get_suite(recipe.RunSteps, 'pass'),
          GenTests=_get_suite(
              recipe.GenTests, "yield api.test('basic')")))

    for test_name, expectation in recipe.expectation.iteritems():
      test_name = filesystem_safe(test_name)
      expect_path = os.path.join(base_path + '.expected', test_name + '.json')
      with self.write_file(expect_path) as buf:
        json.dump(expectation, buf, indent=2, separators=(',', ': '))
    self.recipes_py('doc')

  @attr.s(slots=True)
  class WriteableModule(object):
    """Yielded from the `write_module` method. Used to generate a recipe module
    on disk.

    This contains three string buffers which you may write to, `api`, `test_api`
    and `config`. All buffers will be dedent'd as described in `write_file`.

      * `api` represents the body of the {modname.title}Api class inside of
        `api.py`. If not written to, then the body of this class will be `pass`.
      * `test_api` represents the body of the {modname.title}TestApi class
         inside of `test_api.py`. If not written to, then the body of this class
         will be `pass`.
      * `config` represents the body of `config.py`. If not written to then
        `config.py` will not be written to disk.

    The imports attribute is a list of 'import' lines you want at the top of the
    module files. These lines should be an entire valid python import line (i.e
    starting with `import` or `from`).

    The DEPS attribute corresponds exactly to the recipe module's DEPS field,
    and you may put a python list or dict here, depending on how you want your
    recipe's DEPS to look. The DEPS comes, by default, as a list containing the
    'recipe_engine/step' module. This list may be appended to, or replaced
    entirely (with assignment), if you choose.

    The PROPERTIES attribute is a Python expression to assign to the module's
    PROPERTIES field.

    The DISABLE_STRICT_COVERAGE maps directly to the same-named option in
    `__init__.py`.
    """
    path = attr.ib()  # base path of the module folder

    api = attr.ib(factory=StringIO)
    test_api = attr.ib(factory=StringIO)
    config = attr.ib(factory=StringIO)
    imports = attr.ib(factory=list)
    DEPS = attr.ib(factory=lambda: ['recipe_engine/step'])
    PROPERTIES = attr.ib(default='{}')
    GLOBAL_PROPERTIES = attr.ib(default='None')
    ENV_PROPERTIES = attr.ib(default='None')
    WARNINGS = attr.ib(factory=list)
    DISABLE_STRICT_COVERAGE = attr.ib(default=False)

  @contextlib.contextmanager
  def write_module(self, mod_name):
    """Context manager for writing a recipe module to the disk in this testing
    repo.

    Overwrites any existing recipe module (i.e. the existing module, if any,
    will be removed).

    If you need to write a malformed recipe module, or one with additional
    customizations, please use this method, and then use `write_file` to
    overwrite whichever files need to be adjusted.

    Args:
      * mod_name (str) - The name of the module to write.

    Yields a WriteableModule object. You may manipulate its various fields to
    craft the recipe module you want for your test. See WriteableModule for
    details.
    """
    base = os.path.join('recipe_modules', mod_name)

    mod = self.WriteableModule(base)
    yield mod

    if self.exists(base):
      shutil.rmtree(os.path.join(self.path, base))

    with self.write_file(os.path.join(base, '__init__.py')) as buf:
      buf.write('''
      {imports}

      DEPS = {DEPS!r}

      WARNINGS = {WARNINGS!r}

      DISABLE_STRICT_COVERAGE = {DISABLE_STRICT_COVERAGE!r}

      PROPERTIES = {PROPERTIES}
      GLOBAL_PROPERTIES = {GLOBAL_PROPERTIES}
      ENV_PROPERTIES = {ENV_PROPERTIES}
      '''.format(
          imports='\n'.join(mod.imports),
          DEPS=mod.DEPS,
          WARNINGS = mod.WARNINGS,
          DISABLE_STRICT_COVERAGE=mod.DISABLE_STRICT_COVERAGE,
          PROPERTIES=mod.PROPERTIES,
          GLOBAL_PROPERTIES=mod.GLOBAL_PROPERTIES,
          ENV_PROPERTIES=mod.ENV_PROPERTIES,
      ))

    dump = self.fake_recipe_deps._ambient_toplevel_code_dump()

    with self.write_file(os.path.join(base, 'api.py')) as buf:
      buf.write(textwrap.dedent('''
        from recipe_engine.recipe_api import RecipeApi

        {imports}

        {ambient_toplevel_code}

        class {mod_name}Api(RecipeApi):
        {api}
      ''').format(
          imports='\n'.join(mod.imports),
          ambient_toplevel_code=dump,
          mod_name=mod_name.title().replace(' ', ''),
          api=_get_suite(mod.api, 'pass')))

    with self.write_file(os.path.join(base, 'test_api.py')) as buf:
      buf.write(textwrap.dedent('''
        from recipe_engine.recipe_test_api import RecipeTestApi

        {imports}

        {ambient_toplevel_code}

        class {mod_name}Api(RecipeTestApi):
        {test_api}
      ''').format(
          imports='\n'.join(mod.imports),
          ambient_toplevel_code=dump,
          mod_name=mod_name.title().replace(' ', ''),
          test_api=_get_suite(mod.test_api, 'pass')))

    config_body = _get_suite(mod.config, '', indent='')
    if config_body:
      with self.write_file(os.path.join(base, 'config.py')) as buf:
        buf.write(textwrap.dedent('''
          from recipe_engine.config import ConfigGroup, ConfigList, Dict, List
          from recipe_engine.config import Set, Single, config_item_context

          {imports}

          {config_body}
        ''').format(
            imports='\n'.join(mod.imports),
            config_body=config_body,
        ))

  def add_dep(self, *depnames):
    """Adds new repo-level dependencies to this repo.

    The recipes_cfg_pb2 file will be updated to contain all the new entries;
    they'll point to the current HEAD version of the repos.

    Args:
      * depnames (List[str]) - The names of the other repos to depend on. These
        must already have been created with `RecipeDeps.add_repo`.
    """
    with self.edit_recipes_cfg_pb2() as pkg_pb:
      for depname in depnames:
        dep_repo = self.fake_recipe_deps.repos[depname]
        dep_entry = pkg_pb.deps[depname]
        dep_entry.url = 'file://' + dep_repo.path
        dep_entry.branch = 'refs/heads/master'
        dep_entry.revision = dep_repo.backend.commit_metadata('HEAD').revision

  def recipes_py(self, *args, **kwargs):
    """Runs `recipes.py` in this repo with the given args, just like a user
    might run it.

    Args:
      * args (List[str]) - the arguments to pass to recipes.py.

    Kwargs:
      * env (Dict[str, str]) - Extra environment variables to set while invoking
        recipes.py.

    Returns (output, retcode) where 'output' is the combined stdout/stderr from
    the command and retcode it's return code.
    """
    env = os.environ.copy()
    env.update(kwargs.pop('env', {}))
    if not any(r.has_protos for r in self.fake_recipe_deps.repos.itervalues()):
      pb_pkg_path = os.path.join(ROOT_DIR, '.recipe_deps', '_pb')
      args = ('--proto-override', pb_pkg_path) + args
    proc = subprocess.Popen(
        ('python', 'recipes.py')+args,
        cwd=self.path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    output, _ = proc.communicate()
    return output, proc.returncode

  class TestCommitMetadata(CommitMetadata):
    """Commit metadata for a git commit.

    Identical to `fetch.CommitMetadata`, except that it has a helper function
    to make writing autoroller tests less tedious.
    """
    def as_roll_info(self):
      """Returns a dict of author_email, message_lines and revision which
      is JSON serializable.

      In particular, message_lines is a list instead of a tuple.
      """
      return {
        'author_email': self.author_email,
        'message_lines': list(self.message_lines),
        'revision': self.revision,
      }

  def commit(self, msg,
             author_name='Phinley Pfeiffer',
             author_email='ph.pf@example.com'):
    """Adds all files in the repo, then commits it with the given message.

    Returns a TestCommitMetadata object describing the commit we just created.
    """
    # pylint: disable=protected-access
    self.backend._git('add', '.')
    self.backend._git(
      '-c', 'user.name='+author_name,
      '-c', 'user.email='+author_email,
      'commit', '--allow-empty', '-m', msg)

    return self.TestCommitMetadata(
      **self.backend.commit_metadata('HEAD')._asdict())


@attr.s
class FakeRecipeDeps(object):
  """FakeRecipeDeps is a heavyweight testing object which controls a collection
  of git repos on disk.

  Every FakeRecipeDeps has a 'main' repo. This is analogous to the user-facing
  recipe repo that you might run recipes from (i.e. it has deps on 'upstream'
  repos, including, but not limited to, the recipe engine repo).

  When you create a new FakeRecipeDeps, it auto-creates this main repo with
  a dependency on the recipe_engine (the repo you're reading this from).

  You can add additional repos with the add_repo method, and create dependencies
  between repos with the 'FakeRecipeRepo.add_dep' method.
  """

  # _root will contain:
  #   * sources/ - All non-main repos are created here, with their name
  #     as a subfolder.
  #   * main/ - The main repo is created here
  #   * main/.recipe_deps - The .recipe_deps folder of the main repo.
  _root = attr.ib()

  # A map of repo_name -> FakeRecipeRepo
  repos = attr.ib(factory=dict)

  # A list of textwrap.deindent-able python snippets which will be injected into
  # every recipe, module api and test_api written with this FakeRecipeDeps.
  #
  # This is useful to add helper methods and imports which are implicitly
  # available everywhere in the test.
  ambient_toplevel_code = attr.ib(factory=list)

  def _ambient_toplevel_code_dump(self):
    return '\n'.join(map(textwrap.dedent, self.ambient_toplevel_code))

  ENGINE_REVISION = None
  @classmethod
  def _get_engine_revision(cls):
    if not cls.ENGINE_REVISION:
      if subprocess.call(['git', 'diff-index', '--quiet', 'HEAD', '--']):
        print >>REAL_STDERR, '*' * 6
        print >>REAL_STDERR, textwrap.dedent('''
        WARNING: Tests may rely on current recipe engine repo, but you have
        un-committed changes. If you see unexpected behavior in the tests please
        try committing your changes to the engine repo first and then running
        the tests again.
        ''').lstrip(),
        print >>REAL_STDERR, '*' * 6
        print >>REAL_STDERR
        REAL_STDERR.flush()

      cls.ENGINE_REVISION = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD']).strip()
    return cls.ENGINE_REVISION

  def _create_repo(self, name, path):
    """Creates a recipe repo with the given name at the given path.

    This generates an `infra/config/recipes.cfg` with a file:// dependency on
    the current recipe engine, repo_name set to $name.

    Returns the commit of the created repo.
    """
    assert isinstance(name, str)
    assert name not in self.repos, (
      'duplicate repo_name: %r' % (name,))
    os.makedirs(path)
    subprocess.check_call(['git', 'init'], cwd=path, stdout=DEVNULL)
    cfg_path = os.path.join(path, RECIPES_CFG_LOCATION_REL)
    os.makedirs(os.path.dirname(cfg_path))
    with open(cfg_path, 'wb') as fil:
      json.dump({
        'api_version': 2,
        'repo_name': name,
        'deps': {
          'recipe_engine': {
            'url': 'file://'+ROOT_DIR,
            'branch': 'HEAD',
            'revision': self._get_engine_revision(),
          },
        },
      }, fil)
    readme_path = os.path.join(path, 'README.recipes.md')
    readme_str = ('<!--- AUTOGENERATED BY `./recipes.py test train` -->\n'
                 '# Repo documentation for [main]()\n## Table of Contents')
    with open(readme_path, 'wb') as f:
      f.write(readme_str)
    shutil.copy(os.path.join(ROOT_DIR, 'recipes.py'), path)
    subprocess.check_call(['git', 'add', '.'], cwd=path, stdout=DEVNULL)
    subprocess.check_call(['git', 'commit', '-m', 'init '+name], cwd=path,
                          stdout=DEVNULL)
    self.repos[name] = FakeRecipeRepo(self, name, path)
    return subprocess.check_output(
      ['git', 'rev-parse', 'HEAD'], cwd=path).strip()

  def __attrs_post_init__(self):
    """Makes a new RecipeDeps temp folder on disk with a single (main) repo
    called 'main' which has no dependencies."""
    self._create_repo('main', os.path.join(self._root, 'main'))

  @property
  def recipe_deps_path(self):
    """Returns the absolute path to the `.recipe_deps` folder of the main repo.
    """
    return os.path.join(self.main_repo.path, '.recipe_deps')

  def add_repo(self, name):
    """Adds a new repo to the RecipeDeps.

    This is created in `{FakeRecipeDeps.recipe_deps_path}/{name}`.

    This adds a dependency of the main repo onto this new repo, AND COMMITS THE
    CHANGE TO recipes.cfg.

    Returns created FakeRecipeRepo.
    """
    assert isinstance(name, str)
    self._create_repo(name, os.path.join(self._root, 'sources', name))

    self.main_repo.add_dep(name)
    self.main_repo.commit('add dep on ' + name)
    return self.repos[name]

  @property
  def main_repo(self):
    """Returns the main FakeRecipeRepo for this FakeRecipeDeps."""
    return self.repos['main']
