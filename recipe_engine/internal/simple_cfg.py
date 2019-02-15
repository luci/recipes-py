# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""A simple, proto-free version of recipes_cfg.proto.

This allows the command-line parsing to be protobuf-free so that the recipe
engine can present a unified protobuf implementation.
"""

import json
import logging
import os

import attr

from ..types import freeze

from .attr_util import attr_dict_type, attr_type, attr_value_is

LOG = logging.getLogger(__name__)

# This is the subdirectory in every recipe repo where we look for the
# recipes.cfg file.
# NOTE: If we want to change/autodetect the location of recipes.cfg, look for
# all references to this.
RECIPES_CFG_LOCATION_TOKS = ('infra', 'config', 'recipes.cfg')
RECIPES_CFG_LOCATION_REL = os.path.join(*RECIPES_CFG_LOCATION_TOKS)


def _branch_converter(ref):
  """Converts a possibly-non-absolute ref to an absolute one (i.e. one beginning
  with 'refs/').

  Logs a warning when implicit conversion takes place.

  Returns the converted ref.
  """
  if not isinstance(ref, str):
    return ref # validator will catch this
  if ref.startswith('refs/'):
    return ref
  if ref == 'HEAD':  # This is special, and is used in tests.
    return ref
  conv = 'refs/heads/' + ref
  LOG.warn('DEPRECATED: Non-absolute git branch in recipes.cfg: %r', ref)
  LOG.warn('  Converting to %r.', conv)
  LOG.warn('  Change `recipes.cfg` to have this value to remove warning.')
  LOG.warn('  This warning will become a hard error in the future.')
  return conv


@attr.s(frozen=True)
class SimpleDep(object):
  """Represents a single dependency (url, branch, revision).

  Equivalent to the recipes_cfg_pb2.DepSpec message.
  """
  # The git URL for this dependency.
  url = attr.ib(validator=attr_type(str))

  # The ref to git-fetch if url is a git repo.
  # Automatically converts non-absolute refs to 'refs/heads/...'.
  # TODO(iannucci): Require absolute refs.
  branch = attr.ib(converter=_branch_converter, validator=attr_type(str))

  # The git commit we depend on.
  revision = attr.ib(validator=attr_type(str))


@attr.s(frozen=True)
class SimpleRecipesCfg(object):
  """Represents a `recipes.cfg` file.

  A subset of the recipes_cfg_pb2.RepoSpec message, just enough to load the
  dependencies for this recipe repo (i.e. good enough for RecipeDeps' purposes).
  """
  # The "name" of this recipe repo. This is the name that other recipe repos will
  # use to import modules from this repo. Currently this name must be globally
  # unique amongst recipe repos (d'oh). In practice, global uniqueness has not
  # yet been an issue.
  repo_name = attr.ib(validator=attr_type(str))

  # The mapping of other recipe repo id's that we depend on to their dependency
  # pin information.
  deps = attr.ib(
    converter=freeze,
    validator=attr_dict_type(str, SimpleDep)
  )

  # The repo-root-relative path to where 'recipes/' and/or 'recipe_modules/'
  # directories live.
  recipes_path = attr.ib(validator=[
    attr_type(str),
    attr_value_is('a relative path', lambda v: not os.path.isabs(v)),
    attr_value_is(
      'free of "." and ".."',
      lambda v: not any(x in ('.', '..') for x in v.split(os.path.sep))
    ),
  ])

  @classmethod
  def from_dict(cls, dct):
    """Parses a SimpleRecipesCfg from a dict.

    Args:
      * dct (dict) - A recipes.cfg parsed as JSON (i.e. a python dict)

    Returns parsed SimpleRecipesCfg object."""
    assert isinstance(dct, dict)
    try:
      repo_name = dct.get('repo_name')
      if repo_name is None:
        # NOTE: This must be lazily pulled from `dct` or new recipes.cfg files
        # with only 'repo_name' will fail to load.
        repo_name = dct['project_id']
      return cls(
        str(repo_name),
        {
          str(k): SimpleDep(
            str(v['url']),
            str(v['branch']),
            str(v['revision']),
          ) for k, v in dct.get('deps', {}).iteritems()
        },
        str(dct.get('recipes_path', '')),
      )
    except Exception as ex:
      raise ValueError('Error parsing recipes.cfg: %r' % (ex,))

  def asdict(self):
    """Returns this SimpleRecipesCfg as a JSON-serializable dict.

    This is mostly the same as `attr.asdict`, except that it knows how to
    deal with the fact that SimpleRecipesCfg.deps is a FrozenDict."""
    ret = attr.asdict(self)
    ret['deps'] = {k: attr.asdict(v) for k, v in ret['deps'].iteritems()}
    ret['project_id'] = ret['repo_name']   # Alias repo_name<->project_id
    return ret

  @classmethod
  def from_json_file(cls, path):
    """Parses a SimpleRecipesCfg from a file on disk.

    Args:
      * path (str) - The path to the file to parse (this path is not retained
        so it's absolutness doesn't matter).

    Returns SimpleRecipesCfg
    """
    try:
      with open(path, 'r') as fil:
        data = fil.read()
    except OSError as ex:
      raise ValueError('Error opening recipes.cfg: %s' % (ex,))
    return cls.from_json_string(data)

  @classmethod
  def from_json_string(cls, jstring):
    """Parses a SimpleRecipesCfg from a JSON string.

    Args:
      * jstring (str) - The recipes.cfg as a JSON-encoded string.

    Returns SimpleRecipesCfg
    """
    try:
      data = json.loads(jstring)
    except Exception as ex:
      raise ValueError('Error parsing recipes.cfg as json: %s' % (ex,))

    return cls.from_dict(data)
