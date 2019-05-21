# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Implements a Checker object which can be used in place of `assert` to check
conditions inside tests, but with much more debugging information, including
a smart selection of local variables mentioned inside of the call to check."""

import ast
import attr
import copy
import inspect
import re
import sys
import itertools
import weakref

from collections import Iterable, OrderedDict, deque, defaultdict, namedtuple

import astunparse

from PB.recipe_engine.internal.test.test_result import TestResult

from ...types import FrozenDict


class CheckFrame(namedtuple('CheckFrame', 'fname line function code varmap')):
  def format(self, indent):
    lines = [
      '%s%s:%s - %s()' % ((' '*indent), self.fname, self.line, self.function)
    ]
    indent += 2
    lines.append('%s`%s`' % ((' '*indent), self.code))
    indent += 2
    if self.varmap:
      lines.extend('%s%s: %s' % ((' '*indent), k, v)
                   for k, v in self.varmap.iteritems())
    return '\n'.join(lines)


class Check(namedtuple('Check', (
    'name ctx_filename ctx_lineno ctx_func ctx_args ctx_kwargs '
    'frames passed'))):
  # filename -> {lineno -> [statements]}
  _PARSED_FILE_CACHE = defaultdict(lambda: defaultdict(list))
  _LAMBDA_CACHE = defaultdict(lambda: defaultdict(list))

  @classmethod
  def create(cls, name, hook_context, frames, passed, ignore_set,
             additional_varmap=None):
    try:
      keep_frames = [cls._process_frame(f, ignore_set, with_vars=False)
                     for f in frames[:-1]]
      keep_frames.append(cls._process_frame(
          frames[-1], ignore_set, with_vars=True,
          additional_varmap=additional_varmap))
    finally:
      # avoid reference cycle as suggested by inspect docs.
      del frames

    return cls(
        name,
        hook_context.filename,
        hook_context.lineno,
        cls._get_name_of_callable(hook_context.func),
        map(repr, hook_context.args),
        {k: repr(v) for k, v in hook_context.kwargs.iteritems()},
        keep_frames,
        passed,
    )

  @classmethod
  def _get_name_of_callable(cls, c):
    if inspect.ismethod(c):
      return c.im_class.__name__+'.'+c.__name__
    if inspect.isfunction(c):
      if c.__name__ == (lambda: None).__name__:
        filename = c.func_code.co_filename
        cls._ensure_file_in_cache(filename, c)
        definitions = cls._LAMBDA_CACHE[filename][c.func_code.co_firstlineno]
        assert definitions
        # If there's multiple definitions at the same line, there's not enough
        # information to distinguish which lambda c refers to, so just let
        # python's generic lambda name be used
        if len(definitions) == 1:
          return astunparse.unparse(definitions[0]).strip()
      return c.__name__
    if hasattr(c, '__call__'):
      return c.__class__.__name__+'.__call__'
    return repr(c)

  @classmethod
  def _get_statements_for_frame(cls, frame):
    raw_frame, filename, lineno, _, _, _ = frame
    cls._ensure_file_in_cache(filename, raw_frame)
    return cls._PARSED_FILE_CACHE[filename][lineno]

  @classmethod
  def _ensure_file_in_cache(cls, filename, obj_with_code):
    """This parses the file containing frame, and then extracts all simple
    statements (i.e. those which do not contain other statements). It then
    returns the list of all statements (as AST nodes) which occur on the line
    number indicated by the frame.

    The parse and statement extraction is cached in the _PARSED_FILE_CACHE class
    variable, so multiple assertions in the same file only pay the parsing cost
    once.
    """
    if filename not in cls._PARSED_FILE_CACHE:
      # multi-statement nodes like Module, FunctionDef, etc. have attributes on
      # them like 'body' which house the list of statements they contain. The
      # `to_push` list here is the set of all such attributes across all ast
      # nodes. The goal is to add the CONTENTS of all multi-statement statements
      # to the queue, and anything else is considered a 'single statement' for
      # the purposes of this code.
      to_push = ['test', 'body', 'orelse', 'finalbody', 'excepthandler']
      lines, _ = inspect.findsource(obj_with_code)
      # Start with the entire parsed document (probably ast.Module).
      queue = deque([ast.parse(''.join(lines), filename)])
      while queue:
        node = queue.pop()
        had_statements = False
        # Try to find any nested statements and push them into queue if they
        # exist.
        for key in to_push:
          val = getattr(node, key, MISSING)
          if val is not MISSING:
            had_statements = True
            if isinstance(val, list):
              # Because we're popping things off the start of the queue, and we
              # want to append nodes to _PARSED_FILE_CACHE, we reverse the
              # statements when we extend the queue with them.
              queue.extend(val[::-1])
            else:
              # In the case of 'test', it's just a single expression, not a list
              # of statements
              queue.append(val)
        if had_statements:
          continue
        # node is a 'simple' statement (doesn't contain any nested statements),
        # so find it's maxiumum line-number (e.g. the line number that would
        # show up in a stack trace), and add it to _PARSED_FILE_CACHE. Note that
        # even though this is a simple statement, it could still span multiple
        # lines.
        def get_max_lineno(node):
          return max(getattr(n, 'lineno', 0) for n in ast.walk(node))
        max_line = get_max_lineno(node)
        cls._PARSED_FILE_CACHE[filename][max_line].append(node)

        # If the expression contains any nested lambda definitions, then its
        # possible we may encounter frames that are executing the lambda. In
        # that case, any lambdas that do not appear on the last line of the
        # expression will have frames with line numbers different from frames
        # that are executing the containing expression, so look for any nested
        # lambdas and add them to the cache with the appropriate line number.
        for n in ast.walk(node):
          if not isinstance(n, ast.Lambda):
            continue
          # For the lambda cache we'll have a function with the first line
          # number rather than a frame with the current point of execution so we
          # want n.lineno rather than the maximum line number for the expression
          cls._LAMBDA_CACHE[filename][n.lineno].append(n)

          # Adding the lambda to the nodes when its on the last line results
          # in both the containing expression and the lambda itself appearing
          # in the failure output, so don't add the lambda to the nodes
          lambda_max_line = get_max_lineno(n)
          if lambda_max_line != max_line:
            cls._PARSED_FILE_CACHE[filename][lambda_max_line].append(n)

  @classmethod
  def _process_frame(cls, frame, ignore_set, with_vars, additional_varmap=None):
    """This processes a stack frame into an expect_tests.CheckFrame, which
    includes file name, line number, function name (of the function containing
    the frame), the parsed statement at that line, and the relevant local
    variables/subexpressions (if with_vars is True).

    In addition to transforming the expression with _checkTransformer, this
    will:
      * omit subexpressions which resolve to callable()'s
      * omit the overall step ordered dictionary
      * transform all subexpression values using render_user_value().
    """
    nodes = cls._get_statements_for_frame(frame)
    raw_frame, filename, lineno, func_name, _, _ = frame

    varmap = None
    if with_vars:
      varmap = dict(additional_varmap or {})

      xfrmr = _checkTransformer(raw_frame.f_locals, raw_frame.f_globals)
      xfrmd = xfrmr.visit(ast.Module(copy.deepcopy(nodes)))

      for n in itertools.chain(ast.walk(xfrmd), xfrmr.extras):
        if isinstance(n, _resolved):
          val = n.value
          if isinstance(val, ast.AST):
            continue
          if n.representation in ('True', 'False', 'None'):
            continue
          if callable(val) or id(val) in ignore_set:
            continue
          if n.representation not in varmap:
            varmap[n.representation] = render_user_value(val)

    return CheckFrame(
      filename,
      lineno,
      func_name,
      '; '.join(astunparse.unparse(n).strip() for n in nodes),
      varmap
    )

  def format(self, indent):
    '''Example:
    CHECK "something was run" (FAIL):
      added /.../recipes-py/recipes/engine_tests/whitelist_steps.py:28
        MustRun('fakiestep')
      /.../recipes-py/recipe_engine/post_process.py:160 - MustRun()
        `check("something was run", (step_name in step_odict))`
          step_odict.keys(): ['something important', 'fakestep', '$result']
          step_name: 'fakiestep'
    '''

    ret = (' '*indent)+'CHECK%(name)s(%(passed)s):\n' % {
      'name': ' %r ' % self.name if self.name else '',
      'passed': 'PASS' if self.passed else 'FAIL',
    }
    indent += 2
    ret += '\n'.join(map(lambda f: f.format(indent), self.frames)) + '\n'

    ret += (' '*indent)+'added %s:%d\n' % (self.ctx_filename, self.ctx_lineno)
    func = '%s(' % self.ctx_func
    if self.ctx_args:
      func += ', '.join(self.ctx_args)
    if self.ctx_kwargs:
      func += ', '.join(['%s=%s' % i for i in self.ctx_kwargs.iteritems()])
    func += ')'
    ret += (' '*indent)+'  '+func
    return ret

  def as_proto(self):
    proto = TestResult.TestFailure()
    if self.name:
      proto.check_failure.name = self.name
    proto.check_failure.func = self.ctx_func
    proto.check_failure.args.extend([str(a) for a in self.ctx_args])
    for k, v in self.ctx_kwargs.iteritems():
      proto.check_failure.kwargs[k] = v
    proto.check_failure.filename = self.ctx_filename
    proto.check_failure.lineno = self.ctx_lineno
    return proto


class _resolved(ast.AST):
  """_resolved is a fake AST node which represents a resolved sub-expression.
  It's used by _checkTransformer to replace portions of its AST with their
  resolved equivalents. The valid field indicates that the value corresponds to
  the actual value in source, so operations present in source can be applied.
  Otherwise, attempting to execute operations present in the source may cause
  errors e.g. a dictionary value replaced with its keys because the values
  aren't relevant to the check failure."""
  def __init__(self, representation, value, valid=True):
    super(_resolved, self).__init__()
    self.representation = representation
    self.value = value
    self.valid = valid


