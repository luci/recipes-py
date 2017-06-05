# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os

from . import env

from google.protobuf import json_format
from . import package_pb2


API_VERSIONS = frozenset([2])


def parse(raw):
  """Parses a package_pb2.Package from a string.

  Args:
    raw (str) - The string containing the recipes.cfg contents.

  Returns (package_pb2.Package).
  """
  obj = json.loads(raw)

  vers = obj.get('api_version')
  assert vers in API_VERSIONS, (
    'expected %r to be one of %r' % (vers, API_VERSIONS))

  buf = package_pb2.Package()
  json_format.ParseDict(obj, buf, ignore_unknown_fields=True)
  return buf


def dump_obj(buf):
  """Dumps a package_pb2.Package to a jsonish dict.

  Args:
    buf (package_pb2.Package) - the Package to dump

  Returns (dict)
  """
  return json_format.MessageToDict(buf, preserving_proto_field_name=True)


def dump(buf):
  """Dumps a package_pb2.Package to a string.

  Args:
    buf (package_pb2.Package) - the Package to dump

  Returns (str)
  """
  return json.dumps(
    dump_obj(buf), indent=2, sort_keys=True).replace(' \n', '\n') + '\n'


class PackageFile(object):
  """A collection of functions operating on a recipes.cfg (package) config file.

  This is an object so that it can be mocked in the tests.

  Proto files read will always be upconverted to the current proto in
  package.proto, and will be written back in their original format.
  """

  def __init__(self, path):
    self._path = path

  @property
  def path(self):
    return os.path.realpath(self._path)

  def read_raw(self):
    with open(self._path, 'r') as fh:
      return fh.read()

  def read(self):
    return parse(self.read_raw())

  def to_raw(self, buf):
    return dump(buf)

  def write(self, buf):
    with open(self._path, 'w') as fh:
      fh.write(self.to_raw(buf))


class InfraRepoConfig(object):
  RELPATH = 'infra/config/recipes.cfg'

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
