# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Contains all logic w.r.t. the recipe engine's support for protobufs."""

import errno
import hashlib
import inspect
import os
import posixpath
import re
import shutil
import sys
import tempfile

from gevent import subprocess

import attr

import google.protobuf  # pinned in .vpython
import google.protobuf.message

from .attr_util import attr_type
from .exceptions import BadProtoDefinitions


PROTOC_VERSION = google.protobuf.__version__.encode('utf-8')


if sys.platform.startswith('win'):
  _BAT = '.bat'
  def _to_posix(path):
    return path.replace('\\', '/')
else:
  _BAT = ''
  def _to_posix(path):
    return path


@attr.s(frozen=True)
class _SrcInfo(object):
  """_SrcInfo holds information about the proto/py files found in a recipe repo.
  """
  # Native-slash-delimited path to the source file
  src_abspath = attr.ib(validator=attr_type(str))

  # The fwd-slash-delimited path relative to `repo.path` of the proto file.
  relpath = attr.ib(validator=attr_type(str))

  # The fwd-slash-delimited path relative to the output PB directory of where
  # this file should go when we compile protos.
  dest_relpath = attr.ib(validator=attr_type(str))

  # Set to True iff this is a reserved path
  reserved = attr.ib(validator=attr_type(bool))

  # The git blob hash of this file.
  #
  # We use the git algorithm here in case we ever want to use e.g. the committed
  # git index as a source for these hashes (and it's not really any more
  # expensive to compute).
  blobhash = attr.ib(validator=attr_type(str))

  # The kind of source file, either "proto" or "py".
  kind = attr.ib(validator=attr_type(str))

  @classmethod
  def create(cls, repo, scan_relpath, dest_namespace, relpath):
    """Creates a _SrcInfo.

    This will convert `relpath` into a global relpath for the output PB folder,
    according to the `dest_namespace`.

    NOTE: If `relpath` conflicts with a reserved namespace, then the `reserved`
    attribute on the returned `_SrcInfo` will be True.

    Args:
      * repo (RecipeRepo) - The recipe repo we found the proto file in
      * scan_relpath (str) - The fwd-slash-delimited base path we were scanning
        in the repo to find the proto file. This is offset from the `repo.path`
        by `repo.simple_cfg.recipes_path`. e.g. 'scripts/slave/recipes/'.
      * dest_namespace (str) - The fwd-slash-delimited path prefix for the
        destination proto. e.g. 'recipes/build/'.
      * relpath (str) - The fwd-slash-delimited relative path from `repo.path`
        to where we found the proto. e.g.
        'scripts/slave/recipes/subdir/something.proto'.

    Returns a fully populated _SrcInfo.
    """
    assert '\\' not in scan_relpath, (
      'scan_relpath must be fwd-slash-delimited: %r' % scan_relpath)
    assert '\\' not in dest_namespace, (
      'dest_namespace must be fwd-slash-delimited: %r' % dest_namespace)
    assert '\\' not in relpath, (
      'relpath must be fwd-slash-delimited: %r' % relpath)

    subpath = relpath[len(scan_relpath):]
    reserved = False
    if not dest_namespace:
      first_tok = subpath.split('/')[0]
      if first_tok == 'recipes' or first_tok.startswith('recipe_'):
        reserved = True
    dest_relpath = dest_namespace + subpath

    src_abspath = os.path.normpath(os.path.join(repo.path, relpath))

    # Compute the file's blobhash
    csum = hashlib.sha1()
    with open(src_abspath, 'rb') as src:
      csum.update(
          b'blob %d\0' % (os.fstat(src.fileno()).st_size,))
      while True:
        data = src.read(4 * 1024)
        if not data:
          break
        csum.update(data)
    blobhash = csum.hexdigest()

    return cls(src_abspath, relpath, dest_relpath, reserved, blobhash,
               'proto' if src_abspath.endswith('.proto') else 'py')


