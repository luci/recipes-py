# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import attr
import textwrap


@attr.s
class LUCIStepMarkdownWriter(object):
  _step_text = attr.ib(default='')
  def add_step_text(self, text):
    self._step_text += text

  _step_summary_text = attr.ib(default='')
  def add_step_summary_text(self, text):
    self._step_summary_text += text

  _step_links = attr.ib(factory=list)
  def add_step_link(self, linkname, link):
    self._step_links.append((linkname, link))

  def render(self):
    escape_parens = lambda link: link.replace('(', r'\(').replace(')', r'\)')

    paragraphs = []

    if self._step_summary_text:
      paragraphs.append(self._step_summary_text)

    if self._step_text:
      paragraphs.append(self._step_text)

    if self._step_links:
      paragraphs.append(
          '\n'.join(
              '  * [%s](%s)' % (name, escape_parens(link))
              for name, link in self._step_links))

    return '\n\n'.join(paragraphs)
