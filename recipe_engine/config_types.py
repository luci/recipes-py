# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import itertools

from dataclasses import dataclass, field
from typing import ClassVar, Generator, TYPE_CHECKING

if TYPE_CHECKING:
  from recipe_engine.internal.recipe_deps import RecipeModule, Recipe, RecipeRepo

def ResetGlobalVariableAssignments():
  """This function is called from inside of the recipe test runner prior to each
  test case executed.

  See the class variables below for what they are and what sets them.
  """
  CheckoutBasePath._resolved = None
  Path._OS_SEP = None


# These two exception classes inherit from ValueError because the corresponding
# errors in pathlib in the standard library use ValueError.
class RelativeToDifferentBases(ValueError):
  pass


class RelativeToNotParent(ValueError):
  pass


@dataclass(frozen=True)
class CheckoutBasePath:
  """CheckoutBasePath is a placeholder base for Paths relative to
  api.path.checkout_dir.

  This base is used in the following cases:
    * Construction of Paths to be sent from GenTests to RunSteps (e.g. when
    mocking paths with api.path.exists() from GenTests).
    * In select circumstances when constructing Paths inside of the recipe
    engine's "config" subsystem.

  Paths using CheckoutBasePath are 'slippery' and will try to resolve to
  a ResolvedBasePath at almost every opportunity. Resolving a CheckoutBasePath
  requires that the recipe has already assigned a value to checkout_dir in the
  recipe_engine/path module, which in turn will assign to the
  CheckoutBasePath._resolved class variable.

  If the checkout_dir has not yet been set, `resolve` on this class will raise
  a ValueError stating as such.
  """

  # HACK: This is directly assigned to by the recipe_engine/path module in the
  # checkout_dir setter.
  #
  # This is also reset by the ResetGlobalVariableAssignments() function in this
  # file, which is called from the recipe tests prior to each test case.
  _resolved: ClassVar[Path | None] = None

  def maybe_resolve(self) -> Path | None:
    """If CheckoutBasePath can be resolved to a real Path, return that,
    otherwise return None."""
    if self._resolved:
      return self._resolved

  def resolve(self) -> Path:
    """Resolve this CheckoutBasePath, raise ValueError if not yet defined."""
    checkout_dir = self.maybe_resolve()
    if checkout_dir is None:
      raise ValueError(
          f'Cannot resolve CheckoutBasePath() - api.path.checkout_dir is unset.'
      )
    return checkout_dir

  def __str__(self) -> str:
    """Returns the resolved path as a string.

    We never want to render CheckoutBasePath as anything other than the real
    path base that it points to, which means that this will raise ValueError if
    checkout_dir has not yet been assigned.
    """
    return str(self.resolve())

  def __repr__(self) -> str:
    if self._resolved:
      return str(self)
    return 'CheckoutBasePath[UNRESOLVED]'


@dataclass(frozen=True, order=True)
class ResolvedBasePath:
  """ResolvedBasePath represents a 'resolved' base path.

  In tests, this will contain a string like "[START_DIR]", "[CACHE]", etc. These
  names come from the recipe_engine/path module.

  In non-tests, this will contain an actual absolute filesystem path as a
  string.
  """
  resolved: str

  @classmethod
  def for_recipe_module(cls, test_enabled: bool,
                        module: RecipeModule) -> ResolvedBasePath:
    if not test_enabled:
      return cls(module.path)

    # We change python's module delimiter . to ::, since . is already used
    # by expect tests.
    return cls(f'RECIPE_MODULE[{module.repo.name}::{module.name}]')

  @classmethod
  def for_recipe_script_resources(cls, test_enabled: bool,
                                  recipe: Recipe) -> ResolvedBasePath:
    if not test_enabled:
      return cls(recipe.resources_dir)
    return cls(f'RECIPE[{recipe.full_name}].resources')

  @classmethod
  def for_bundled_repo(cls, test_enabled: bool,
                       repo: RecipeRepo) -> ResolvedBasePath:
    if not test_enabled:
      return cls(repo.path)
    return cls(f'RECIPE_REPO[{repo.name}]')

  def __repr__(self) -> str:
    return self.resolved