def _gather_src_info_from_repo(repo):
  """Gathers all protos from the given repo.

  Args:
    * repo (RecipeRepo) - The repo to gather all protos from.

  Returns List[_SrcInfo]
  """
  # Tuples of
  #   * fwd-slash path relative to repo.path of where to look for protos.
  #   * fwd-slash namespace prefix of where these protos should go in the global
  #     namespace.
  pre = repo.simple_cfg.recipes_path
  if pre and not pre.endswith('/'):
    pre += '/'
  scan_path = [
    (pre+'recipes/', 'recipes/%s/' % repo.name),
    (pre+'recipe_modules/', 'recipe_modules/%s/' % repo.name),
    (pre+'recipe_proto/', ''),
  ]
  if repo.name == 'recipe_engine':
    scan_path.append((pre+'recipe_engine/', 'recipe_engine/'))

  ret = []
  for scan_relpath, dest_namespace in scan_path:
    for base, dirs, fnames in os.walk(os.path.join(repo.path, scan_relpath)):
      base = str(base)  # base can be unicode

      # Skip all '.expected' directories.
      dirs[:] = [dname for dname in dirs if not dname.endswith('.expected')]

      # fwd-slash relative-to-repo.path version of `base`
      relbase = _to_posix(os.path.relpath(base, repo.path))

      for fname in fnames:
        fname = str(fname)  # fname can be unicode
        if not fname.endswith(('.proto', '.proto.py')):
          continue
        ret.append(_SrcInfo.create(
            repo, scan_relpath, dest_namespace, posixpath.join(relbase, fname)
        ))

  return sorted(ret)


# This is the version # of the proto generation algorithm, and is mixed into the
# checksum. If you need to change the compilation algorithm/process in any way,
# you should increment this version number to cause all protos to be regenerated
# downstream.
RECIPE_PB_VERSION = b'4'


def _gather_sources(deps):
  """Gathers all .proto and .proto.py files from all repos, and calculates their
  collective hash.

  Args:
    * deps (RecipeDeps) - The loaded recipe dependencies.

  Returns Tuple[
    dgst: str,
    proto_files: List[Tuple[str, str]],
    py_files: List[Tuple[str, str]],
  ]
    * dgst: The 'overall' checksum for all protos which we ought to to have
      installed (as hex)
    * proto_files: a list of source abspath to dest_relpath for these proto
      files (i.e. copy from source to $tmpdir/dest_relpath when constructing the
      to-be-compiled proto tree).
    * py_files: a list of source abspath to dest_relpath for these python
      files (i.e. copy from source to $tmpdir/dest_relpath when constructing the
      to-be-compiled proto tree).

  Raises BadProtoDefinitions if this finds conflicting or reserved protos.
  """
  all_srcs = {}  # Dict[repo_name : str, List[_SrcInfo]]
  for repo in deps.repos.values():
    src_info = _gather_src_info_from_repo(repo)
    if src_info:
      all_srcs[repo.name] = src_info

  csum = hashlib.sha256(RECIPE_PB_VERSION)
  csum.update(b'\0')
  csum.update(PROTOC_VERSION)
  csum.update(b'\0')
  rel_to_projs = {}  # type: Dict[dest_relpath: str, List[repo_name: str]]
  # dups has keys where len(rel_to_projs[dest_relpath]) > 1
  dups = set()       # type: Set[key: str]
  reserved = set()   # type: Set[key: str]
  proto_files = []   # type: List[Tuple[src_abspath: str, dest_relpath: str]]
  py_files = []      # type: List[Tuple[src_abspath: str, dest_relpath: str]]
  for repo_name, src_infos in sorted(all_srcs.items()):
    csum.update(repo_name.encode('utf-8'))
    csum.update(b'\0\0')

    for info in src_infos:
      duplist = rel_to_projs.setdefault(info.dest_relpath, [])
      duplist.append(repo_name)
      if len(duplist) > 1:
        dups.add(info.dest_relpath)
      if info.reserved:
        reserved.add(info.dest_relpath)

      if info.kind == 'proto':
        proto_files.append((info.src_abspath, info.dest_relpath))
      else:
        py_files.append((info.src_abspath, info.dest_relpath))

      csum.update(info.relpath.encode('utf-8'))
      csum.update(b'\0')
      csum.update(info.dest_relpath.encode('utf-8'))
      csum.update(b'\0')
      csum.update(info.blobhash.encode('utf-8'))
      csum.update(b'\0')

  if dups or reserved:
    msg = ''

    if dups:
      msg += (
        'Multiple repos have the same .proto file:\n' + '\n'.join(
            '  %r in %s' % (relpath, ', '.join(rel_to_projs[relpath]))
            for relpath in sorted(dups)))

    if reserved:
      if msg:
        msg += '\n'
      msg += (
        'Repos have reserved .proto files:\n' + '\n'.join(
            '  %r in %s' % (relpath, ', '.join(rel_to_projs[relpath]))
            for relpath in sorted(reserved)))

    raise BadProtoDefinitions(msg)

  return csum.hexdigest(), proto_files, py_files


