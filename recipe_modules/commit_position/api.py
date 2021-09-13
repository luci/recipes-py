# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import re

from recipe_engine import recipe_api


class CommitPositionApi(recipe_api.RecipeApi):
  """Recipe module providing commit position parsing and formatting."""

  RE_COMMIT_POSITION = re.compile(
      r'(?P<ref>refs/[^@]+)@{#(?P<revision>\d+)}')

  @classmethod
  def parse(cls, value):
    """Returns (ref, revision_number) tuple."""
    match = cls.RE_COMMIT_POSITION.match(value)
    if not match:
      raise ValueError(
        'Commit position "%s" does not match r"%s"' %
        (value, cls.RE_COMMIT_POSITION.pattern))
    return match.group('ref'), int(match.group('revision'))

  @classmethod
  def format(cls, ref, revision_number):
    """Returns a commit position string.

    ref must start with 'refs/'.
    """
    assert isinstance(ref, str)
    assert ref.startswith('refs/'), ref
    revision_number = int(revision_number)
    return '%s@{#%d}' % (ref, revision_number)
