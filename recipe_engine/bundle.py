#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Bundles a universe_view into a standalone folder.

This captures the result of doing all the network operations that recipe_engine
might do at startup to fetch repo code.

THIS IS A HACK. However, the API is solid. The general principle is that the
input to bundle is:
  * a universe
  * a package manifest
  * repo's bundle_extra_paths.txt in their module folders
And the output is:
  * a runnable folder for the named package

The particular implementation here is hacky and is DESIGNED TO BE REPLACED, once
we have a proof of concept of this working on swarming.

Some things that we'd want to do to make this better:
  * Allow this to fetch lazily from gitiles (no git clones)
    * will be necessary to support HUGE repos like chromium/src
  * Allow this to target a specific subset of runnable recipes
    * prune down to ONLY the modules which are required to run those particular
      recipes.
  * Add debugging command to print aggregate bundle_extra_paths content while
    doing this so that we can whittle away these extra dependencies.
  * Support symlinks
"""

from __future__ import absolute_import
import errno
import fnmatch
import functools
import io
import itertools
import logging
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys

from multiprocessing.pool import ThreadPool
from collections import namedtuple, defaultdict

from . import loader
from . import package

LOGGER = logging.getLogger(__name__)


def check(obj, typ):
  if not isinstance(obj, typ):
    msg = '%r was %s, expected %s' % (obj, type(obj).__name__, typ.__name__)
    LOGGER.debug(msg)
    raise TypeError(msg)


# Since windows doesn't support the executable bit, we warn when bundling files
# that git knows are +x. On POSIX-ey platforms this falls through to os.fchmod.
if sys.platform.startswith('win'):
  def set_executable(f):
    check(f, file)
    LOGGER.warn("data loss! unable to set +x on %s" % (f.name,))
else:
  def set_executable(f):
    check(f, file)
    os.fchmod(f.fileno(), os.fstat(f.fileno()).st_mode|0111)


def prepare_destination(destination):
  check(destination, str)

  destination = os.path.abspath(destination)
  LOGGER.info('prepping destination %s', destination)
  if os.path.exists(destination):
    LOGGER.fatal(
      'directory %s already exists! The directory must not exist to use it as '
      'a bundle target.', destination)
    sys.exit(1)
  os.makedirs(destination)
  return NativePath(destination)


GLOB_CHARS = re.compile(r'[*!?\[\]]')


def _join_impl(base, others):
  base_type = type(base)

  if base.raw_value != '':
    vals = [None] * (len(others)+1)
    vals[0] = base.raw_value
    offset = 1
  else:
    vals = [None] * len(others)
    offset = 0

  for i, o in enumerate(others):
    if isinstance(o, str):
      v = o
    elif isinstance(o, base_type):
      v = o.raw_value
    else:
      raise TypeError('cannot join %s with %s' % (
        base_type.__name__, type(o).__name__))
    vals[i+offset] = v
  return base_type(base.sep.join(vals))


@functools.total_ordering
class PosixPath(object):
  """PosixPaths are utf-8 encoded str's containing paths with POSIX-style
  slashes ('/')."""

  sep = '/'

  def __init__(self, value):
    if '\\' in value:
      raise ValueError('PosixPath cannot contain "\\"')
    self._value = value

  @property
  def raw_value(self):
    return self._value

  def split(self):
    return map(PosixPath, self._value.split(self.sep))

  def join(self, *other):
    return _join_impl(self, other)

  def to_native(self):
    return NativePath(self._value.replace(self.sep, NativePath.sep))

  def rstrip(self):
    return PosixPath(self._value.rstrip(self.sep))

  def basename(self):
    return PosixPath(posixpath.basename(self._value))

  def path_split(self):
    return map(PosixPath, posixpath.split(self._value))

  def __repr__(self):
    return "%s(%r)" % (type(self).__name__, self._value)

  def __eq__(self, other):
    check(other, PosixPath)
    return self.raw_value == other.raw_value

  def __lt__(self, other):
    check(other, PosixPath)
    return self.raw_value < other.raw_value

  def __hash__(self):
    return hash(('PosixPath', self._value))


class NativePath(object):
  """NativePaths are utf-8 encoded str's containing paths with os.path.sep-style
  slashes."""

  sep = os.path.sep
  OTHER_SLASH = '\\' if sep == '/' else '/'

  def __init__(self, value):
    if self.OTHER_SLASH in value:
      raise ValueError('NativePath cannot contain "%s" on this platform', )
    self._value = value

  @property
  def raw_value(self):
    return self._value

  def join(self, *other):
    return _join_impl(self, other)

  def __repr__(self):
    return "%s(%r)" % (type(self).__name__, self._value)


def parse_simple_glob(glob):
  """Parses a glob to ensure it's a simple glob.

  A simple glob is one where the path consists of non-glob tokens, followed by
  a token at the end which may contain glob characters.

  Examples (good):
    * a/b/c*
    * a/b/*something*
    * pattern*

  Examples (bad):
    * a/*/b
    * */b
    * */something*

  Args:
    glob (PosixPath) - The simple glob pattern to parse.

  Raises:
    ValueError - if the provided glob is not a simple glob.

  Returns (tuple[PosixPath, str]) - the constant prefix (e.g. 'a/b') and the
    glob regex string as a tuple.
  """
  check(glob, PosixPath)
  toks = glob.split()
  for tok in toks[:-1]:
    if GLOB_CHARS.search(tok.raw_value):
      raise ValueError('not a simple glob (non-leaf components are patterns)')
  if not GLOB_CHARS.search(toks[-1].raw_value):
    raise ValueError('not a simple glob (leaf component not a pattern)')
  prefix = PosixPath('')
  if len(toks) > 1:
    prefix = toks[0].join(*toks[1:-1])
  return prefix, fnmatch.translate(toks[-1].raw_value)


def repo_files_simple_pattern(repo_root, dirpath, regex):
  """Generates all files in the repo which match 'dirpath/regex'.

  Use parse_simple_glob to obtain dirpath and regex.

  Args:
    repo_root (NativePath) - abspath to the root of the repo
    dirpath (PosixPath) - path relative to repo_root (no . or ..) to the
      directory where regex should be applied.
    regex (regex) - the regex object to match files in dirpath.

  Yields (PosixPath) - paths of files relative to repo_root.
  """
  check(repo_root, NativePath)
  check(dirpath, PosixPath)
  check(regex, re._pattern_type)

  output = subprocess.check_output([
    'git', '-C', repo_root.raw_value,
    'ls-tree', 'HEAD:'+dirpath.raw_value]).splitlines()

  # Each line looks like:
  # 100644 blob df099e1cd4d5d08f88a262033729d80a08f01371	__init__.py
  # mode typ id\tname

  for line in output:
    metadata, filename = line.split('\t', 1)
    _mode, typ, _id = metadata.split(' ')
    if typ == 'blob' and regex.match(filename):
      yield dirpath.join(filename)


def repo_files_recursive(repo_root, relpath):
  """Returns the repo-relative paths for all files in the repo which are
  descendants of relpath."""
  check(repo_root, NativePath)
  check(relpath, PosixPath)

  s = relpath.raw_value
  if not s.endswith('/'):
    s += '/'

  return map(PosixPath, subprocess.check_output([
    'git', '-C', repo_root.raw_value,
    'ls-files', s]).splitlines())


def read_from_repo(repo_root, relpath):
  """Reads the relpath from the repo and returns its content."""
  check(repo_root, NativePath)
  check(relpath, PosixPath)
  return subprocess.check_output([
    'git', '-C', repo_root.raw_value,
    'cat-file', 'blob', 'HEAD:'+relpath.raw_value])


def write_from_repo(repo_root, dest_root, relpath):
  """Writes the data from the repo at relpath to the given file."""
  check(repo_root, NativePath)
  check(dest_root, NativePath)
  check(relpath, PosixPath)

  with open(dest_root.join(relpath.to_native()).raw_value, 'wb') as f:
    subprocess.check_call([
      'git', '-C', repo_root.raw_value,
      'cat-file', 'blob', 'HEAD:'+relpath.raw_value], stdout=f)
    out = subprocess.check_output([
      'git', '-C', repo_root.raw_value,
      'ls-tree', 'HEAD', relpath.raw_value])
    mode, _ = out.split(' ', 1)
    # git only stores 0755 and 0644, so it's safe to check for this pattern
    # explicitly.
    if mode.endswith('0755'):
      set_executable(f)


def parse_bundle_extra(data):
  """Parses bundle_extra_paths.txt data.

  A bundle_extra_paths file can have on each line:
    * a comment:   # this is a comment
    * blank line:
    * a file:      //some/path/to/file.txt
    * a dir:       //some/path/to/dir/
    * a glob:      //some/path/*pattern*

  Note that globs must be simple (see parse_simple_glob). The trailing slash for
  dirs is important. All paths must begin with // and are relative to the repo's
  root. Relative paths (paths containing . or ..) are not allowed.

  Args:
    data (str) - the raw text of the file

  Returns (dirs, globs, files, errors).
    files and dirs are lists of repo-relative PosixPaths (e.g. 'a/b/c'), globs
    is a dict of (relpath, [regex, ...]) (as returned by parse_simple_glob).
    errors is a list of error strings encountered while parsing the file.
  """
  check(data, str)

  errors = []
  files = []
  dirs = []

  # path -> {pattern, pattern, ...}
  globs = defaultdict(set)

  for lineno, line in enumerate(data.splitlines()):
    line = line.strip()
    if len(line) == 0 or line.startswith('#'):
      continue

    if '\\' in line:
      errors.append('line %d: %r contains "\\" (use "/" instead)' %
                    (lineno, line))
      continue

    # We assert all paths start with '//' so that we can capture 'include the
    # entire repo' cases without resorting to '.', or '' which are both
    # confusing. '//' also implies root-of-repo to the casual reader, which is
    # a pretty well-understood concept.
    if not line.startswith('//'):
      errors.append('line %d: %r missing "//"' % (lineno, line))
      continue

    line_path = PosixPath(line[2:])

    if '//' in line_path.raw_value:
      errors.append('line %d: %r has doubled slashes' % (lineno, line))
      continue

    toks = line_path.split()
    if any(t.raw_value == '.' or t.raw_value == '..' for t in toks):
      errors.append('line %d: %r relative path' %  (lineno, line))
      continue

    if GLOB_CHARS.search(line_path.raw_value):
      try:
        path, pattern = parse_simple_glob(line_path)
        globs[path].add(pattern)
      except ValueError as ex:
        errors.append('line %r: %r %s' % (lineno, line, ex))
    elif line_path.raw_value == '':
      # 'include whole repo' is indicated by '//' which shows up as '' here
      dirs.append(line_path.rstrip())
    elif line_path.raw_value.endswith(PosixPath.sep):
      dirs.append(line_path.rstrip())
    else:
      files.append(line_path)

  return dirs, globs, files, errors


def minify_extra_files(dirs, globs, files, already_included_dirs):
  """This takes the sets of files, dirs, and globs parsed from all
  bundle_extra_paths files and minimizes them so that we do the minimum number
  of file operations. For example, if the dir foo is in dirs, we don't need
  the dir foo/bar, the glob foo/something/pattern*, or the file foo/file.

  Args:
    dirs (set[PosixPath]) - the set of recursive dir paths we want
    globs (dict[PosixPath, set[regex]]) - the mapping of path prefix to a set
      of glob regex patterns.
    files (set[PosixPath]) - the set of single file paths we want
    already_included_dirs (set) - the set of directories that the 'bundle'
        command already included, which should be ignored.

  Returns new sets as a tuple (dirs, globs, files). The globs dictionary will
      be modified so that every prefix maps to a single compiled regex, not
      a list of uncompiled regex patterns.
  """
  FULL_REPO = PosixPath('')
  if FULL_REPO in already_included_dirs:
    return {FULL_REPO}, {}, set()

  # first calculate the minimal set of dirs
  new_dirs = set(already_included_dirs)

  def is_already_included(path):
    check_dir = None
    for tok in path.split():
      if check_dir is None:
        check_dir = tok
      else:
        check_dir = check_dir.join(tok)
      if check_dir in new_dirs:
        return True
    return False

  for d in sorted(dirs):
    if FULL_REPO == d:
      return {FULL_REPO}, {}, set()

    check(d, PosixPath)
    if not is_already_included(d):
      new_dirs.add(d)

  new_globs = {}
  for prefix, patterns in globs.iteritems():
    check(prefix, PosixPath)
    if not is_already_included(prefix):
      new_globs[prefix] = re.compile('|'.join('(%s)' % p for p in
                                              sorted(patterns)))

  new_files = set()
  for f in files:
    check(f, PosixPath)
    if not is_already_included(f):
      dirname, filename = f.path_split()
      pat = new_globs.get(dirname)
      if not (pat and pat.match(filename.raw_value)):
        new_files.add(f)

  new_dirs -= already_included_dirs

  return new_dirs, new_globs, new_files


def generate_files(repo_root, relative_recipes_dir, with_recipes):
  """Generates a series of repo-relative paths and file objects within the given
  repo which should be included in the bundle.

  This includes:
    * the recipes folder (if with_recipes is true)
    * the recipe_modules folder
    * any directories included by bundle_extra_paths in the recipe_module
      folders.
    * any simple globs included by bundle_extra_paths in the recipe_module
      folders.
    * any files included by bundle_extra_paths in the recipe_module
      folders.

  This method attempts to prevent scanning duplicates (e.g. if multiple
  bundle_extra_paths files include the same dir, file, etc.).
  """
  check(repo_root, NativePath)
  check(relative_recipes_dir, PosixPath)
  check(with_recipes, bool)

  recipes_path = relative_recipes_dir.join('recipes')
  recipe_module_path = relative_recipes_dir.join('recipe_modules')

  extra_files = set()
  extra_dirs = set()
  extra_globs = defaultdict(set)

  had_errors = False

  def is_expectation(fpath):
    # some/path/something.expected/something.json
    expected_path, _ = fpath.path_split()
    _, expected_dir = expected_path.path_split()
    return expected_dir.raw_value.endswith('.expected')

  def process_bundle_extra(fpath):
    if fpath.basename().raw_value == 'bundle_extra_paths.txt':
      data = read_from_repo(repo_root, fpath)

      dirs, globs, files, errors = parse_bundle_extra(data)
      extra_files.update(files)
      extra_dirs.update(dirs)
      for dirpath, pats in globs.iteritems():
        extra_globs[dirpath].update(pats)
      if errors:
        fullpath = repo_root.join(fpath.to_native())
        LOGGER.error('in %r', fullpath.raw_value)
        for e in errors:
          LOGGER.error('  %s', e)
        return False
    return True

  # grab all files in the recipe_modules folder.
  to_iter = [repo_files_recursive(repo_root, recipe_module_path)]
  dirs_seen = {recipe_module_path}

  # maybe grab all files in the recipes folder.
  if with_recipes:
    to_iter.append(repo_files_recursive(repo_root, recipes_path))
    dirs_seen.add(recipes_path)

  for fpath in itertools.chain(*to_iter):
    if is_expectation(fpath):
      continue
    yield fpath
    if not process_bundle_extra(fpath):
      had_errors = True

  if had_errors:
    LOGGER.error('One or more errors. See log for detail.')
    sys.exit(1)

  extra_dirs, extra_globs, extra_files = minify_extra_files(
    extra_dirs, extra_globs, extra_files, dirs_seen)

  # Now iterate through all extra dirs.
  for d in sorted(extra_dirs):
    for relpath in repo_files_recursive(repo_root, d):
      yield relpath

  # Then all extra globs.
  for dirname, glob in extra_globs.iteritems():
    for relpath in repo_files_simple_pattern(repo_root, dirname, glob):
      yield relpath

  # Finally all extra files
  for relpath in sorted(extra_files):
    yield relpath


def export_package(pkg, destination, with_recipes):
  check(pkg, package.Package)
  check(destination, NativePath)
  check(with_recipes, bool)

  repo_root = NativePath(pkg.repo_root)
  relative_recipes_dir = PosixPath(pkg.relative_recipes_dir)

  if with_recipes:
    LOGGER.info('exporting package: %s(/%s)/{recipes,recipe_modules}',
                repo_root.raw_value, relative_recipes_dir.raw_value)
  else:
    LOGGER.info('exporting package: %s(/%s)/recipe_modules',
                repo_root.raw_value, relative_recipes_dir.raw_value)

  bundle_dst = destination.join(pkg.name)

  madedirs = set()

  # using a ThreadPool speeds this up ~4x.
  tp = ThreadPool()

  # TODO(iannucci): have generate_files also yield a writer function
  # so that gitiles fetches can be done more efficiently by preferring to fetch
  # entire recursive dirs as tarballs, minimizing the number of single-file
  # fetches. Since the generator function knows where all the files came from,
  # it could cache the downloaded gitiles data and return writers which know
  # how to write from the cache into the final location.
  for relpath in generate_files(repo_root, relative_recipes_dir, with_recipes):
    native = relpath.to_native().raw_value

    LOGGER.debug('  writing: %s', native)
    parent = os.path.dirname(native)
    if parent not in madedirs:
      try:
        os.makedirs(bundle_dst.join(parent).raw_value)
      except OSError as err:
        if err.errno != errno.EEXIST:
          raise
      madedirs.add(parent)

    tp.apply_async(write_from_repo, args=(repo_root, bundle_dst, relpath))

  tp.close()
  tp.join()

  cfg_path_dst = package.InfraRepoConfig().to_recipes_cfg(bundle_dst.raw_value)
  if not os.path.exists(cfg_path_dst):
    cfg_path_src = package.InfraRepoConfig().to_recipes_cfg(repo_root.raw_value)
    os.makedirs(os.path.dirname(cfg_path_dst))
    shutil.copyfile(cfg_path_src, cfg_path_dst)


TEMPLATE_SH = u"""#!/usr/bin/env bash
python ${BASH_SOURCE[0]%/*}/recipe_engine/recipes.py --no-fetch \
"""

TEMPLATE_BAT = u"""python "%~dp0\\recipe_engine\\recipes.py" --no-fetch ^
"""

def prep_recipes_py(universe, root_package, destination):
  check(universe, loader.RecipeUniverse)
  check(root_package, package.Package)
  check(destination, NativePath)

  LOGGER.info('prepping recipes.py for %s', root_package.name)
  recipes_script = destination.join('recipes').raw_value
  with io.open(recipes_script, 'w', newline='\n') as recipes_sh:
    recipes_sh.write(TEMPLATE_SH)

    pkg_path = package.InfraRepoConfig().to_recipes_cfg(
      '${BASH_SOURCE[0]%%/*}/%s' % root_package.name)
    recipes_sh.write(u' --package %s \\\n' % pkg_path)
    for pkg in universe.packages:
      recipes_sh.write(u' -O %s=${BASH_SOURCE[0]%%/*}/%s \\\n' %
                       (pkg.name, pkg.name))
    recipes_sh.write(u' "$@"\n')
  os.chmod(recipes_script, os.stat(recipes_script).st_mode | stat.S_IXUSR)

  with io.open(recipes_script+'.bat', 'w', newline='\r\n') as recipes_bat:
    recipes_bat.write(TEMPLATE_BAT)

    pkg_path = package.InfraRepoConfig().to_recipes_cfg(
      '"%%~dp0\\%s"' % root_package.name)
    recipes_bat.write(u' --package %s ^\n' % pkg_path)
    for pkg in universe.packages:
      recipes_bat.write(u' -O %s=%%~dp0/%s ^\n' % (
        pkg.name, pkg.name))
    recipes_bat.write(u' %*\n')


def main(root_package, universe, destination):
  """
  Args:
    root_package (package.Package) - The recipes script in the produced bundle
      will be tuned to run commands using this package.
    universe (loader.RecipeUniverse) - All of the recipes necessary to support
      root_package.
    destination (str) - Path to the bundle output folder. This folder should not
      exist before calling this function.
  """
  check(root_package, package.Package)
  check(universe, loader.RecipeUniverse)
  check(destination, str)

  logging.basicConfig()
  destination = prepare_destination(destination)
  for pkg in universe.packages:
    export_package(pkg, destination, pkg == root_package)
  prep_recipes_py(universe, root_package, destination)
  LOGGER.info('done!')