@attr.s
class _DirMaker(object):
  """Helper class to make directories on disk, handling errors for directories
  which exist and only making a given directory once."""
  made_dirs = attr.ib(factory=set)

  def __call__(self, dirname):
    """Makes a directory.

    Args:
      * dirname (str) - Directory to make (abs or relative).
    """
    if dirname in self.made_dirs:
      return
    toks = dirname.split(os.path.sep)
    try:
      os.makedirs(dirname)
    except OSError as ex:
      if ex.errno != errno.EEXIST:
        raise
    curpath = toks[0] + os.path.sep
    for tok in toks[1:]:
      curpath = os.path.join(curpath, tok)
      self.made_dirs.add(curpath)


def _check_package(pkg, relpath_base):
  """Returns an error as a string if the proto file at `relpath_base` has
  a package line which is inconsistent.

  Args:
    * pkg (str) - The package read from the proto, e.g. "some.package.namespace"
    * relpath_base (str) - The native-slash-delimited relative path to the
      destination `PB` folder of the generated proto file, minus the '.py'
      extension. e.g.  "recipes/recipe_engine/subpath".

  Returns None if there's no error, or a string if there is. The error string
  will start with the destination relative path of the proto, suitable for use
  with _rel_to_abs_replacer.
  """
  relpath_toks = relpath_base.split(os.path.sep)
  toplevel_namespace = relpath_toks[0]

  is_reserved_namespace = (
    lambda tok: tok == 'recipes' or tok.startswith('recipe_')
  )
  is_global = not is_reserved_namespace(toplevel_namespace)

  err = None
  pkg_toks = pkg.split('.')
  if is_global:
    if is_reserved_namespace(pkg_toks[0]):
      err = 'uses reserved namespace %r' % pkg_toks[0]
  else:
    # pkg line should match the relpath_base
    if toplevel_namespace == 'recipes':
      # Recipes should match the full relpath_base
      expected = '.'.join(relpath_toks)
      if pkg != expected:
        err = 'expected %r, got %r' % (expected, pkg)
    else:
      # Everything else should match the full relpath minus a token
      expected = '.'.join(relpath_toks[:-1])
      if pkg != expected:
        err = 'expected %r, got %r' % (expected, pkg)

  if err:
    err = '%s: bad package: %s' % (relpath_base + '.proto', err)

  return err


# We find all import lines which aren't importing from the special
# `google.protobuf` namespace, and rewrite them.
_REWRITE_IMPORT_RE = re.compile(
    r'^from (?!google\.protobuf)(\S*) import (\S*)_pb2 as (.*)$')
