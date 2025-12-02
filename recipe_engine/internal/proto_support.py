# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Contains all logic w.r.t. the recipe engine's support for protobufs."""

from __future__ import annotations

import ast
import errno
import hashlib
import inspect
import os
import posixpath
import re
import shutil
import sys
import tempfile

from typing import Callable

from gevent import subprocess

import attr

import google.protobuf  # pinned in .vpython
import google.protobuf.message
from google.protobuf import descriptor_pb2

from . import recipe_deps
from .attr_util import attr_type
from .exceptions import BadProtoDefinitions

PROTOC_VERSION = google.protobuf.__version__.encode('utf-8')


if sys.platform.startswith('win'):
  _BAT = '.bat'
  def _to_posix(path: str) -> str:
    return path.replace('\\', '/')
else:
  _BAT = ''
  def _to_posix(path: str) -> str:
    return path


@attr.s(frozen=True)
class _ProtoInfo:
  """_ProtoInfo holds information about the proto files found in a recipe repo.
  """
  # Native-slash-delimited path to the source file
  src_abspath: str = attr.ib(validator=attr_type(str))

  # The fwd-slash-delimited path relative to `repo.path` of the proto file.
  relpath: str = attr.ib(validator=attr_type(str))

  # The fwd-slash-delimited path relative to the output PB directory of where
  # this file should go when we compile protos.
  dest_relpath: str = attr.ib(validator=attr_type(str))

  # Set to True iff this is a reserved path
  reserved: bool = attr.ib(validator=attr_type(bool))

  # The git blob hash of this file.
  #
  # We use the git algorithm here in case we ever want to use e.g. the committed
  # git index as a source for these hashes (and it's not really any more
  # expensive to compute).
  blobhash: str = attr.ib(validator=attr_type(str))

  @classmethod
  def create(cls, repo: recipe_deps.RecipeRepo, scan_relpath: str,
             dest_namespace: str, relpath: str) -> _ProtoInfo:
    """Creates a _ProtoInfo.

    This will convert `relpath` into a global relpath for the output PB folder,
    according to the `dest_namespace`.

    NOTE: If `relpath` conflicts with a reserved namespace, then the `reserved`
    attribute on the returned `_ProtoInfo` will be True.

    Args:
      * repo - The recipe repo we found the proto file in
      * scan_relpath - The fwd-slash-delimited base path we were scanning
        in the repo to find the proto file. This is offset from the `repo.path`
        by `repo.simple_cfg.recipes_path`. e.g. 'scripts/slave/recipes/'.
      * dest_namespace - The fwd-slash-delimited path prefix for the
        destination proto. e.g. 'recipes/build/'.
      * relpath - The fwd-slash-delimited relative path from `repo.path`
        to where we found the proto. e.g.
        'scripts/slave/recipes/subdir/something.proto'.

    Returns a fully populated _ProtoInfo.
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

    return cls(src_abspath, relpath, dest_relpath, reserved, blobhash)

  @classmethod
  def _find_inline_properties_proto(cls, path: str) -> str | None:
    with open(path, 'r') as ins:
      for entry in ast.parse(ins.read()).body:
        match entry:
          case (ast.Assign(
              targets=[ast.Name(id='INLINE_PROPERTIES_PROTO')],
              value=ast.Constant(value=str(x))) | ast.AnnAssign(
                  target=ast.Name(id='INLINE_PROPERTIES_PROTO'),
                  value=ast.Constant(value=str(x)))):
            return x

          case (ast.Assign(targets=[ast.Name(id='INLINE_PROPERTIES_PROTO')])
                | ast.AnnAssign(target=ast.Name(id='INLINE_PROPERTIES_PROTO'))
                | ast.AugAssign(target=ast.Name(id='INLINE_PROPERTIES_PROTO'))):
            raise ValueError(f'bad use of INLINE_PROPERTIES_PROTO in {path}')

    return None

  @classmethod
  def inline_create(cls, repo: recipe_deps.RecipeRepo, scan_relpath: str,
                    dest_namespace: str, relpath: str) -> _ProtoInfo:
    """Creates a _ProtoInfo from a Python file containing an inline proto."""

    inline_properties_proto: str | None = None

    assert relpath.endswith('.py')
    path = os.path.join(repo.path, relpath)

    inline_properties_proto = cls._find_inline_properties_proto(path)

    assert inline_properties_proto, (
        f'Expected but could not find proto in {path}')

    subpath = relpath[len(scan_relpath):]

    proto_path = os.path.join(
        repo.recipe_deps.recipe_deps_path,
        'inline_proto',
        repo.name,
        f'{os.path.splitext(subpath)[0]}.proto',
    )
    proto_relpath = os.path.relpath(proto_path, repo.path)

    # Writing to disk so proto errors point to a specific file that users can
    # find. This is needed because line numbers don't exactly match the
    # multi-line str in the Python file.
    os.makedirs(os.path.dirname(proto_path), exist_ok=True)
    with open(proto_path, 'w') as outs:
      print(f'// This file is generated from {path}', file=outs)
      print('syntax = "proto3";', file=outs)

      namespace = dest_namespace.strip('/').split('/')
      for i, part in enumerate(os.path.dirname(relpath).split('/')):
        if i != 0:
          namespace.append(part)
      print(f'package {".".join(namespace)};', file=outs)
      print(inline_properties_proto, file=outs)

    scan_relpath = os.path.join(
        os.path.relpath(repo.recipe_deps.recipe_deps_path, repo.path),
        'inline_proto', repo.name)
    return cls.create(repo, scan_relpath, dest_namespace, proto_relpath)


def _gather_proto_info_from_repo(
    repo: recipe_deps.RecipeRepo,
) -> list[_ProtoInfo]:
  """Gathers all protos from the given repo.

  Args:
    * repo - The repo to gather all protos from.

  Returns List[_ProtoInfo]
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
        path = posixpath.join(base, fname)
        relpath = posixpath.join(relbase, fname)
        relname, suffix = os.path.splitext(relpath)

        if suffix == '.proto':
          ret.append(
              _ProtoInfo.create(repo, scan_relpath, dest_namespace, relpath))
          continue

        if suffix == '.py' and not os.path.isfile(f'{relname}.proto'):
          with open(path, 'r') as ins:
            contents = ins.read()
          if re.search(r'^INLINE_PROPERTIES_PROTO\s*=', contents, re.MULTILINE):
            ret.append(
                _ProtoInfo.inline_create(repo, scan_relpath, dest_namespace,
                                         relpath))
          continue

  return sorted(ret)