class _checkTransformer(ast.NodeTransformer):
  """_checkTransformer is an ast NodeTransformer which extracts the helpful
  subexpressions from a python expression (specificially, from an invocation of
  the Checker). These subexpressions will be printed along with the check's
  source code statement to provide context for the failed check.

  It knows the following transformations:
    * all python identifiers will be resolved to their local variable meaning.
    * `___ in <instance of dict>` will cause dict.keys() to be printed in lieu
      of the entire dictionary.
    * `a[b][c]` will cause `a[b]` and `a[b][c]` to be printed (for an arbitrary
      level of recursion)

  The transformed ast is NOT a valid python AST... In particular, every reduced
  subexpression will be a _resolved() where the `representation` is the code for
  the subexpression (It could be any valid expression like `foo.bar()`),
  and the `value` will be the eval'd value for that element.

  In addition to this, there will be a list of _resolved nodes in the
  transformer's `extra` attribute for additional expressions which should be
  printed for debugging usefulness, but didn't fit into the ast tree anywhere.
  """

  def __init__(self, lvars, gvars):
    self.lvars = lvars
    self.gvars = gvars
    self.extras = []

  def visit_Compare(self, node):
    """Compare nodes occur for all sequences of comparison (`in`, gt, lt, etc.)
    operators. We only want to match `___ in instanceof(dict)` here, so we
    restrict this to Compare ops with a single operator which is `In` or
    `NotIn`.
    """
    node = self.generic_visit(node)

    if len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)):
      cmps = node.comparators
      if len(cmps) == 1 and isinstance(cmps[0], _resolved):
        rslvd = cmps[0]
        if isinstance(rslvd.value, dict):
          node = ast.Compare(
            node.left,
            node.ops,
            [_resolved(rslvd.representation+".keys()",
                       sorted(rslvd.value.keys()),
                       valid=False)])

    return node

  def visit_Attribute(self, node):
    """Attribute nodes occur for attribute access (e.g. foo.bar). We want to
    follow attribute access where possible to so that we can provide the value
    that resulted in a check failure.
    """
    node = self.generic_visit(node)
    if isinstance(node.value, _resolved):
      node = _resolved(
          '%s.%s' % (node.value.representation, node.attr),
          getattr(node.value.value, node.attr))
    return node

  def visit_Subscript(self, node):
    """Subscript nodes are anything which is __[__]. We only want to match __[x]
    here so where the [x] is a regular Index expression (not an elipsis or
    slice). We only handle cases where x is a constant, or a resolvable variable
    lookup (so a variable lookup, index, etc.)."""
    node = self.generic_visit(node)

    if (isinstance(node.slice, ast.Index) and
        isinstance(node.value, _resolved) and
        node.value.valid):
      sliceVal = MISSING
      sliceRepr = ''
      if isinstance(node.slice.value, _resolved):
        # (a[b])[c]
        # will include `a[b]` in the extras.
        self.extras.append(node.slice.value)
        sliceVal = node.slice.value.value
        sliceRepr = node.slice.value.representation
      elif isinstance(node.slice.value, ast.Num):
        sliceVal = node.slice.value.n
        sliceRepr = repr(sliceVal)
      elif isinstance(node.slice.value, ast.Str):
        sliceVal = node.slice.value.s
        sliceRepr = repr(sliceVal)
      if sliceVal is not MISSING:
        try:
          node = _resolved(
            '%s[%s]' % (node.value.representation, sliceRepr),
            node.value.value[sliceVal])
        except KeyError:
          rslvd = node.value
          if not isinstance(rslvd.value, dict):
            raise
          node = _resolved(rslvd.representation+".keys()",
                           sorted(rslvd.value.keys()),
                           valid=False)

    return node

  def visit_Name(self, node):
    """Matches a single, simple identifier (e.g. variable).

    This will lookup the variable value from python constants (e.g. True),
    followed by the frame's local variables, and finally by the frame's global
    variables.
    """
    consts = {'True': True, 'False': False, 'None': None}
    val = consts.get(
      node.id, self.lvars.get(
        node.id, self.gvars.get(
          node.id, MISSING)))
    if val is not MISSING:
      return _resolved(node.id, val)
    return node