# We find the `package` line to enforce what package the proto used for
# enforcement purposes.
_PACKAGE_RE = re.compile(r'^\s+package=\'([^\']*)\',$')
def _rewrite_and_rename(root, base_proto_path):
  """Transforms a vanilla compiled *_pb2.py file into a recipe proto python
  file.

  Rewrites the import lines and renames the rewritten *_pb2.py file to just
  *.py.

  Args:
    * root (str) - Root directory
    * base_proto_path (str) - Path to the *_pb2.py file to rewrite.

  Returns None if this was successful, or returns a string with an error message
  if this failed.
  """
  assert base_proto_path.endswith('_pb2.py')

  err = None

  found_first_import = False
  target_base = base_proto_path[:-len('_pb2.py')]
  with open(target_base+'.py', 'wb') as ofile:
    with open(base_proto_path, 'rU') as ifile:
      bypass = False
      for line in ifile:
        if bypass:
          ofile.write(line.encode('utf-8'))
          continue

        pkg_m = _PACKAGE_RE.match(line)
        if pkg_m:
          # found the package line
          err = _check_package(
              pkg_m.group(1), os.path.relpath(target_base, root))

          ofile.write(line.encode('utf-8'))  # write it unchanged
          # This was the last line we were looking for; the rest of the file is
          # a straight copy.
          bypass = True
          continue

        # If it's the first import line, we want to insert a __future__ import
        # line.
        if not found_first_import and line.startswith(('from ', 'import ')):
          found_first_import = True
          ofile.write(b"\nfrom __future__ import absolute_import\n\n")
          ofile.write(line.encode('utf-8'))
          continue

        # Finally, if we're not in bypass mode, we're potentially rewriting
        # import lines.
        ofile.write(
          _REWRITE_IMPORT_RE.sub(
              r'from PB.\1 import \2 as \3\n', line
          ).encode('utf-8'))
  os.remove(base_proto_path)

  return err


def _try_rename(src, dest):
  """Attempts to os.rename src to dest, swallowing ENOENT errors."""
  try:
    os.rename(src, dest)
  except OSError as exc:
    if exc.errno != errno.ENOENT:
      raise


def _rel_to_abs_replacer(proto_files):
  """Returns a function which will replace directories relative to the
  destination `PB` directory (at the beginning of a line) with their original
  source absolute paths.

  This transforms output like:

      recipe_engine/analyze.proto:7:1: ....

  To:

      /path/to/recipe_engine.git/recipe_engine/analyze.proto:7:1: ....
  """
  rel_to_abs = {}
  for src_abspath, dest_relpath in proto_files:
    dest_dirname = os.path.dirname(dest_relpath)
    if dest_dirname not in rel_to_abs:
      src_base = os.path.dirname(src_abspath)
      if not dest_dirname: # a root path; needs a slash on replacement
        src_base += os.path.sep
      rel_to_abs[dest_dirname] = src_base

  # Sort all relative paths by length from longest to shortest
  finder = re.compile('^(%s)' % ('|'.join(
      re.escape(rel) for rel in sorted(rel_to_abs, key=len, reverse=True)),))

  # For every match of some relpath, look up the original source path in
  # rel_to_abs and substitute that.
  return lambda to_replace: finder.sub(
      lambda match: rel_to_abs[match.group(0)], to_replace)


def _collect_protos(argfile_fd, proto_files, dest):
  """Copies all proto_files into dest.

  Writes this list of files to `argfile_fd` which will be passed to protoc.

  Args:
    * argfile_fd (int): An open writable file descriptor for the argfile.
    * proto_files (List[Tuple[src_abspath: str, dest_relpath: str]])
    * dest (str): Path to the directory where we should collect the .proto
    files.

  Side-effects:
    * Each dest_relpath is written to `argfile_fd` on its own line.
    * Closes `argfile_fd`.
  """
  try:
    _makedirs = _DirMaker()
    for src_abspath, dest_relpath in proto_files:
      destpath = os.path.join(dest, dest_relpath)
      _makedirs(os.path.dirname(destpath))
      shutil.copyfile(src_abspath, destpath)
      os.write(argfile_fd, dest_relpath.encode('utf-8'))
      os.write(argfile_fd, b'\n')
  finally:
    os.close(argfile_fd)  # for windows


