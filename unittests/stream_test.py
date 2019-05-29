#!/usr/bin/env vpython
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import cStringIO

import test_env

from recipe_engine.internal.stream.annotator import AnnotatorStreamEngine
from recipe_engine.internal.stream.invariants import StreamEngineInvariants


class StreamTest(test_env.RecipeEngineUnitTest):
  def _example(self, engine):
    foo = engine.new_step_stream(('foo',), False)
    foo.write_line('foo says hello to xyrself')

    bar = engine.new_step_stream(('bar',), False)
    foo.write_split('foo says hello to bar:\n  hi bar')
    bar.write_line('bar says hi, shyly')

    foo.write_line('foo begins to read a poem')
    with foo.new_log_stream('poem/proposition') as poem:
      poem.write_line('bar, thoust art soest beautiful')
      bar.add_step_text('*blushing*')
      poem.write_line('thoust makest mine heartst goest thumpitypump..est')

    foo.add_step_link('read it online!', 'https://foospoemtobar.com/')
    foo.add_step_summary_text('read a killer poem and took a bow')
    foo.trigger('{"builderName":["bar\'s fantasies"]}')
    foo.close()

    bar.set_build_property('is_babycrazy', 'true')
    bar.write_line('bar tries to kiss foo, but foo already left')
    bar.write_line('@@@KISS@foo@@@')
    bar.set_step_status('EXCEPTION', had_timeout=False)
    bar.close()

  def _example_annotations(self):
    return """@@@CURRENT_TIMESTAMP@123@@@
@@@HONOR_ZERO_RETURN_CODE@@@
@@@SEED_STEP@foo@@@
@@@STEP_CURSOR@foo@@@
@@@CURRENT_TIMESTAMP@123@@@
@@@STEP_STARTED@@@
foo says hello to xyrself
@@@SEED_STEP@bar@@@
foo says hello to bar:
  hi bar
@@@STEP_CURSOR@bar@@@
@@@CURRENT_TIMESTAMP@123@@@
@@@STEP_STARTED@@@
bar says hi, shyly
@@@STEP_CURSOR@foo@@@
foo begins to read a poem
@@@STEP_LOG_LINE@poem&#x2f;proposition@bar, thoust art soest beautiful@@@
@@@STEP_CURSOR@bar@@@
@@@STEP_TEXT@*blushing*@@@
@@@STEP_CURSOR@foo@@@
@@@STEP_LOG_LINE@poem&#x2f;proposition@thoust makest mine heartst goest thumpitypump..est@@@
@@@STEP_LOG_END@poem&#x2f;proposition@@@
@@@STEP_LINK@read it online!@https://foospoemtobar.com/@@@
@@@STEP_SUMMARY_TEXT@read a killer poem and took a bow@@@
@@@STEP_TRIGGER@{"builderName":["bar's fantasies"]}@@@
@@@CURRENT_TIMESTAMP@123@@@
@@@STEP_CLOSED@@@
@@@STEP_CURSOR@bar@@@
@@@SET_BUILD_PROPERTY@is_babycrazy@true@@@
bar tries to kiss foo, but foo already left
!@@@KISS@foo@@@
@@@STEP_EXCEPTION@@@
@@@CURRENT_TIMESTAMP@123@@@
@@@STEP_CLOSED@@@
@@@CURRENT_TIMESTAMP@123@@@
"""

  def fake_time(self):
    return 123

  def test_example(self):
    stringio = cStringIO.StringIO()
    engine = AnnotatorStreamEngine(
        stringio, emit_timestamps=True, time_fn=self.fake_time)
    with engine:
      self._example(engine)
      # Split lines for good diffs.
    self.assertEqual(
        stringio.getvalue().splitlines(),
        self._example_annotations().splitlines())

  def test_example_wellformed(self):
    with StreamEngineInvariants() as engine:
      self._example(engine)

  def test_product_with_invariants_on_example(self):
    stringio = cStringIO.StringIO()
    engine = StreamEngineInvariants.wrap(
        AnnotatorStreamEngine(
            stringio, emit_timestamps=True, time_fn=self.fake_time))
    with engine:
      self._example(engine)
    self.assertEqual(stringio.getvalue(), self._example_annotations())

  def test_write_after_close(self):
    with StreamEngineInvariants() as engine:
      foo = engine.new_step_stream(('foo',), False)
      foo.close()
      with self.assertRaises(AssertionError):
        foo.write_line('no')

  def test_log_still_open(self):
    with StreamEngineInvariants() as engine:
      foo = engine.new_step_stream(('foo',), False)
      log = foo.new_log_stream('log')
      with self.assertRaises(AssertionError):
        foo.close()

  def test_no_write_multiple_lines(self):
    with StreamEngineInvariants() as engine:
      foo = engine.new_step_stream(('foo',), False)
      with self.assertRaises(AssertionError):
        foo.write_line('one thing\nand another!')

  def test_invalid_status(self):
    with StreamEngineInvariants() as engine:
      foo = engine.new_step_stream(('foo',), False)
      with self.assertRaises(AssertionError):
        foo.set_step_status('SINGLE', had_timeout=False)

  def test_buildbot_status_constraint(self):
    with StreamEngineInvariants() as engine:
      foo = engine.new_step_stream(('foo',), False)
      foo.set_step_status('FAILURE', had_timeout=False)
      with self.assertRaises(AssertionError):
        foo.set_step_status('SUCCESS', had_timeout=False)


if __name__ == '__main__':
  test_env.main()
