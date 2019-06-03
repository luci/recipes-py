# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""The types that appear as inputs to post-processing hooks."""

import re

from collections import Iterable, OrderedDict

import attr


class Command(list):
  """Specialized list enabling enhanced searching in command arguments.

  Command is a list of strings that supports searching for individual strings
  or subsequences of strings comparing by either string equality or regular
  expression. Regular expression elements are compared against strings using the
  search method of the regular expression object.

  e.g. the following all evaluate as True:
  'foo' in Command(['foo', 'bar', 'baz'])
  re.compile('a') in Command(['foo', 'bar', 'baz'])
  ['foo', 'bar'] in Command(['foo', 'bar', 'baz'])
  [re.compile('o$'), 'bar', re.compile('^b')] in Command(['foo', 'bar', 'baz'])
  """

  def __contains__(self, item):
    # Get a function that can be used for matching against an element
    # Command's elements will always be strings, so we'll only try to match
    # against strings or regexes
    def get_matcher(obj):
      if isinstance(obj, basestring):
        return lambda other: obj == other
      if isinstance(obj, re._pattern_type):
        return obj.search
      return None

    if isinstance(item, Iterable) and not isinstance(item, basestring):
      matchers = [get_matcher(e) for e in item]
    else:
      matchers = [get_matcher(item)]

    # If None is present in matchers, then that means item is/contains an object
    # of a type that we won't use for matching
    if any(m is None for m in matchers):
      return False

    # At this point, matchers is a list of functions that we can apply against
    # the elements of each subsequence in the list; if each matcher matches the
    # corresponding element of the subsequence then we say that the sequence of
    # strings/regexes is contained in the command
    for i in xrange(len(self) - len(matchers) + 1):
      for j, matcher in enumerate(matchers):
        if not matcher(self[i + j]):
          break
      else:
        return True
    return False


@attr.s
class Step(object):
  """The representation of a step provided to post-process hooks.

  A `Step` has fields for all of the details of a step that would be recorded
  into the JSON expectation file for this test. Fields set to their default
  values will not appear in the expectation file for the test. The defaults for
  each field simplify post-processing hooks by allowing the fields to be
  accessed without having to specify a default value.

  See field definitions and comments for descriptions of the field meanings and
  default values.
  """
  # **************************** Expectation fields ****************************
  # These fields appear directly in the expectations file for a test

  # TODO(iannucci) Use buildbucket step names here, e.g. 'parent|child|leaf'
  # instead of buildbot style 'parent.child.leaf' or make tuple
  # The name of the step as a string
  name = attr.ib()

  # The step's command as a sequence of strings
  # When initialized in from_step_dict, the sequence will be an instance of
  # Command, which supports an enhanced contains check that enables concise
  # subsequence and regex checking
  # Implementation note: cmd still appears in expectation files when its empty,
  # so distiniguish between an empty cmd list and a cmd that has been filtered
  # while still allowing duck-typing a default of () is used which is not equal
  # to an empty list but still supports sequence operations
  cmd = attr.ib(default=())

  # The working directory that the step is executed under as a string, in terms
  # of a placeholder e.g. RECIPE_REPO[recipe_engine]
  # An empy string is equivalent to start_dir
  cwd = attr.ib(default='')

  # The CPU cost of this step in millicores.
  cpu = attr.ib(default=500)

  # See //recipe_modules/context/api.py for information on the precise meaning
  # of env, env_prefixes and env_suffixes
  # env will be the env value for the step, a dictionary mapping strings
  # containing the environment variable names to strings containing the
  # environment variable value
  env = attr.ib(factory=dict)
  # env_prefixes and env_suffixes will be the env prefixes and suffixes for the
  # step, dictionaries mapping strings containing the environment variable names
  # to lists containing strings to be prepended/addended to the environment
  # variable
  env_prefixes = attr.ib(factory=dict)
  env_suffixes = attr.ib(factory=dict)

  # A bool indicating whether a step can emit its own annotations
  allow_subannotations = attr.ib(default=False)

  # Deprecated
  trigger_specs = attr.ib(factory=list)

  # Either None for no timeout or a numeric type containing the number of
  # seconds the step must complete in
  timeout = attr.ib(default=None)

  # A bool indicating the step is an infrastructure step that should raise
  # InfraFailure instead of StepFailure if the step finishes with an exit code
  # that is not allowed
  infra_step = attr.ib(default=False)

  # String containing the content of the step's stdin if the step's stdin was
  # redirected with a PlaceHolder
  stdin = attr.ib(default='')

  # ***************************** Annotation fields ****************************
  # These fields appear in annotations in the ~followup_annotations field in the
  # expectations file for the test

  # The nest level of the step: 0 is a top-level step
  # TODO(iannucci) Remove this
  nest_level = attr.ib(default=0)

  # A string containing the step's step text
  step_text = attr.ib(default='')

  # A string containing the step's step summary text
  step_summary_text = attr.ib(default='')

  # A dictionary containing the step's logs, mapping strings containing the log
  # name to strings containing the full content of the log (the lines of the
  # logs in the StepPresentation joined with '\n')
  logs = attr.ib(factory=OrderedDict)

  # A dictionary containing the step's links, mapping strings containing the
  # link name to strings containing the link url
  links = attr.ib(factory=OrderedDict)

  # A dictionary containing the build properties set by the step, mapping
  # strings containing the property name to json-ish objects containing the
  # value of the property.
  output_properties = attr.ib(factory=OrderedDict)

  # A string containing the resulting status of the step, one of: 'SUCCESS',
  # 'EXCEPTION', 'FAILURE', 'WARNING'
  status = attr.ib(default='SUCCESS',
                   validator=attr.validators.in_(
                       ('SUCCESS', 'EXCEPTION', 'FAILURE', 'WARNING')))

  # Arbitrary lines that appear in the annotations
  # The presence of these annotations is an implementation detail and likely to
  # change in the future, so tests should avoid operating on this field except
  # to set it to default to filter them out
  _raw_annotations = attr.ib(default=[])

  @classmethod
  def from_step_dict(cls, step_dict):
    """Create a `Step` from a step dictionary.

    Args:
      * step_dict - Dictionary containing the data to be written out to the
          expectation file for the step. All keys in the dictionary must match
          the name of one of the fields of `Step`.

    Returns:
      A `Step` object where for each item in `step_dict`, the field whose name
      matches the item's key is set to the item's value.
    """
    if 'name' not in step_dict:
      raise ValueError("step dict must have 'name' key, step dict keys: %r"
                       % sorted(step_dict.iterkeys()))
    if 'cmd' in step_dict:
      step_dict = step_dict.copy()
      step_dict['cmd'] = Command(step_dict['cmd'])
    return cls(**step_dict)

  def _as_dict(self):
    return attr.asdict(self, recurse=False)

  def to_step_dict(self):
    prototype = Step('')._as_dict()
    step_dict = {k: v for k, v in self._as_dict().iteritems()
                 if k == 'name' or v != prototype[k]}
    if step_dict.get('cmd', None) is not None:
      step_dict['cmd'] = list(step_dict['cmd'])
    for k in step_dict.keys():
      if k.startswith('_'):
        step_dict[k[1:]] = step_dict.pop(k)
    return step_dict