# This is the version # of the proto generation algorithm, and is mixed into the
# checksum. If you need to change the compilation algorithm/process in any way,
# you should increment this version number to cause all protos to be regenerated
# downstream.
RECIPE_PB_VERSION = b'6'


def _gather_protos(
    deps: recipe_deps.RecipeDeps,
) -> tuple[str, list[tuple[str, str]]]:
  """Gathers all .proto files from all repos, and calculates their collective
  hash.

  Args:
    * deps - The loaded recipe dependencies.

  Returns Tuple[dgst: str, proto_files: List[Tuple[str, str]]]
    * dgst: The 'overall' checksum for all protos which we ought to to have
      installed (as hex)
    * proto_files: a list of source abspath to dest_relpath for these proto
      files (i.e. copy from source to $tmpdir/dest_relpath when constructing the
      to-be-compiled proto tree).

  Raises BadProtoDefinitions if this finds conflicting or reserved protos.
  """
  all_protos = {}  # Dict[repo_name : str, List[_ProtoInfo]]
  for repo in deps.repos.values():
    proto_info = _gather_proto_info_from_repo(repo)
    if proto_info:
      all_protos[repo.name] = proto_info

  csum = hashlib.sha256(RECIPE_PB_VERSION)
  csum.update(b'\0')
  csum.update(PROTOC_VERSION)
  csum.update(b'\0')
  rel_to_projs: dict[str, list[str]] = {}
  # dups has keys where len(rel_to_projs[dest_relpath]) > 1
  dups: set[str] = set()
  reserved: set[str] = set()
  retval: list[tuple[str, str]] = []
  for repo_name, proto_infos in sorted(all_protos.items()):
    csum.update(repo_name.encode('utf-8'))
    csum.update(b'\0\0')

    for info in proto_infos:
      duplist = rel_to_projs.setdefault(info.dest_relpath, [])
      duplist.append(repo_name)
      if len(duplist) > 1:
        dups.add(info.dest_relpath)
      if info.reserved:
        reserved.add(info.dest_relpath)

      retval.append((info.src_abspath, info.dest_relpath))

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

  return csum.hexdigest(), retval


