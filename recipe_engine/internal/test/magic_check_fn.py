# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Implements a Checker object which can be used in place of `assert` to check
conditions inside tests, but with much more debugging information, including
a smart selection of local variables mentioned inside of the call to check."""

import ast
import copy
import inspect
import re
import itertools

from collections import OrderedDict, deque, defaultdict, namedtuple

import astunparse

from PB.recipe_engine.test_result import TestResult


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
  resolved equivalents."""
  def __init__(self, representation, value):
    super(_resolved, self).__init__()
    self.representation = representation
    self.value = value


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
                      sorted(rslvd.value.keys()))])

    return node

  def visit_Subscript(self, node):
    """Subscript nodes are anything which is __[__]. We only want to match __[x]
    here so where the [x] is a regular Index expression (not an elipsis or
    slice). We only handle cases where x is a constant, or a resolvable variable
    lookup (so a variable lookup, index, etc.)."""
    node = self.generic_visit(node)

    if (isinstance(node.slice, ast.Index) and
        isinstance(node.value, _resolved)):
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
        node = _resolved(
          '%s[%s]' % (node.value.representation, sliceRepr),
          node.value.value[sliceVal])

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
  # filename -> {lineno -> [statements]}
  _PARSED_FILE_CACHE = defaultdict(lambda: defaultdict(list))

  def __init__(self, filename, lineno, func, args, kwargs):
    self.failed_checks = []

    # _ignore_set is the set of objects that we should never print as local
    # variables. We start this set off by including the actual Checker object,
    # since there's no value to printing that.
    self._ignore_set = {id(self)}

    self._ctx_filename = filename
    self._ctx_lineno = lineno
    self._ctx_funcname = _nameOfCallable(func)
    self._ctx_args = map(repr, args)
    self._ctx_kwargs = {k: repr(v) for k, v in kwargs.iteritems()}

  def _ignore(self, *ignores):
    self._ignore_set.update(id(i) for i in ignores)

  def _get_statements_for_frame(self, frame):
    """This parses the file containing frame, and then extracts all simple
    statements (i.e. those which do not contain other statements). It then
    returns the list of all statements (as AST nodes) which occur on the line
    number indicated by the frame.

    The parse and statement extraction is cached in the _PARSED_FILE_CACHE class
    variable, so multiple assertions in the same file only pay the parsing cost
    once.
    """
    raw_frame, filename, lineno, _, _, _ = frame
    if filename not in self._PARSED_FILE_CACHE:
      # multi-statement nodes like Module, FunctionDef, etc. have attributes on
      # them like 'body' which house the list of statements they contain. The
      # `to_push` list here is the set of all such attributes across all ast
      # nodes. The goal is to add the CONTENTS of all multi-statement statements
      # to the queue, and anything else is considered a 'single statement' for
      # the purposes of this code.
      to_push = ['test', 'body', 'orelse', 'finalbody', 'excepthandler']
      lines, _ = inspect.findsource(raw_frame)
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
        self._PARSED_FILE_CACHE[filename][max_line].append(node)
        # If the expression contains any nested lambda definitions, then its
        # possible we may encounter frames that are executing the lambda. In
        # that case, any lambdas that do not appear on the last line of the
        # expression will have frames with line numbers different from frames
        # that are executing the containing expression, so look for any nested
        # lambdas and add them to the cache with the appropriate line number.
        for n in ast.walk(node):
          if isinstance(n, ast.Lambda):
            # Adding the lambda to the nodes when its on the last line results
            # in both the containing expression and the lambda itself appearing
            # in the failure output, so don't add the lambda to the nodes
            lambda_max_line = get_max_lineno(n)
            if lambda_max_line != max_line:
              self._PARSED_FILE_CACHE[filename][lambda_max_line].append(n)
    return self._PARSED_FILE_CACHE[filename][lineno]

  def _process_frame(self, frame, with_vars):
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
    nodes = self._get_statements_for_frame(frame)
    raw_frame, filename, lineno, func_name, _, _ = frame

    varmap = None
    if with_vars:
      varmap = {}

      xfrmr = _checkTransformer(raw_frame.f_locals, raw_frame.f_globals)
      xfrmd = xfrmr.visit(ast.Module(copy.deepcopy(nodes)))

      for n in itertools.chain(ast.walk(xfrmd), xfrmr.extras):
        if isinstance(n, _resolved):
          val = n.value
          if isinstance(val, ast.AST):
            continue
          if n.representation in ('True', 'False', 'None'):
            continue
          if callable(val) or id(val) in self._ignore_set:
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

        innermost = len(frames) - 1
        keep_frames = [self._process_frame(f, i == innermost)
                       for i, f in enumerate(frames)]
      finally:
        del f

      self.failed_checks.append(Check(
        hint,
        self._ctx_filename,
        self._ctx_lineno,
        self._ctx_funcname,
        self._ctx_args,
        self._ctx_kwargs,
        keep_frames,
        False
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


class CheckException(Exception):
  """An exception that can be raised to signal an implicit check failure.

  This exception type is used to implement implicit checks such as the one
  performed by StepsDict. In the case of an implict check failure, it's not
  generally feasible to continue execution of the post process function. This
  exception allows for halting execution of the post process function in a way
  that the engine can recognize as safe to continue with further checks.
  """
  pass


class StepsDict(OrderedDict):
  """The dictionary of steps to be used in post_process functions.

  StepsDict acts just like an OrderedDict, mapping the step name to the step
  details for the step, with the exception that indexing with a missing key does
  not raise a KeyError. Instead StepsDict does an implicit check to make sure
  that the step is in the dictionary. If the check fails, the execution of the
  post process function is halted, a check failure will be recorded and the
  engine will continue execution as though the post process function returned
  None.
  """
  def __init__(self, checker, *args, **kwargs):
    super(StepsDict, self).__init__(*args, **kwargs)
    assert isinstance(checker, Checker)
    checker._ignore(self)
    self._checker = checker

  def __getitem__(self, step):
    # Store this to a local variable so that the variable expansion in the check
    # failure backtrace includes only the important details
    check = self._checker
    steps_dict = self
    # Store the result into a variable rather than directly using if check(...)
    # because compound statements (if) don't get nicely displayed in the check
    # failure backtrace
    step_present = check(step in steps_dict)
    if not step_present:
      raise CheckException()
    return super(StepsDict, self).__getitem__(step)


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

  # One or both may be a StepsDict, which is just OrderedDict with custom
  # __getitem__, so don't require an exact type match
  if isinstance(a, OrderedDict) and isinstance(b, OrderedDict):
    pass
  elif type(a) != type(b):
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

  elif isinstance(a, dict):
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


def _nameOfCallable(c):
  if inspect.ismethod(c):
    return c.im_class.__name__+'.'+c.__name__
  if inspect.isfunction(c):
    return c.__name__
  if hasattr(c, '__call__'):
    return c.__class__.__name__+'.__call__'
  return repr(c)
