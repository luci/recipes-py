# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import re
import sys

from builtins import zip
from gevent import subprocess


def _pattern2re(pattern):
  """Transforms a GA pattern to a regular expression."""
  i = 0
  escaped = False
  regex = ''
  # Keep track of the index where the character class started, None if we're not
  # currently parsing a character class.
  charclass_start = None
  while i < len(pattern):
    to_skip = 1
    to_add = pattern[i]
    if escaped:
      escaped = False
    elif pattern[i] == '\\':
      escaped = True
    elif pattern[i] == '[':
      charclass_start = i
    elif pattern[i] == ']':
      # When ']' is the first character after a character class starts, it
      # doesn't end it, it just means ']' is part of the character class.
      if charclass_start is None or charclass_start < i - 1:
        charclass_start = None
    elif pattern[i] == '?' and charclass_start is None:
      # '?' shouldn't be replaced inside character classes.
      to_add = '[^/]'
    elif pattern[i] == '*' and charclass_start is None:
      # '*' shouldn't be replaced inside character classes.
      if pattern[i:i+3] == '**/':
        to_add = '((.+/)?)'
        to_skip = 3
      elif pattern[i:i+2] == '**':
        to_add = '.+'
        to_skip = 2
      else:
        to_add = '[^/]*'
    elif charclass_start is None:
      to_add = re.escape(pattern[i])
    regex += to_add
    i += to_skip

  if regex.startswith('/'):
    regex = '^' + regex
  else:
    regex = '/' + regex

  return regex + '$'


def _parse_gitattr_line(line):
  """Parses a line in a GA files.

  Args:
    line (str) - A line in a GA file.
  Returns:
    If the line is empty, a comment, or doesn't modify the 'recipes' attribute,
    this function returns None.
    Otherwise, it returns a pair with |pattern| and |has_recipes|, where
    |pattern| is a regex encoding the pattern, and |has_recipes| is True if the
    'recipes' attribute was set and False if it was unset (-) or unspecified (!)
  """
  line = line.strip()
  if not line or line.startswith('#'):
    return None

  if line.startswith((r'\#', r'\!')):
    line = line[1:]

  if not line.startswith('"'):
    line = line.split()
    pattern = line[0]
    attributes = line[1:]
  else:
    is_escaped = False
    pattern = ''
    for i, c in enumerate(line[1:], 1):
      if is_escaped:
        pattern += c
        is_escaped = False
      elif c == '\\':
        is_escaped = True
      elif c == '"':
        attributes = line[i+1:].strip().split()
        break
      else:
        pattern += c

  has_recipes = None
  for attribute in reversed(attributes):
    action = True
    if attribute.startswith(('-', '!')):
      action = False
      attribute = attribute[1:]
    if attribute == 'recipes':
      has_recipes = action
      break

  if has_recipes is None:
    return None

  return _pattern2re(pattern), has_recipes


