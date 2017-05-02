#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function, absolute_import

from . import env

from . import doc_pb2 as doc

# These are modes for Printer
GITHUB = 'github'
GITILES = 'gitiles'


class Printer(object):
  def __init__(self, mode):
    assert mode in (GITHUB, GITILES), mode

    self.mode = mode
    self._url_mode = None
    self._url = None
    self._current_package = None
    self._known_objects = None

  @property
  def url(self):
    return self._url

  @url.setter
  def url(self, v):
    self._url = v
    self._url_mode = GITHUB if 'github.com/' in v else GITILES

  @property
  def current_package(self):
    return self._current_package

  @current_package.setter
  def current_package(self, v):
    self._current_package = v

  @property
  def known_objects(self):
    return self._known_objects

  @known_objects.setter
  def known_objects(self, v):
    self._known_objects = v

  def __call__(self, *args, **kwargs):
    """Prints some text to the document. Behaves exactly like the builtin print
    function."""
    print(*args, **kwargs)

  def docstring(self, node):
    """Prints the docstring on the node (if any).

    In the future this will adjust the docstring to better fit in the overall
    document structure.
    """
    # TODO(iannucci): adjust section headers inside docstring to nest correctly.
    # Maybe fix up links too?
    if node.docstring:
      self()
      self(node.docstring)

  @staticmethod
  def generic_link(name, url):
    """Returns a markdown link for the name,url pair."""
    name = name.replace('_', '\_')
    return "[%s](%s)" % (name, url)

  def link(self, node, name=None, relpath=None, lineno=None):
    """Links to the source for a given documentation node.

    Node is duck-typed, and will be probed for:
      name (str) - the name of the link
      relpath (str) - the relative path from the repo root to this node's file.
      lineno (int, optional) - the line number in the source

    All of these values may be provided/overridden in the kwargs, in which case
    node will not be probed for that particular value.

    This understands how to link to either github or gitiles, regardless of the
    flavor of markdown we're targetting (since the source links depend solely on
    on the canonical_repo_url).
    """
    if not self._url:
      raise ValueError("unset url")

    if name is None:
      name = getattr(node, 'name')
    if relpath is None:
      relpath = getattr(node, 'relpath')
    if lineno is None:
      lineno = getattr(node, 'lineno', None)

    if relpath:
      # TODO(iannucci): pin these to the revisions in the recipes.cfg file.
      if self._url_mode == GITHUB:
        url = '/'.join((self._url, 'tree/master', relpath))
        if lineno:
          url += '#L%d' % lineno
      else:
        url = '/'.join((self._url, '+/master', relpath))
        if lineno:
          url += '#%d' % lineno
    else:
      url = self._url

    return self.generic_link(name, url)

  def anchorlink(self, pkgname, name, prefix=None):
    anchor = name
    if self.mode == GITILES:
      if prefix is not None:
        anchor = '%s-%s' % (prefix, anchor)
      replacement = '_'
    else:
      if prefix is not None:
        anchor = '%s--%s' % (prefix, anchor)
      replacement = ''

    anchor = anchor.replace(' ', '-')

    for c in '/:':
      anchor = anchor.replace(c, replacement)
    if self.mode == GITHUB:
      anchor = anchor.lower()

    if pkgname == self.current_package:
      return "[%s](#%s)" % (name, anchor)

    return "[%s](./%s.md#%s)" % (name, pkgname, anchor)

  def modlink(self, pkgname, name):
    """Returns a link to the generated markdown for a recipe module."""
    return self.anchorlink(pkgname, name, 'recipe_modules')

  def recipelink(self, pkgname, name):
    """Returns a link to the generated markdown for a recipe."""
    return self.anchorlink(pkgname, name, 'recipes')

  def objlink(self, obj):
    """Returns a markdown link to a well-known object `obj`"""
    if obj.generic:
      return str(obj.generic)
    else:
      obj = self.known_objects[obj.known]
      return self.link(getattr(obj, obj.WhichOneof('kind')))

  def toc(self, section_name, section_map):
    if section_map:
      self()
      self('**%s**' % (self.anchorlink(self.current_package, section_name),))
      for name, mod in sorted(section_map.items()):
        link = self.anchorlink(self.current_package, name,
                               section_name.replace(' ', '_'))
        if mod.docstring:
          first_line = mod.docstring.split('.', 1)[0].replace('\n', ' ')+'.'
          self('  * %s &mdash; %s' % (link, first_line))
        else:
          self('  * %s' % (link,))


def Emit(p, node):
  assert isinstance(p, Printer)

  if isinstance(node, doc.Doc.Recipe):
    p("### *recipes* /", p.link(node))

    Emit(p, node.deps)

    # TODO(iannucci): PARAMETERS
    # TODO(iannucci): RETURN_SCHEMA

    p.docstring(node)

    for _, func in sorted(node.funcs.items()):
      Emit(p, func)

  elif isinstance(node, doc.Doc.Package):
    # TODO(iannucci): this is a bit hacky. Maybe these should be set on p before
    # calling Emit?
    p.current_package = node.spec.project_id
    p.url = node.spec.canonical_repo_url
    p.known_objects = node.known_objects

    p('# Package documentation for', p.generic_link(
      node.spec.project_id, p.url))

    p.docstring(node)

    p('## Table of Contents')
    p.toc('Recipe Modules', node.recipe_modules)
    p.toc('Recipes', node.recipes)

    if node.recipe_modules:
      p("## Recipe Modules")
      p()
      for _, mod in sorted(node.recipe_modules.items()):
        Emit(p, mod)

    if node.recipes:
      p("## Recipes")
      p()
      for _, mod in sorted(node.recipes.items()):
        Emit(p, mod)

  elif isinstance(node, doc.Doc.Module):
    p("### *recipe_modules* /", p.link(node))

    Emit(p, node.deps)

    # TODO(iannucci): PARAMETERS

    p.docstring(node)

    Emit(p, node.api_class)

    # TODO(iannucci): classes

    # TODO(iannucci): funcs

  elif isinstance(node, doc.Doc.Deps):
    if node.module_links:
      p()
      links = [p.modlink(n.package, n.name) for n in node.module_links]
      p(p.link(node, name="DEPS")+":", ', '.join(links))

  elif isinstance(node, doc.Doc.Class):
    p()
    bases = [p.objlink(b) for b in node.bases]
    p('#### **class %s(%s):**' % (
      p.link(node), ', '.join(bases)))

    p.docstring(node)

    # TODO(iannucci): inner classes

    for _, func in sorted(node.funcs.items()):
      Emit(p, func)

  elif isinstance(node, doc.Doc.Func):
    p()
    decos = '<br>'.join([
      "&emsp; **@%s**" % p.objlink(d)
      for d in node.decorators
    ])
    if decos:
      decos += '<br>'
    p("%s&mdash; **def %s(%s):**" % (
      decos, p.link(node), node.signature.replace('*', '\*')))

    p.docstring(node)

  else:
    raise TypeError("don't know how to render markdown for %r"
                    % type(node).__name__)