def render_user_value(val):
  """Takes a subexpression user value, and attempts to render it in the most
  useful way possible.

  Currently this will use render_re for compiled regular expressions, and will
  fall back to repr() for everything else.

  It should be the goal of this function to return an `eval`able string that
  would yield the equivalent value in a python interpreter.
  """
  if isinstance(val, re._pattern_type):
    return render_re(val)
  return repr(val)


def render_re(regex):
  """Renders a repr()-style value for a compiled regular expression."""
  actual_flags = []
  if regex.flags:
    flags = [
      (re.IGNORECASE, 'IGNORECASE'),
      (re.LOCALE, 'LOCALE'),
      (re.UNICODE, 'UNICODE'),
      (re.MULTILINE, 'MULTILINE'),
      (re.DOTALL, 'DOTALL'),
      (re.VERBOSE, 'VERBOSE'),
    ]
    for val, name in flags:
      if regex.flags & val:
        actual_flags.append(name)
  if actual_flags:
    return 're.compile(%r, %s)' % (regex.pattern, '|'.join(actual_flags))
  else:
    return 're.compile(%r)' % regex.pattern


class Checker(object):
  def __init__(self, hook_context, *ignores):
    self.failed_checks = []

    # _ignore_set is the set of objects that we should never print as local
    # variables. We start this set off by including the actual Checker object,
    # since there's no value to printing that.
    self._ignore_set = {id(x) for x in ignores+(self,)}

    self._hook_context = hook_context

  def _call_impl(self, hint, exp):
    """This implements the bulk of what happens when you run `check(exp)`. It
    will crawl back up the stack and extract information about all of the frames
    which are relevent to the check, including file:lineno and the code
    statement which occurs at that location for all the frames.

    On the last frame (the one that actually contains the check call), it will
    also try to obtain relevant local values in the check so they can be printed
    with the check to aid in debugging and diagnosis. It uses the parsed
    statement found at that line to find all referenced local variables in that
    frame.
    """

    if exp:
      # TODO(iannucci): collect this in verbose mode.
      # this check passed
      return

    # Grab all frames between (non-inclusive) the creation of the checker and
    # self.__call__
    try:
      # Skip over the __call__ and _call_impl frames and order it so that
      # innermost frame is at the bottom
      frames = inspect.stack()[2:][::-1]

      try:
        for i, f in enumerate(frames):
          # The first frame that has self in the local variables is the one
          # where the checker is created
          if self in f[0].f_locals.itervalues():
            break
        frames = frames[i+1:]

      finally:
        del f

      self.failed_checks.append(Check.create(
          hint,
          self._hook_context,
          frames,
          False,
          self._ignore_set,
      ))
    finally:
      # avoid reference cycle as suggested by inspect docs.
      del frames

  def __call__(self, arg1, arg2=None):
    if arg2 is not None:
      hint = arg1
      exp = arg2
    else:
      hint = None
      exp = arg1
    self._call_impl(hint, exp)
    return bool(exp)


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
  """The representation of a step provided to post-process hooks."""
  # Fields from step dict
  # The name of the step as a string
  name = attr.ib()

  # The step's command as a list of strings
  # cmd is present in the initial step dict even when its empty, so using None
  # as the default allows us to just compare against the default like any other
  # field and preserve any empty list
  cmd = attr.ib(default=None)

  # The working directory that the step is executed under as a string
  cwd = attr.ib(default='')

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

  # Strings containing the content of the step's stdin, stdout and stderr
  stdout = attr.ib(default='')
  stderr = attr.ib(default='')
  stdin = attr.ib(default='')

  # Fields that appear in followup annotations in expectations
  # The nest level of the step: 0 is a top-level step
  nest_level = attr.ib(default=0)

  # A string containing the step's step text
  step_text = attr.ib(default='')

  # A string containing the step's step summary text
  step_summary_text = attr.ib(default='')

  # A dictionary containing the step's logs, mapping strings containing the log
  # name to strings containing the content of the log
  logs = attr.ib(factory=OrderedDict)

  # A dictionary containing the step's links, mapping strings containing the
  # link name to strings containing the link url
  links = attr.ib(factory=OrderedDict)

  # A dictionary containing the build properties set by the step, mapping
  # strings containing the property name to json-ish strings containing the
  # value of the property
  output_properties = attr.ib(factory=OrderedDict)

  # A string containing the resulting status of the step, one of: 'SUCCESS',
  # 'EXCEPTION', 'FAILURE', 'WARNING'
  status = attr.ib(default='SUCCESS')

  # Aribtrary lines that are output into ~followup_annotations in expectations
  _raw_annotations = attr.ib(default=[])

  @classmethod
  def from_step_dict(cls, step_dict):
    if 'name' not in step_dict:
      raise ValueError("step dict must have 'name' key, step dict keys: %r"
                       % sorted(step_dict.iterkeys()))
    if step_dict.get('cmd', None) is not None:
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


