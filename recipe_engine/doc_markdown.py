#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function, absolute_import

from . import env

from . import doc_pb2 as doc


GITHUB, GITILES = range(2)

def markdown_flavor_for_url(url):
  """Returns either GITHUB or GITILES for the given URL to indicate which flavor
  of markdown is hosted at the URL."""
  if 'github' in url:
    return GITHUB
  return GITILES


class Printer(object):
  def __init__(self, outf):
    self._outf = outf
    self._url = None
    self._current_package = None
    self._known_objects = None
    self._specs = None

  @property
  def specs(self):
    return self._specs

  @specs.setter
  def specs(self, v):
    self._specs = v

  @property
  def url(self):
    return self._specs[self._current_package].canonical_repo_url

  @property
  def markdown_flavor(self):
    return markdown_flavor_for_url(self.url)

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

  def __call__(self, *args):
    """Prints some text to the document. Behaves exactly like the builtin print
    function."""
    print(*args, file=self._outf)

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

  def srclink(self, node, name=None, relpath=None, lineno=None, package=None):
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
    url, flavor = "", self.markdown_flavor
    if package is not None:
      url, _, flavor = self.baseurl(package)

    if name is None:
      name = getattr(node, 'name')
    if relpath is None:
      relpath = getattr(node, 'relpath')
    if lineno is None:
      lineno = getattr(node, 'lineno', None)

    if relpath:
      url += '/'+relpath
      if lineno:
        if flavor == GITHUB:
          url += '#L%d' % lineno
        else:
          url += '#%d' % lineno
    else:
      url += '/'

    return self.generic_link(name, url)

  @staticmethod
  def anchor(flavor, name, prefix=None):
    anchor = name
    if flavor == GITILES:
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
    if flavor == GITHUB:
      anchor = anchor.lower()
    return anchor

  def anchorlink(self, name, prefix=None):
    anchor = self.anchor(self.markdown_flavor, name, prefix)
    return "[%s](#%s)" % (name, anchor)

  def baseurl(self, pkgname):
    if pkgname == self.current_package:
      return '', self.specs[pkgname].recipes_path, self.markdown_flavor

    s = self.specs[pkgname]
    r = self.specs[self.current_package].deps[pkgname].revision
    url = s.canonical_repo_url
    flavor = markdown_flavor_for_url(url)
    if flavor == GITHUB:
      url += '/blob/%s' % r
    else:
      url += '/+/%s' % r
    return url, s.recipes_path, flavor

  def readmeurl(self, pkgname):
    if pkgname == self.current_package:
      return '', self.markdown_flavor

    url, recipes_path, flavor = self.baseurl(pkgname)
    if recipes_path:
      url += '/%s' % recipes_path
    url += '/README.recipes.md'
    return url, flavor

  def modlink(self, pkgname, name):
    """Returns a link to the generated markdown for a recipe module."""
    url, flavor = self.readmeurl(pkgname)
    url += '#' + self.anchor(flavor, name, 'recipe_modules')
    return '[%s](%s)' % (name, url)

  def objlink(self, obj):
    """Returns a markdown link to a well-known object `obj`"""
    if obj.generic:
      return str(obj.generic)
    else:
      # TODO(iannucci): link to a generated markdown doc, not directly to
      # source.
      obj = self.known_objects[obj.known]
      return self.srclink(getattr(obj, obj.WhichOneof('kind')),
                          package='recipe_engine')

  def toc(self, section_name, section_map):
    if section_map:
      self()
      self('**%s**' % (self.anchorlink(section_name),))
      for name, mod in sorted(section_map.items()):
        link = self.anchorlink(name,
                               section_name.replace(' ', '_').lower())
        if mod.docstring:
          first_line = mod.docstring.split('.', 1)[0].replace('\n', ' ')+'.'
          self('  * %s &mdash; %s' % (link, first_line))
        else:
          self('  * %s' % (link,))


def Emit(p, node):
  assert isinstance(p, Printer)

  if isinstance(node, doc.Doc.Recipe):
    p("### *recipes* /", p.srclink(node))

    Emit(p, node.deps)

    # TODO(iannucci): PARAMETERS
    # TODO(iannucci): RETURN_SCHEMA

    p.docstring(node)

    for _, func in sorted(node.funcs.items()):
      Emit(p, func)

  elif isinstance(node, doc.Doc.Package):
    p.current_package = node.project_id
    p.specs = node.specs
    p.known_objects = node.known_objects

    p('<!--- AUTOGENERATED BY `./recipes.py test train` -->')
    p('# Package documentation for', p.generic_link(
      node.project_id, p.url))

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
    p("### *recipe_modules* /", p.srclink(node))

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
      p(p.srclink(node, name="DEPS")+":", ', '.join(links))

  elif isinstance(node, doc.Doc.Class):
    p()
    bases = [p.objlink(b) for b in node.bases]
    p('#### **class %s(%s):**' % (
      p.srclink(node), ', '.join(bases)))

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
      decos, p.srclink(node), node.signature.replace('*', '\*')))

    p.docstring(node)

  else:
    raise TypeError("don't know how to render markdown for %r"
                    % type(node).__name__)