def _compile_protos(proto_files, proto_tree, protoc, argfile, dest):
  """Runs protoc over the collected protos, renames them and rewrites their
  imports to make them import from `PB`.

  Args:
    * proto_files (List[Tuple[src_abspath: str, dest_relpath: str]])
    * proto_tree (str): Path to the directory with all the collected .proto
      files.
    * protoc (str): Path to the protoc binary to use.
    * argfile (str): Path to a protoc argfile containing a relative path to
      every .proto file in proto_tree on its own line.
    * dest (str): Path to the destination where the compiled protos should go.
  """
  protoc_proc = subprocess.Popen(
      [protoc, '--python_out', dest, '@'+argfile],
      cwd=proto_tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  output, _ = protoc_proc.communicate()
  os.remove(argfile)


  if protoc_proc.returncode != 0:
    replacer = _rel_to_abs_replacer(proto_files)
    print("Error while compiling protobufs. Output:\n", file=sys.stderr)
    sys.stderr.write(replacer(output.decode('utf-8')))
    sys.exit(1)

  rewrite_errors = []
  for base, _, fnames in os.walk(dest):
    for name in fnames:
      err = _rewrite_and_rename(dest, os.path.join(base, name))
      if err:
        rewrite_errors.append(err)
    with open(os.path.join(base, '__init__.py'), 'wb'):
      pass

  if rewrite_errors:
    print("Error while rewriting generated protos. Output:\n", file=sys.stderr)
    replacer = _rel_to_abs_replacer(proto_files)
    for error in rewrite_errors:
      print(replacer(error), file=sys.stderr)
    sys.exit(1)


def _copy_py_files(py_files, dest):
  """Copies .proto.py files to .py files in the destination tree.

  This also replaces "." in the dest_relpath with os.path.sep, to
  correspond with the python package naming rules.

  Args:
    * py_files (List[Tuple[src_abspath: str, dest_relpath: str]]).
      dest_relpath will have the '.proto.py' extension, which this function
      converts.
    * dest (str): Path to the destination where the py files should go.
  """
  for src_abspath, dest_relpath in py_files:
    dirname, filename = os.path.split(dest_relpath)
    shutil.copyfile(src_abspath, os.path.join(
        dest,
        dirname.replace('.', os.path.sep),
        filename[:-len('.proto.py')]+'.py'))


def _install_protos(proto_package_path, dgst, proto_files, py_files):
  """Installs protos to `{proto_package_path}/PB`.

  Args:
    * proto_package_base (str) - The absolute path to the folder where:
      * We should install protoc as '.../protoc/...'
      * We should install the compiled proto files as '.../PB/...'
      * We should use '.../tmp/...' as a tempdir.
    * dgst (str) - The hexadecimal (lowercase) checksum for the protos we're
      about to install.
    * proto_files (List[Tuple[src_abspath: str, dest_relpath: str]])

  Side-effects:
    * Ensures that `{proto_package_path}/PB` exists and is the correct
      version (checksum).
    * Ensures that `{proto_package_path}/protoc` contains the correct
      `protoc` compiler from CIPD.
  """
  cipd_proc = subprocess.Popen([
    'cipd'+_BAT, 'ensure', '-root', os.path.join(proto_package_path, 'protoc'),
    '-ensure-file', '-'], stdin=subprocess.PIPE)
  # We don't have a mac-arm64 protoc package yet; force amd64 for now.
  protoc_platform = b'mac-amd64' if sys.platform == 'darwin' else b'${platform}'
  cipd_proc.communicate((b'infra/3pp/tools/protoc/%s version:2@' %
                         protoc_platform) + PROTOC_VERSION)
  if cipd_proc.returncode != 0:
    raise ValueError(
        'failed to install protoc: retcode %d' % cipd_proc.returncode)

  # This tmp folder is where all the temporary garbage goes. Future recipe
  # engine invocations will attempt to clean this up as long as PB is
  # up-to-date.
  tmp_base = os.path.join(proto_package_path, 'tmp')

  # proto_tree holds a tree of all the collected .proto files, to be passed to
  # `protoc`
  # pb_temp is the destination of all the generated files; it will be renamed to
  # `{proto_package_path}/dest` as the final step of the installation.
  _DirMaker()(tmp_base)
  proto_tree = tempfile.mkdtemp(dir=tmp_base)
  pb_temp = tempfile.mkdtemp(dir=tmp_base)
  argfile_fd, argfile = tempfile.mkstemp(dir=tmp_base)
  _collect_protos(argfile_fd, proto_files, proto_tree)

  protoc = os.path.join(proto_package_path, 'protoc', 'bin', 'protoc')
  _compile_protos(proto_files, proto_tree, protoc, argfile, pb_temp)
  _copy_py_files(py_files, pb_temp)
  with open(os.path.join(pb_temp, 'csum'), 'w') as csum_f:
    csum_f.write(dgst)

  dest = os.path.join(proto_package_path, 'PB')
  # Check the digest again, in case another engine beat us to the punch.
  # This is still racy, but it makes the window substantially smaller.
  if not _check_digest(proto_package_path, dgst):
    old = tempfile.mkdtemp(dir=tmp_base)
    _try_rename(dest, os.path.join(old, 'PB'))
    _try_rename(pb_temp, dest)


def _check_digest(proto_package, dgst):
  """Checks protos installed in `{proto_package_path}/PB`.

  Args:
    * proto_package_base (str) - The absolute path to the folder where we will
      look for '.../PB/csum
    * dgst (str) - The digest of the proto files which we believe need to be
      built.

  Returns True iff csum matches dgst.
  """
  try:
    csum_path = os.path.join(proto_package, 'PB', 'csum')
    with open(csum_path, 'r') as cur_dgst_f:
      return cur_dgst_f.read() == dgst
  except (OSError, IOError) as exc:
    if exc.errno != errno.ENOENT:
      raise


def ensure_compiled(deps, proto_override):
  """Ensures protos are compiled.

  Gathers protos from all repos and compiles them into
  `{deps.recipe_deps_path}/_pb3/recipe_deps/*`.

  If proto_override is given, the function returns without doing any work.

  See /doc/implementation_details.md for more info.

  Args:
    * deps (RecipeDeps) - The fully-loaded recipes deps.
    * proto_override (str|None) - Instead of finding/compiling all protos, use
      this absolute path for `{deps.recipe_deps_path}/_pb3`.

  Returns path to the compiled proto package.
  """
  proto_package = proto_override
  if not proto_package:
    proto_package = os.path.join(deps.recipe_deps_path, '_pb3')
    _DirMaker()(proto_package)

    dgst, proto_files, py_files = _gather_sources(deps)

    # If the digest already matches, we're done
    if not _check_digest(proto_package, dgst):
      # Otherwise, try to compile
      try:
        _install_protos(proto_package, dgst, proto_files, py_files)
      except:  # pylint: disable=bare-except
        # If some other recipe engine compiled at the same time as us, it may
        # have broken our compilation (e.g. if the other engine cleared tmp out
        # from under us). Double-check the digest to see if it's now what we
        # expect, but raise if not.
        if not _check_digest(proto_package, dgst):
          raise

    # Always try to remove .../tmp if it exists
    shutil.rmtree(os.path.join(proto_package, 'tmp'), ignore_errors=True)

    # Try to remove .recipe_deps/_pb, which is obsoleted in favor of the
    # python-version-specific _pb directories.
    # Also remove _pb2 since recipes no longer support python2.
    shutil.rmtree(
        os.path.join(deps.recipe_deps_path, '_pb'), ignore_errors=True)
    shutil.rmtree(
        os.path.join(deps.recipe_deps_path, '_pb2'), ignore_errors=True)
  return proto_package


def append_to_syspath(proto_package):
  """Append proto package to sys.path.

  Raises an AssertionError if another package with the same basename is already
  on sys.path.
  """
  for path in sys.path:
    assert os.path.basename(proto_package) != os.path.basename(path)
  sys.path.append(proto_package)


def is_message_class(obj):
  """Returns True if |obj| is a subclass of google.protobuf.message.Message."""
  return (inspect.isclass(obj) and
          issubclass(obj, google.protobuf.message.Message))