MISSING = object()


def VerifySubset(a, b):
  """Verify subset verifies that `a` is a subset of `b` where a and b are both
  JSON-ish types. They are also permitted to be OrderedDicts instead of
  dictionaries.

  This verifies that a introduces no extra dictionary keys, list elements, etc.
  and also ensures that the order of entries in an ordered type (such as a list
  or an OrderedDict) remain the same from a to b. This also verifies that types
  are consistent between a and b.

  As a special case, empty and single-element dictionaries are considered
  subsets of an OrderedDict, even though their types don't precisely match.

  If a is a valid subset of b, this returns None. Otherwise this returns
  a descriptive message of what went wrong.

  Example:
    print 'object'+VerifySubset({'a': 'thing'}, {'b': 'other', 'a': 'prime'})

  OUTPUT:
    object['a']: 'thing' != 'prime'
  """
  if a is b:
    return

  if isinstance(b, OrderedDict) and isinstance(a, dict):
    # 0 and 1-element dicts can stand in for OrderedDicts.
    if len(a) == 0:
      return
    elif len(a) == 1:
      a = OrderedDict([next(a.iteritems())])

  if type(a) != type(b):
    return ': type mismatch: %r v %r' % (type(a).__name__, type(b).__name__)

  if isinstance(a, OrderedDict):
    last_idx = 0
    b_reverse_index = {k: (i, v) for i, (k, v) in enumerate(b.iteritems())}
    for k, v in a.iteritems():
      j, b_val = b_reverse_index.get(k, (MISSING, MISSING))
      if j is MISSING:
        return ': added key %r' % k

      if j < last_idx:
        return ': key %r is out of order' % k
      # j == last_idx is not possible, these are OrderedDicts
      last_idx = j

      msg = VerifySubset(v, b_val)
      if msg:
        return '[%r]%s' % (k, msg)

  elif isinstance(a, (dict, FrozenDict)):
    for k, v in a.iteritems():
      b_val = b.get(k, MISSING)
      if b_val is MISSING:
        return ': added key %r' % k

      msg = VerifySubset(v, b_val)
      if msg:
        return '[%r]%s' % (k, msg)

  elif isinstance(a, list):
    if len(a) > len(b):
      return ': too long: %d v %d' % (len(a), len(b))

    if not (a or b):
      return

    bi = ai = 0
    while bi < len(b) - 1 and ai < len(a) - 1:
      msg = VerifySubset(a[ai], b[bi])
      if msg is None:
        ai += 1
      bi += 1
    if ai != len(a) - 1:
      return ': added %d elements' % (len(a)-1-ai)

  elif isinstance(a, (basestring, int, bool, type(None))):
    if a != b:
      return ': %r != %r' % (a, b)

  else:
    return ': unknown type: %r' % (type(a).__name__)


