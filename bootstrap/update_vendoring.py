#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Regenerates vendored components and derivative files from external sources.

This is a utililty script that is intended to be run on a Linux-based system.
Other operating systems may work, but are not supported.

This script encapsulates all of the logic necessary to regenerate the components
vendored into the Recipe Engine. The list of vendor actions can be seen in the
_ACTIONS list.

This script specifically includes support for checking out, building, running,
packaging, installing, and generating the protobuf library and derivative
protobufs from vendored sources. All such protobufs must be kept in sync with
the vendored protobuf library, else they may not be able to coexist.
"""

import argparse
import collections
import contextlib
import glob
import logging
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile


# The path to the repository root directory.
REPO_DIR = os.path.abspath(os.path.join(
  os.path.dirname(os.path.realpath(__file__)), os.pardir))


# Global logger instance.
LOGGER = logging.getLogger('recipes-py/regenerate')


@contextlib.contextmanager
def _tempdir(leak=False):
  tdir = None
  try:
    tdir = tempfile.mkdtemp(prefix='tmp_recipes_py_gen')
    yield tdir
  finally:
    if tdir:
      if leak:
        LOGGER.warning('Leaking temporary dirctory: %s', tdir)
      else:
        shutil.rmtree(tdir)


def _path(base, v):
  """Constructs a system path from a base path and a universal path segment.

  Args:
    base (str): A valid base system path.
    v (str): A universal ('/' as separator) path segment.

  Returns (str): A valid system path formed by concatenating `base` and `v`.
  """
  if os.sep != '/':
    v = v.replace('/', os.sep)
  return os.path.join(base, v)


class Context(object):
  """Context passed around to all actions. Actions may accumulate data in a
  Context and pass it to subsequent Actions.
  """

  def __init__(self, dest_root):
    self._tools = {}
    self._dest_root = dest_root

  def add_tool(self, name, path):
    if name in self._tools:
      raise KeyError('Duplicate tool: %s', name)
    self._tools[name] = path

  def tool(self, name):
    return self._tools[name]

  def dest(self, relpath):
    return _path(self._dest_root, relpath)

  def check_call(self, args, cwd=None):
    LOGGER.debug('Running command (cwd=%s): %s', cwd, ' '.join(args))
    subprocess.check_call(args, cwd=cwd)

  @staticmethod
  def vendor_dir(src, dest):
    LOGGER.debug('Vendoring directory [%s] => [%s]', src, dest)
    if os.path.exists(dest):
      shutil.rmtree(dest)
    shutil.copytree(src, dest)


class _ActionBase(object):
  """Simple base class for an action."""

  def run(self, c, workdir):
    raise NotImlpementedError()


class _VendoredPythonProtobuf(_ActionBase):
  """Manages checking out the Protobuf Git repository, installing `protoc` tool,
  registering that tool with the Context, using that tool to build the Python
  protobuf package and compiled protobufs, and installs those protobufs into
  a vendored destination.
  """

  def __init__(self, reldest, repo, ref):
    self._reldest = reldest
    self._repo = repo
    self._ref = ref

  def run(self, c, workdir):
    dest = c.dest(self._reldest)

    src = os.path.join(workdir, 'repo')
    c.check_call(['git', 'clone', self._repo, src])
    c.check_call(['git', '-C', src, 'checkout', self._ref])

    # Build and install "protoc" to the specified prefix.
    prefix = os.path.join(workdir, 'prefix')
    c.check_call([os.path.join(src, 'autogen.sh')], cwd=src)
    c.check_call([os.path.join(src, 'configure'), '--prefix', prefix],
                 cwd=src)
    c.check_call(['make', '-j%d' % (multiprocessing.cpu_count(),),
                  'install'], cwd=src)

    # Export our protoc path to the vendor registry.
    c.add_tool('protoc', os.path.join(prefix, 'bin', 'protoc'))

    # Augment our PATH to include the prefix output.
    protobuf_python = os.path.join(src, 'python')
    build = os.path.join(workdir, 'build')
    pure = os.path.join(build, 'pure')
    c.check_call([
        os.path.join(protobuf_python, 'setup.py'),
        'build',
        '--build-base', build,
        '--build-purelib', pure,
    ], cwd=protobuf_python)

    # Replace our vendored directory with the pure build directory.
    python_proto_lib = os.path.join(pure, 'google')
    c.vendor_dir(python_proto_lib, dest)


class _VendoredPipPackage(_ActionBase):
  """Installs a versioned `pip` package into a vendored destination."""

  def __init__(self, reldest, name, version):
    self._reldest = reldest
    self._name = name
    self._version = version

  def run(self, c, workdir):
    dest = c.dest(self._reldest)

    install_dir = os.path.join(workdir, 'six')
    c.check_call(['pip', 'install', '--verbose', '-t', install_dir,
                  '%s==%s' % (self._name, self._version)])

    c.vendor_dir(install_dir, dest)


class _VendoredLuciGoProto(_ActionBase):
  """Uses the installed `protoc` tool to compile Python protobufs from the
  `luci-go` repository, and installs those protobufs into a vendored
  destination.
  """

  _REPO = 'https://github.com/luci/luci-go'

  def __init__(self, reldest, relsrc, ref):
    self._reldest = reldest
    self._relsrc = relsrc
    self._ref = ref

  def run(self, c, workdir):
    dest = c.dest(self._reldest)
    if not os.path.isdir(dest):
      os.makedirs(dest)

    src = os.path.join(workdir, 'repo')
    c.check_call(['git', 'clone', '--depth=1', self._REPO, src])
    c.check_call(['git', '-C', src, 'checkout', self._ref])

    in_path = _path(src, self._relsrc)
    all_proto = glob.glob(os.path.join(in_path, '*.proto'))
    c.check_call([c.tool('protoc'), '-I', in_path, '--python_out', dest] +
                  all_proto)


class _VendoredGitRepo(_ActionBase):
  """Loads a Git repository into a vendored destination."""

  def __init__(self, reldest, repo, ref, subpath=None):
    self._reldest = reldest
    self._repo = repo
    self._ref = ref
    self._subpath = subpath

  def run(self, c, workdir):
    dest = c.dest(self._reldest)

    # Use a separate Git directory so we don't copy it when we clone.
    src = os.path.join(workdir, 'repo')
    git_dir = os.path.join(workdir, 'repo_git_dir')
    c.check_call(['git', 'clone', '--separate-git-dir', git_dir,
                  '--depth=1', self._repo, src])
    c.check_call(['git', '--git-dir', git_dir, '-C', src,
                  'checkout', self._ref])

    if self._subpath:
      src = _path(src, self._subpath)
    c.vendor_dir(src, dest)


class _RegenerateLocalProtobufs(_ActionBase):
  """Runs the Context-installed `protoc` tool to generate recipe engine
  protobufs.
  """

  _LOCAL_PROTO_DIRS = (
      'recipe_engine',
  )

  def run(self, c, _workdir):
    for d in self._LOCAL_PROTO_DIRS:
      outdir = c.dest(d)

      d = _path(REPO_DIR, d)
      all_proto = glob.glob(os.path.join(d, '*.proto'))

      c.check_call([c.tool('protoc'), '-I', d, '--python_out', outdir] +
                    all_proto)


_ACTIONS = (
    _VendoredPipPackage(
        'recipe_engine/third_party/six',
        name='six',
        version='1.10.0'),

    _VendoredPipPackage(
        'recipe_engine/third_party/requests',
        name='requests',
        version='2.10.0'),

    _VendoredGitRepo(
        'recipe_engine/third_party/client-py/libs',
        repo='https://github.com/luci/client-py',
        ref='origin/master',
        subpath='libs'),

    # All actions that rely on "protoc" must happen after this one.
    _VendoredPythonProtobuf(
        'recipe_engine/third_party/google',
        repo='https://github.com/google/protobuf',
        ref='v3.1.0'),

    _VendoredLuciGoProto(
        'recipe_engine/third_party',
        relsrc='common/proto/milo',
        ref='origin/master'),

    _RegenerateLocalProtobufs(),
)


def main(argv):
  parser = argparse.ArgumentParser()
  parser.add_argument('--dest', default=REPO_DIR,
      help='The destination to vendor into.')
  parser.add_argument('--leak', action='store_true',
      help='Leak temporary working directory.')
  opts = parser.parse_args(argv)

  c = Context(opts.dest)
  with _tempdir(leak=opts.leak) as td:
    for i, act in enumerate(_ACTIONS):
      vdir = os.path.join(td, 'vendor_%d' % (i,))
      os.makedirs(vdir)

      # Execute the vendor script.
      act.run(c, vdir)


if __name__ == '__main__':
  logging.basicConfig(level=logging.DEBUG)
  sys.exit(main(sys.argv[1:]))