class AttrChecker(object):
  def __init__(self, repo, shortcircuit=True):
    self._repo = repo
    # Shortcircuit means we only care about whether any of the files we check
    # has the 'recipes' attribute set (which is useful when checking if the
    # revision is interesting), and not about the results for each individual
    # file (which is useful for testing).
    self._shortcircuit = shortcircuit
    # A map from the git blob hash of a .gitattributes file to a list of the
    # rules specified in that file that affect the 'recipes' attribute.
    # Each rule is a pair of (pattern, action) where |pattern| is a compiled
    # regex that matches the affected files, and action is True if the 'recipes'
    # attributes is to be set or False otherwise.
    # Rules are stored in the order they appear in the .gitattributes file.
    self._gitattr_files_cache = {}
    # Stores the gitattributes files for the current revision.
    self._gitattr_files = None

  def _git(self, cmd, stdin=None):
    """Executes a git command and returns the standard output."""
    p = subprocess.Popen(
        ['git'] + cmd,
        cwd=self._repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True)
    stdout, _ = p.communicate(stdin if stdin else None)
    if p.returncode != 0:
      raise subprocess.CalledProcessError(p.returncode, ['git'] + cmd, None)
    return stdout.strip().splitlines()

  def _get_directories(self, files):
    """Lists all the directories touched by any of the |files|."""
    dirs = set([''])
    for f in files:
      f = os.path.dirname(f)
      while f and f not in dirs:
        dirs.add(f)
        f = os.path.dirname(f)
    return dirs

  def _ensure_gitattributes_files_loaded(self, revision, files):
    """Loads and parses all the .gitattributes files in the given revision."""
    self._gitattr_files = []

    # We list all the directories that were touched by any of the files, and
    # search for .gitattributes files in them.
    touched_dirs = self._get_directories(files)
    possible_gitattr_paths = '\n'.join(
        '%s:%s' % (revision, os.path.join(d, '.gitattributes'))
        for d in touched_dirs)

    # We ask git to list the hashes for all the .gitattributes files we listed
    # above. If the file doesn't exist, git returns '<object> missing', where
    # object is the revision and .gitattribute file we asked for.
    possible_gitattr_blobs = self._git(
        ['cat-file', '--batch-check=%(objectname)'],
        possible_gitattr_paths)
    for line, d in zip(possible_gitattr_blobs, touched_dirs):
      if line.endswith(' missing'):
        continue
      if d != '':
        d += '/'
      self._gitattr_files.append(('/' + d, self._parse_gitattr_file(line)))

    # Store the paths in desc. order of length.
    self._gitattr_files.sort()
    self._gitattr_files.reverse()

  def _parse_gitattr_file(self, blob_hash):
    """Returns a list of patterns and actions parsed from the GA file.

    Parses the .gitattributes file pointed at by |blob_hash|, and returns the
    patterns that set, unset or unspecify the 'recipes' attribute.

    Args:
      blob_hash (sha1) - A hash that points to a .gitattributes file in the git
          repository.
    Returns:
      A list of |(pattern, action)| where |pattern| is a compiled regular
      expression encoding a pattern in the GA file, and |action| is True if
      'recipes' was set, and False if it was unset (-) or unspecified (!).
    """
    if blob_hash in self._gitattr_files_cache:
      return self._gitattr_files_cache[blob_hash]

    rules = []
    for line in self._git(['cat-file', 'blob', blob_hash]):
      parsed_line = _parse_gitattr_line(line)
      if parsed_line is None:
        continue
      pattern, attr_value = parsed_line
      if rules and rules[-1][1] == attr_value:
        rules[-1][0] = '((%s)|(%s))' % (rules[-1][0], pattern)
      else:
        if rules:
          rules[-1][0] = re.compile(rules[-1][0])
        rules.append([pattern, attr_value])
    if rules:
      rules[-1][0] = re.compile(rules[-1][0])

    self._gitattr_files_cache[blob_hash] = rules
    return rules

  def _check_file(self, f):
    """Check whether |f| has the 'recipes' attribute set.

    Returns True if the file |f| has the 'recipes' attribute set, and False
    otherwise.
    """
    # If the file path starts with the GA path, then the path is a parent of
    # the file. Note that since the GA paths are sorted desc. according to
    # length, the first we find will be the most specific one.
    for path, rules in self._gitattr_files:
      if not f.startswith(path):
        continue
      # Iterate over the rules in reverse, so the last rule comes first and we
      # can return early.
      result = None
      for pattern, action in reversed(rules):
        if pattern.search(f):
          result = action
          break
      # If the result is not None, then the GA told us how to handle the file
      # and we can stop looking.
      if result is not None:
        return result
    # No GA specified a rule for the file, so the attribute is unspecified and
    # not set.
    return False

  def check_files(self, revision, files):
    """Checks the 'recipes' attribute for the |files| at the given |revision|.

    If |shortcircuit| was specified when creating this object, returns True if
    any of the |files| has the 'recipes' attribute set.
    Otherwise, returns a list with an entry for each file |f| specifying
    whether it has the 'recipes' attribute set or not.
    """
    # Make sure the gitattribute files are loaded at the right revision.
    self._ensure_gitattributes_files_loaded(revision, files)
    results = (self._check_file('/' + f) for f in files)
    if self._shortcircuit:
      return any(results)
    return list(results)