class PostProcessError(ValueError):
  """Exception raised when any of the post-process hooks fails."""
  pass


def post_process(raw_expectations, test_data):
  """Run post processing hooks against the expectations generated by a test.

  Args:
    raw_expectations - A dictionary mapping the name of a step to a dictionary
        containing the details of that step.
    test_data - The TestData object for the current test, containing the post
        process hooks to run.

  Returns:
    A tuple containing 2 items: the resultant raw expectations and a list of
    check failures. The raw expectations will be in the same format as the
    raw_expectations argument or None if expectations should not be written out.
    The failures will be a list of Check objects describing the check failures
    encountered by the post processing hooks.
  """
  failed_checks = []
  for hook, args, kwargs, context in test_data.post_process_hooks:
    steps = copy.deepcopy(raw_expectations)
    # The checker MUST be saved to a local variable in order for it to be able
    # to correctly detect the frames to keep when creating a failure backtrace
    check = Checker(context, steps)
    for k, v in steps.iteritems():
      if k != '$result':
        steps[k] = Step.from_step_dict(v)
    try:
      rslt = hook(check, steps, *args, **kwargs)
    except KeyError:
      exc_type, exc_value, exc_traceback = sys.exc_info()
      try:
        failed_checks.append(Check.create(
            '',
            context,
            inspect.getinnerframes(exc_traceback)[1:],
            False,
            check._ignore_set,
            {'raised exception':
             '%s: %r' % (exc_type.__name__, exc_value.message)},
        ))
      finally:
        # avoid reference cycle as suggested by inspect docs.
        del exc_traceback
      continue

    failed_checks += check.failed_checks
    if rslt is not None:
      for k, v in rslt.iteritems():
        if isinstance(v, Step):
          rslt[k] = v.to_step_dict()
        else:
          cmd = rslt[k].get('cmd', None)
          if cmd is not None:
            rslt[k]['cmd'] = list(cmd)
      msg = VerifySubset(rslt, raw_expectations)
      if msg:
        raise PostProcessError('post process: steps' + msg)
      # restore 'name' if it was removed
      for k, v in rslt.iteritems():
        v['name'] = k
      raw_expectations = rslt

  # Empty means drop expectations
  result_data = raw_expectations.values() if raw_expectations else None
  return result_data, failed_checks