@attr.s
class _DirMaker:
  """Helper class to make directories on disk, handling errors for directories
  which exist and only making a given directory once."""
  made_dirs: set[str] = attr.ib(factory=set)

  def __call__(self, dirname: str) -> None:
    """Makes a directory.

    Args:
      * dirname - Directory to make (abs or relative).
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


def _check_package(modulebody: str, relpath_base: str) -> str | None:
  """Returns an error as a string if the proto file at `relpath_base` has
  a package line which is inconsistent.

  Args:
    * modulebody - The contents of the _pb2.py file.
    * pkg - The package read from the proto, e.g. "some.package.namespace"
    * relpath_base - The native-slash-delimited relative path to the
      destination `PB` folder of the generated proto file, minus the '.py'
      extension. e.g.  "recipes/recipe_engine/subpath".

  Returns None if there's no error, or a string if there is. The error string
  will start with the destination relative path of the proto, suitable for use
  with _rel_to_abs_replacer.
  """
  parsed = ast.parse(modulebody)
  for assignment in parsed.body:
    if not isinstance(assignment, ast.Assign):
      continue

    assert isinstance(assignment.targets[0], ast.Name)
    if assignment.targets[0].id != 'DESCRIPTOR':
      continue

    # found the file descriptor line
    assert isinstance(assignment.value, ast.Call)
    assert isinstance(assignment.value.args[0], ast.Constant)
    desc = descriptor_pb2.FileDescriptorProto.FromString(
        assignment.value.args[0].value)
    pkg = desc.package
    break
  else:
    return "unable to find DESCRIPTOR in module"

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
    r'^from (?!google\.protobuf|typing)(\S*) import (\S*)_pb2 as (.*)$',
    re.MULTILINE)


def _rewrite_and_rename(root: str, base_proto_path: str) -> str | None:
  """Transforms a vanilla compiled *_pb2.py file into a recipe proto python
  file.

  Rewrites the import lines and renames the rewritten *_pb2.py file to just
  *.py.

  Args:
    * root - Root directory
    * base_proto_path - Path to the *_pb2.py file to rewrite.

  Returns None if this was successful, or returns a string with an error message
  if this failed.
  """
  assert base_proto_path.endswith('_pb2.py'), base_proto_path

  target = base_proto_path[:-len('_pb2.py')]+'.py'
  with open(base_proto_path, 'r', encoding='utf-8') as ifile:
    content = ifile.read()

  # First, process the _pb2.py file.
  #
  # We need to check it's package name and rewrite it's imports.
  expected_package = os.path.relpath(target, root)
  expected_package, _ = os.path.splitext(expected_package)
  err = _check_package(content, expected_package)

  with open(target, 'w', encoding='utf-8') as ofile:
    ofile.write(
        _REWRITE_IMPORT_RE.sub(r'from PB.\1 import \2 as \3', content))
  os.remove(base_proto_path)

  # Next, we process the .pyi file
  base_pyi_path = base_proto_path + 'i'
  pyi_target = base_proto_path[:-len('_pb2.py')]+'.pyi'
  with open(base_pyi_path, 'r', encoding='utf-8') as ifile:
    content = ifile.read()
  with open(pyi_target, 'w', encoding='utf-8') as ofile:
    ofile.write(
        _REWRITE_IMPORT_RE.sub(r'from PB.\1 import \2 as \3', content))
  os.remove(base_pyi_path)

  return err


def _try_rename(src: str, dest: str) -> None:
  """Attempts to os.rename src to dest, swallowing ENOENT errors."""
  try:
    os.rename(src, dest)
  except OSError as exc:
    if exc.errno != errno.ENOENT:
      raise


def _rel_to_abs_replacer(
    proto_files: list[tuple[str, str]],
) -> Callable[[str], str]:
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


def _collect_protos(
    argfile_fd: int,
    proto_files: list[tuple[str, str]],
    dest: str,
) -> None:
  """Copies all proto_files into dest.

  Writes this list of files to `argfile_fd` which will be passed to protoc.

  Args:
    * argfile_fd: An open writable file descriptor for the argfile.
    * proto_files (List[Tuple[src_abspath: str, dest_relpath: str]])
    * dest: Path to the directory where we should collect the .proto
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


