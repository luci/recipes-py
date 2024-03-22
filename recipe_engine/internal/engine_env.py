# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from itertools import chain
from collections import defaultdict


class FakeEnviron(object):
  """This is a fake dictionary which is meant to emulate os.environ strictly for
  the purposes of interacting with merge_envs.

  It supports:
    * Any key access is answered with <key>, allowing this to be used as
      a % format argument.
    * Deleting/setting items sets them to None/value, appropriately.
    * `in` checks always returns True
    * copy() returns self

  The 'formatted' result can be obtained by looking at .data.
  """
  def __init__(self):
    self.data = {}

  def __getitem__(self, key):
    return '<%s>' % key

  def get(self, key, default=None):
    return self[key]

  def keys(self):
    return list(self.data)

  def items(self):
    return self.data.items()

  def pop(self, key, default=None):
    result = self.data.get(key, default)
    self.data[key] = None
    return result

  def __delitem__(self, key):
    self.data[key] = None

  def __contains__(self, key):
    return True

  def __setitem__(self, key, value):
    self.data[key] = value

  def copy(self):
    return self


def merge_envs(original, overrides, prefixes, suffixes, pathsep):
  """Merges two environments.

  Returns a new environment dict with entries from `overrides` overwriting
  corresponding entries in `original`. Keys in `overrides` whose value is None
  will completely remove the environment variable. Values can contain %(KEY)s
  strings, which will be substituted with the values from the original (useful
  for amending, as opposed to overwriting, variables like PATH).

  Also returns a set of removed keys; this is used by the simulation tests to
  retain explicit envvar deletions for the test expectations.

  See StepConfig for environment construction rules.

  Args:

    * original (Dict[str, str]|FakeEnviron) - The base "real" environment to
      merge into.
    * overrides (Dict[str, str|None]) - The values to overwrite with.
    * prefixes (Dict[str, List[str]]) - Values to prepend (joined with
      `pathsep`) to PATH-like environment variables.
    * suffixes (Dict[str, List[str]]) - Values to append (joined with `pathsep`)
      to PATH-like environment variables.
    * pathsep (str) - The separator to use when adding `prefixes` and `suffixes`
      to the env.

  Returns (merged_env : Dict[str, str], removed_keys : Set[str])
  """
  result = dict(original.items())
  removed = set()

  if not any((prefixes, suffixes, overrides)):
    return result, removed

  subst = (original if isinstance(original, FakeEnviron)
           else defaultdict(lambda: '', **original))

  merged = set()
  for k in set(suffixes).union(prefixes):
    pfxs = tuple(prefixes.get(k, ()))
    sfxs = tuple(suffixes.get(k, ()))
    if not (pfxs or sfxs):
      continue

    # If the same key is defined in "overrides", we need to incorporate with it.
    # We'll do so here, and skip it in the "overrides" construction.
    merged.add(k)
    if k in overrides:
      val = overrides[k]
      if val is not None:
        # TODO(iannucci): Remove % formatting hacks from recipe engine
        # environment processing; all known uses should be using env
        # suffix/prefix instead.
        val = str(val) % subst
    else:
      # Not defined. Append "val" iff it is defined in "original" and not empty.
      val = original.get(k, '')
    if val:
      pfxs += (val,)
    result[k] = pathsep.join(str(v) for v in chain(pfxs, sfxs))

  for k, v in overrides.items():
    if k in merged:
      continue
    if v is None:
      result.pop(k, None)
      removed.add(k)
    else:
      result[k] = str(v) % subst

  return result, removed
