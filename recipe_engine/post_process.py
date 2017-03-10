# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file contains post process filters for use with the
RecipeTestApi.post_process method in GenTests.
"""

import re

from collections import defaultdict, OrderedDict, namedtuple


_filterRegexEntry = namedtuple('_filterRegexEntry', 'at_most at_least fields')


class Filter(object):
  """Filter is an implementation of a post_process callable which can remove
  unwanted data from a step OrderedDict."""

  def __init__(self, *steps):
    """Builds a new Filter object. It may be optionally prepopulated by
    specifying steps.

    Usage:
      f = Filter('step_a', 'step_b')
      yield TEST + api.post_process(f)

      f = f.include('other_step')
      yield TEST + api.post_process(f)

      yield TEST + api.post_process(Filter('step_a', 'step_b', 'other_step'))
    """
    self.data = {name: () for name in steps}
    self.re_data = {}

  def __call__(self, check, step_odict):
    unused_includes = self.data.copy()
    re_data = self.re_data.copy()

    re_usage_count = defaultdict(int)

    to_ret = OrderedDict()
    for name, step in step_odict.iteritems():
      field_set = unused_includes.pop(name, None)
      if field_set is None:
        for exp, (_, _, fset) in re_data.iteritems():
          if exp.match(name):
            re_usage_count[exp] += 1
            field_set = fset
            break
      if field_set is None:
        continue
      if len(field_set) == 0:
        to_ret[name] = step
      else:
        to_ret[name] = {
          k: v for k, v in step.iteritems()
          if k in field_set or k == 'name'
        }

    check(len(unused_includes) == 0)

    for regex, (at_least, at_most, _) in re_data.iteritems():
      check(re_usage_count[regex] >= at_least)
      if at_most is not None:
        check(re_usage_count[regex] <= at_most)

    return to_ret

  def include(self, step_name, fields=()):
    """Include adds a step to the included steps set.

    Additionally, if any specified fields are provided, they will be the total
    set of fields in the filtered step. The 'name' field is always included. If
    fields is omitted, the entire step will be included.

    Args:
      step_name (str) - The name of the step to include
      fields (list(str)) - The field(s) to include. Omit to include all fields.

    Returns the new filter.
    """
    if isinstance(fields, basestring):
      raise ValueError('Expected fields to be a non-string iterable')
    new_data = self.data.copy()
    new_data[step_name] = frozenset(fields)
    ret = Filter()
    ret.data = new_data
    ret.re_data = self.re_data
    return ret

  def include_re(self, step_name_re, fields=(), at_least=1, at_most=None):
    """This includes all steps which match the given regular expression.

    If a step matches both an include() directive as well as include_re(), the
    include() directive will take precedence.

    Args:
      step_name_re (str or regex) - the regular expression of step names to
        match.
      fields (list(str)) - the field(s) to include in the matched steps. Omit to
        include all fields.
      at_least (int) - the number of steps that this regular expression MUST
        match.
      at_most (int) - the maximum number of steps that this regular expression
        MUST NOT exceed.

    Returns the new filter.
    """
    if isinstance(fields, basestring):
      raise ValueError('Expected fields to be a non-string iterable')
    new_re_data = self.re_data.copy()
    new_re_data[re.compile(step_name_re)] = _filterRegexEntry(
      at_least, at_most, frozenset(fields))

    ret = Filter()
    ret.data = self.data
    ret.re_data = new_re_data
    return ret


def DoesNotRun(check, step_odict, *steps):
  """Asserts that the given steps don't run.

  Usage:
    yield TEST + api.post_process(DoesNotRun, 'step_a', 'step_b')

  """
  banSet = set(steps)
  for step_name in step_odict:
    check(step_name not in banSet)


def DoesNotRunRE(check, step_odict, *step_regexes):
  """Asserts that no steps matching any of the regexes have run.

  Args:
    step_regexes (str) - The step name regexes to ban.

  Usage:
    yield TEST + api.post_process(DoesNotRunRE, '.*with_patch.*', '.*compile.*')

  """
  step_regexes = [re.compile(r) for r in step_regexes]
  for step_name in step_odict:
    for r in step_regexes:
      check(not r.match(step_name))


def MustRun(check, step_odict, *steps):
  """Asserts that steps with the given names are in the expectations.

  Args:
    steps (str) - The steps that must have run.

  Usage:
    yield TEST + api.post_process(MustRun, 'step_a', 'step_b')
  """
  for step_name in steps:
    check(step_name in step_odict)


def MustRunRE(check, step_odict, step_regex, at_least=1, at_most=None):
  """Assert that steps matching the given regex completely are in the
  exepectations.

  Args:
    step_regex (str, compiled regex) - The regular expression to match.
    at_least (int) - Match at least this many steps. Matching fewer than this
      is a CHECK failure.
    at_most (int) - Optional upper bound on the number of matches. Matching
      more than this is a CHECK failure.

  Usage:
    yield TEST + api.post_process(MustRunRE, r'.*with_patch.*', at_most=2)
  """
  step_regex = re.compile(step_regex)
  matches = 0
  for step_name in step_odict:
    if step_regex.match(step_name):
      matches += 1
  check(matches >= at_least)
  if at_most is not None:
    check(matches <= at_most)


def DropExpectation(_check, _step_odict):
  """Using this post-process hook will drop the expectations for this test
  completely.

  Usage:
    yield TEST + api.post_process(DropExpectation)

  """
  return {}