def _compile_protos(proto_files: list[tuple[str, str]], proto_tree: str,
                    protoc: str, argfile: str, dest: str) -> None:
  """Runs protoc over the collected protos, renames them and rewrites their
  imports to make them import from `PB`.

  Args:
    * proto_files: Protobuf files.
    * proto_tree: Path to the directory with all the collected .proto
      files.
    * protoc: Path to the protoc binary to use.
    * argfile: Path to a protoc argfile containing a relative path to
      every .proto file in proto_tree on its own line.
    * dest: Path to the destination where the compiled protos should go.
  """
  protoc_proc = subprocess.Popen(
      [protoc, '--python_out', dest, '--pyi_out', dest, '@'+argfile],
      cwd=proto_tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  output, _ = protoc_proc.communicate()
  os.remove(argfile)

  if protoc_proc.returncode != 0:
    replacer = _rel_to_abs_replacer(proto_files)
    print("Error while compiling protobufs. Output:\n", file=sys.stderr)
    sys.stderr.write(replacer(output.decode('utf-8')))
    sys.exit(1)

  rewrite_errors = []
  # Walk over all _pb2.py and pyi files (_rewrite_and_rename will process both
  # based on the _pb2.py path)
  for base, _, fnames in os.walk(dest):
    for name in fnames:
      if not name.endswith('_pb2.py'):
        continue
      pb2_path = os.path.join(base, name)
      err = _rewrite_and_rename(dest, pb2_path)
      if err:
        rewrite_errors.append(err)

  if rewrite_errors:
    print("Error while rewriting generated protos. Output:\n", file=sys.stderr)
    replacer = _rel_to_abs_replacer(proto_files)
    for error in rewrite_errors:
      print(replacer(error), file=sys.stderr)
    sys.exit(1)


def _install_protos(proto_package_path: str, dgst: str,
                    proto_files: list[tuple[str, str]]) -> None:
  """Installs protos to `{proto_package_path}/PB`.

  Args:
    * proto_package_path - The absolute path to the folder where:
      * We should install protoc as '.../protoc/...'
      * We should install the compiled proto files as '.../PB/...'
      * We should use '.../tmp/...' as a tempdir.
    * dgst - The hexadecimal (lowercase) checksum for the protos we're
      about to install.
    * proto_files: Protobuf files.

  Side-effects:
    * Ensures that `{proto_package_path}/PB` exists and is the correct
      version (checksum).
    * Ensures that `{proto_package_path}/protoc` contains the correct
      `protoc` compiler from CIPD.
  """
  cipd_proc = subprocess.Popen([
    'cipd'+_BAT, 'ensure', '-root', os.path.join(proto_package_path, 'protoc'),
    '-ensure-file', '-'], stdin=subprocess.PIPE)
  protoc_version = PROTOC_VERSION.split(b'.', 1)[1]
  cipd_proc.communicate(b'infra/3pp/tools/protoc/${platform} version:3@' +
                        protoc_version)
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
  proto_tree = tempfile.mkdtemp(dir=tmp_base, prefix='proto_')
  pb_temp = tempfile.mkdtemp(dir=tmp_base, prefix='pb.py_')
  argfile_fd, argfile = tempfile.mkstemp(dir=tmp_base)
  _collect_protos(argfile_fd, proto_files, proto_tree)

  protoc = os.path.join(proto_package_path, 'protoc', 'bin', 'protoc')
  _compile_protos(proto_files, proto_tree, protoc, argfile, pb_temp)
  with open(os.path.join(pb_temp, 'csum'), 'w') as csum_f:
    csum_f.write(dgst)

  dest = os.path.join(proto_package_path, 'PB')
  # Check the digest again, in case another engine beat us to the punch.
  # This is still racy, but it makes the window substantially smaller.
  if not _check_digest(proto_package_path, dgst):
    old = tempfile.mkdtemp(dir=tmp_base)
    _try_rename(dest, os.path.join(old, 'PB'))
    _try_rename(pb_temp, dest)


def _check_digest(proto_package: str, dgst: str) -> bool:
  """Checks protos installed in `{proto_package_path}/PB`.

  Args:
    * proto_package_base - The absolute path to the folder where we will
      look for '.../PB/csum
    * dgst - The digest of the proto files which we believe need to be
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


def ensure_compiled(deps: recipe_deps.RecipeDeps,
                    proto_override: str | None) -> str:
  """Ensures protos are compiled.

  Gathers protos from all repos and compiles them into
  `{deps.recipe_deps_path}/_pb3/PB/*`.

  If proto_override is given, the function returns without doing any work.

  See /doc/implementation_details.md for more info.

  Args:
    * deps - The fully-loaded recipes deps.
    * proto_override - Instead of finding/compiling all protos, use
      this absolute path for `{deps.recipe_deps_path}/_pb3`.

  Returns path to the compiled proto package.
  """
  proto_package = proto_override
  if not proto_package:
    proto_package = os.path.join(deps.recipe_deps_path, '_pb3')
    _DirMaker()(proto_package)

    dgst, proto_files = _gather_protos(deps)

    # If the digest already matches, we're done
    if not _check_digest(proto_package, dgst):
      # Otherwise, try to compile
      try:
        _install_protos(proto_package, dgst, proto_files)
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


def append_to_syspath(proto_package: str) -> None:
  """Append proto package to sys.path.

  Raises an AssertionError if another package with the same basename is already
  on sys.path.
  """
  for path in sys.path:
    assert os.path.basename(proto_package) != os.path.basename(path)
  sys.path.append(proto_package)


def is_message_class(obj: object) -> bool:
  """Returns True if |obj| is a subclass of google.protobuf.message.Message."""
  return (inspect.isclass(obj) and
          issubclass(obj, google.protobuf.message.Message))