@dataclass(frozen=True)
class Path:
  """Represents an absolute path which is relative to a 'base' path.

  The `base` is either a ResolvedBasePath or a CheckoutBasePath.

  This Path is made aware of the currently simulated path separator from the
  __init__ method of the recipe_engine/path module, which assigns to this
  class's _OS_SEP variable.
  """
  base: CheckoutBasePath | ResolvedBasePath
  pieces: tuple[str, ...]

  # HACK: This is directly assigned to by the recipe_engine/path module, and is
  # populated with the current path separator character (either '/' or '\\').
  #
  # This is also reset by the ResetGlobalVariableAssignments() function in this
  # file, which is called from the recipe tests prior to each test case.
  _OS_SEP: ClassVar[str | None] = None

  # This field is used to cache the output of __str__.
  #
  # Why not use @functools.cache on __str__? Unfortunately, this effectively
  # creates a global variable Path.__str__.<wrapper func>.cache, which is a dict
  # mapping Path instances to their __str__() values. This is 'fine', but it
  # ends up capturing the value of _OS_SEP which can change multiple times per
  # process run (see ResetGlobalVariableAssignments). This can still be used by
  # adding Path.__str__.cache_clear() to ResetGlobalVariableAssignments, but
  # I don't think introducing the extra global variable is necessary or
  # desirable here, especially since we know that Path is immutable.
  _str: str | None = field(default=None, repr=False, hash=False, compare=False)

  def __init__(self, base: CheckoutBasePath | ResolvedBasePath, *pieces: str):
    """Creates a Path.

    Args:
      base: Either a CheckoutBasePath, which represents a placeholder for
        a ResolvedBasePath, or a ResolvedBasePath.
      *pieces: The components of the path relative to base.
        - If this recipe is being run on windows, pieces with '/' or '\\' will
          be split. On non-windows, they will be split only on '/'.
        - Split pieces equaling '..' must not go above the `base`. That is, if
          you give `Path(ResolvedBasePath('[CACHE]'), '..', 'something')`, this
          will raise ValueError because the '..' would bring this Path above the
          base. However, `Path(ResolvedBasePath('[CACHE]'), 'something', '..')`
          is OK and would be equivalent to `Path(ResolvedBasePath('[CACHE]'))`.
        - Empty pieces and pieces which are '.' are ignored.
        - If the recipe is not yet running (e.g. you are calling Path from
          GenTests), and you include a '\\' in a piece, this will raise
          ValueError (just use '/' or separate the pieces yourself in that
          case).
    """
    super().__init__()
    if not isinstance(base, (CheckoutBasePath, ResolvedBasePath)):
      raise ValueError(
          'First argument to Path must be CheckoutBasePath or ResolvedBasePath, '
          f'got {base!r} ({type(base)!r})')

    # If they gave us a CheckoutBasePath, but it's already resolvable,
    # immediately transmute it into a ResolvedBasePath.
    if isinstance(base, CheckoutBasePath):
      if resolved_path := base.maybe_resolve():
        base = resolved_path.base
        pieces = resolved_path.pieces + tuple(pieces)

    has_backslashes: bool = False
    for i, piece in enumerate(pieces):
      if not isinstance(piece, str):
        raise ValueError('Variadic arguments to Path must only be `str`, '
                         f'argument {i} was {piece!r} ({type(piece)!r})')
      has_backslashes = has_backslashes or '\\' in piece

    # NOTE: we always separate on '/', regardless of _OS_SEP, as users like to
    # pass pieces to Path constructors and join() which contain a slash already
    # (but almost never pass them with '\\').
    #
    # However, if they make a path, using backslash in pieces, during GenTests,
    # we can't tell if these should be separated or not and so raise a ValueError.
    if self._OS_SEP is None and has_backslashes:
      raise ValueError(
          f'Cannot instantiate Path({base!r}, {pieces!r}) - Pieces contain'
          ' backslash and recipe_engine/path has not been initialized yet.'
          ' Please use "/" (even for windows) or pass the pieces to join'
          ' separately.')
    need_backslash_split = has_backslashes and self._OS_SEP == '\\'

    normalized_pieces = []
    for piece in pieces:
      slash_pieces = piece.split('/')
      if need_backslash_split:
        new_slash_pieces = []
        for sp in slash_pieces:
          new_slash_pieces.extend(sp.split(self._OS_SEP))
        slash_pieces = new_slash_pieces
      normalized_pieces.extend(p for p in slash_pieces if p and p != '.')

    # At this point normalized_pieces is pieces but where:
    #   * All pieces have been split by / and/or \ - there are no more
    #   splittable slashes in normalized_pieces.
    #   * All empty pieces (which are '' or '.' pieces) have been removed.

    # Next, we normalize '..' passed in - This is allowed as long as it can be
    # fully resolved within the given pieces. Otherwise we'll raise an exception
    # if a joined '..' would take us above the base of this Path.
    #
    # Note that we start i at 1 and not 0: if pieces[0] == '..', this will be
    # caught in the next check section.
    i = 1
    while 0 < i < len(normalized_pieces):
      piece = normalized_pieces[i]
      if piece == '..':
        # At this point normalized_pieces looks like:
        #    'previous'  'something' '..'  'other' 'things'
        #    i-2        [i-1         i   ] i+1     i+2
        #
        # The [section] is the items in [i-1:i+1] (this syntax is a half-open
        # range). Assigning `[]` to this range will remove the previous element,
        # and also the '..'. This shifts the list to now be:
        #    'previous' 'other' 'things'
        #    i-2        i-1     i
        #
        # Which means that we need to decrement i by one to evaluate 'other',
        # which is the next item to analyze.
        normalized_pieces[i - 1:i + 1] = []
        i -= 1
      else:
        i += 1

    # Finally, check to see if any '..' was left over and raise.
    if normalized_pieces and normalized_pieces[0] == '..':
      raise ValueError(
          f'Unable to compute {base!r} / {pieces!r} without going above the base.'
      )

    # This is a frozen dataclass, so we have to assign using object.__setattr__.
    # Believe it or not, this is actually documented in
    # https://docs.python.org/3.11/library/dataclasses.html#frozen-instances
    object.__setattr__(self, 'base', base)
    object.__setattr__(self, 'pieces', tuple(normalized_pieces))

  @property
  def parents(self) -> Generator[Path, None, None]:
    """For 'foo/bar/baz', yield 'foo/bar' then 'foo'."""
    result: list[Path] = []
    prev: Path = self
    curr: Path = self.parent
    while prev != curr:
      yield curr
      prev, curr = curr, curr.parent

  @property
  def parent(self) -> Path:
    """For 'foo/bar/baz', return 'foo/bar'."""
    return Path(self.base, *self.pieces[0:-1])

  @property
  def name(self) -> str:
    """For 'foo/bar/baz', return 'baz'."""
    return self.pieces[-1]

  @property
  def stem(self) -> str:
    """For 'dir/foo.tar.gz', return 'foo.tar'."""
    return self.name.rsplit('.', 1)[0]

  @property
  def suffix(self) -> str:
    """For 'dir/foo.tar.gz', return '.gz'."""
    parts = self.name.rsplit('.', 1)
    if len(parts) == 1:
      return ''
    return '.' + parts[1]

  @property
  def suffixes(self) -> str:
    """For 'dir/foo.tar.gz', return ['.tar', '.gz']."""
    return [f'.{x}' for x in self.name.split('.')[1:]]

  def _resolve(self) -> Path:
    """If self.base is a ResolvedBasePath, this will return self.

    Otherwise, this will resolve self.base and return an equivalent path to
    `self` but with a ResolvedBasePath base. If CheckoutBasePath is
    unresolvable, this raises ValueError.
    """
    if not isinstance(self.base, CheckoutBasePath):
      return self
    return self.base.resolve().joinpath(*self.pieces)

  def __eq__(self, other: object) -> bool:
    if isinstance(other, str):
      return str(self) == other
    if not isinstance(other, Path):
      return NotImplemented

    # first, if both bases are checkout, just compare pieces, since we know that
    # CheckoutBasePath, once assigned, will always match.
    if (isinstance(self.base, CheckoutBasePath) and
        isinstance(other.base, CheckoutBasePath)):
      return self.pieces == other.pieces

    try:
      spath = self._resolve()
      opath = other._resolve()
      return spath.base == opath.base and spath.pieces == opath.pieces
    except Exception as ex:
      raise ValueError('Path.__eq__ invalid for mismatched bases '
                       '(CheckoutBasePath vs ResolvedBasePath) '
                       'before checkout_dir is set') from ex

  def __lt__(self, other: object) -> bool:
    if isinstance(other, str):
      return str(self) < other
    if not isinstance(other, Path):
      return NotImplemented

    # first, if both bases are checkout, just compare pieces, since we know that
    # CheckoutBasePath, once assigned, will always match.
    if (isinstance(self.base, CheckoutBasePath) and
        isinstance(other.base, CheckoutBasePath)):
      return self.pieces < other.pieces
    try:
      spath = self._resolve()
      opath = other._resolve()
      return (spath.base, spath.pieces) < (opath.base, opath.pieces)
    except Exception as ex:
      raise ValueError('Path.__lt__ invalid for mismatched bases '
                       '(CheckoutBasePath vs ResolvedBasePath) '
                       'before checkout_dir is set') from ex

  def __truediv__(self, piece: str | Path) -> Path:
    """Adds the shorthand '/'-operator for .joinpath(), returning a new path."""
    return self.joinpath(piece)

  def joinpath(self, *pieces: str | Path) -> Path:
    """Appends *pieces to this Path, returning a new Path.

    Empty values ('', None) in pieces will be omitted.

    Args:
      pieces: The components of the path relative to base. If a component is a
        Path instance, the returned path will be equivalent to calling joinpath
        on that component with any following components. The normal Path
        __init__ rules for '..' and '.' apply.

    Returns:
      The new Path.
    """
    if not pieces:
      return self
    for (i, p) in enumerate(pieces):
      if isinstance(p, Path):
        return p.joinpath(*pieces[i+1:])
    return Path(
        self.base,
        # Propagate None here so that accidental joins with None raise an error
        # rather than getting silently ignored
        *[p for p in itertools.chain(self.pieces, pieces) if p or p is None])

  def __str__(self) -> str:
    if self._str is None:
      if not self._OS_SEP:
        raise ValueError('Unable to render Path to string - '
                         'recipe_engine/path has not been initialized yet.')
      str_val = self._OS_SEP.join(itertools.chain((str(self.base),), self.pieces))
      object.__setattr__(self, '_str', str_val)
      return str_val
    return self._str

  def __repr__(self) -> str:
    # Try to resolve `self` - if it's rooted in CheckoutBasePath and
    # checkout_dir is already set, display the fully resolved path, since all
    # interactions with this Path will behave in that fashion.
    #
    # Otherwise, just use `self` as-is to allow repr(Path) to work in scenarios
    # where checkout_dir hasn't been set (for example, when reporting errors
    # involving unresolved checkout_dir paths...)
    try:
      spath = self._resolve()
    except ValueError:
      spath = self

    # NOTE: It would be good to switch to the dataclass-repr instead (or just
    # use __str__ all the time)
    s = 'Path(%r' % (spath.base,)
    if spath.pieces:
      s += ', %s' % ', '.join(repr(x) for x in spath.pieces)
    return s + ')'

  def __hash__(self) -> int:
    spath = self._resolve()
    return hash(('config_types.Path', spath.base, spath.pieces))

  def relative_to(self, other: Path, *, walk_up: bool = False) -> str:
    """Give one path relative to another.

    Examples:
      '[CACHE]/foo/bar'.relative_to('[CACHE]/foo') -> 'bar'
      '[CACHE]/foo/bar/baz'.relative_to('[CACHE]/foo') -> 'bar/baz'
      '[CACHE]/foo'.relative_to('[CACHE]/bar') -> ValueError
      '[CACHE]/foo'.relative_to('[CACHE]/bar', walk_up=True) -> '../foo'
      '[CACHE]/foo'.relative_to('[CACHE]/foo/bar/baz') -> ValueError
      '[CACHE]/foo'.relative_to('[CACHE]/foo/bar/baz', walk_up=True) -> '../..'
      '[CACHE]/foo'.relative_to('[CLEANUP]/bar') -> ValueError
      '[CACHE]/foo'.relative_to('[CLEANUP]/bar', walk_up=True) -> ValueError

    Assumes other is a directory.

    Args:
      other: Path to give self relative to.
      walk_up: Allow '..' in the return value.
    """
    if self.base != other.base:
      raise RelativeToDifferentBases(
          f'{self!r} and {other!r} have different bases')

    if not walk_up and other not in self.parents:
      raise RelativeToNotParent(
          f'{other!r} not in parents of {self!r} and walk_up=False')

    result = []

    for parent in itertools.chain([self], self.parents):
      if parent != other and parent not in other.parents:
        result.append(parent.name)

    for parent in itertools.chain([other], other.parents):
      if parent == self or parent in self.parents:
        break
      result.append('..')

    return '/'.join(reversed(result))
