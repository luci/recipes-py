#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import cStringIO
import unittest

import test_env

from recipe_engine import stream

class StreamTest(unittest.TestCase):
  def _example(self, engine):
    foo = engine.make_step_stream('foo')
    foo.write_line('foo says hello to xyrself')

    bar = engine.make_step_stream('bar')
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

    # TODO(luqui): N.B. stream interleaving is not really possible with
    # subannotations, since the subannotator stream could have changed the
    # active step.  To do this right we would need to parse and re-emit
    # subannotations.
    bars_baby = engine.make_step_stream(
        'bar\'s baby',
        allow_subannotations=True,
        step_nest_level=1)
    bars_baby.write_line('I\'m in bar\'s imagination!!')
    bars_baby.write_line('@@@STEP_WARNINGS@@@')
    bars_baby.reset_subannotation_state()
    bars_baby.close()

    bar.set_build_property('is_babycrazy', 'true')
    bar.write_line('bar tries to kiss foo, but foo already left')
    bar.write_line('@@@KISS@foo@@@')
    bar.set_step_status('EXCEPTION')
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
@@@SEED_STEP@bar's baby@@@
@@@STEP_CURSOR@bar's baby@@@
@@@CURRENT_TIMESTAMP@123@@@
@@@STEP_STARTED@@@
@@@STEP_NEST_LEVEL@1@@@
I'm in bar's imagination!!
@@@STEP_WARNINGS@@@
@@@STEP_CURSOR@bar's baby@@@
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
    engine = stream.AnnotatorStreamEngine(
        stringio, emit_timestamps=True, time_fn=self.fake_time)
    with engine:
      self._example(engine)
      # Split lines for good diffs.
    self.assertEqual(
        stringio.getvalue().splitlines(),
        self._example_annotations().splitlines())

  def test_example_wellformed(self):
    with stream.StreamEngineInvariants() as engine:
      self._example(engine)

  def test_product_with_invariants_on_example(self):
    stringio = cStringIO.StringIO()
    engine = stream.StreamEngineInvariants.wrap(
        stream.AnnotatorStreamEngine(
            stringio, emit_timestamps=True, time_fn=self.fake_time))
    with engine:
      self._example(engine)
    self.assertEqual(stringio.getvalue(), self._example_annotations())

  def test_noop(self):
    with stream.NoopStreamEngine() as engine:
      self._example(engine)

  def test_write_after_close(self):
    with stream.StreamEngineInvariants() as engine:
      foo = engine.make_step_stream('foo')
      foo.close()
      with self.assertRaises(AssertionError):
        foo.write_line('no')

  def test_log_still_open(self):
    with stream.StreamEngineInvariants() as engine:
      foo = engine.make_step_stream('foo')
      log = foo.new_log_stream('log')
      with self.assertRaises(AssertionError):
        foo.close()

  def test_no_write_multiple_lines(self):
    with stream.StreamEngineInvariants() as engine:
      foo = engine.make_step_stream('foo')
      with self.assertRaises(AssertionError):
        foo.write_line('one thing\nand another!')

  def test_invalid_status(self):
    with stream.StreamEngineInvariants() as engine:
      foo = engine.make_step_stream('foo')
      with self.assertRaises(AssertionError):
        foo.set_step_status('SINGLE')

  def test_buildbot_status_constraint(self):
    with stream.StreamEngineInvariants() as engine:
      foo = engine.make_step_stream('foo')
      foo.set_step_status('FAILURE')
      with self.assertRaises(AssertionError):
        foo.set_step_status('SUCCESS')

  def test_content_assertions(self):
    with stream.StreamEngineInvariants() as engine:
      with self.assertRaises(ValueError):
        engine.make_step_stream('foo\nbar')

      # Test StepStream.
      s = engine.make_step_stream('foo')
      with self.assertRaises(ValueError):
        s.new_log_stream('foo\nbar')
      ls = s.new_log_stream('foo')

      with self.assertRaises(ValueError):
        s.add_step_text('foo\nbar')
      s.add_step_text('foo')

      with self.assertRaises(ValueError):
        s.add_step_summary_text('foo\nbar')
      s.add_step_summary_text('foo')

      with self.assertRaises(ValueError):
        s.add_step_link('foo\nbar', 'baz')
      with self.assertRaises(ValueError):
        s.add_step_link('foo', 'bar\nbaz')
      s.add_step_link('foo', 'bar')

      with self.assertRaises(ValueError):
        s.set_build_property('foo\nbar', 'true')
      with self.assertRaises(ValueError):
        s.set_build_property('foo', 'true\n')
      with self.assertRaises(ValueError):
        s.set_build_property('foo', 'NOT JSON')
      s.set_build_property('foo', '"Is JSON"')

      with self.assertRaises(ValueError):
        s.trigger('true\n')
      with self.assertRaises(ValueError):
        s.trigger('NOT JSON')
      s.trigger('"Is JSON"')

      ls.close()
      s.close()


if __name__ == '__main__':
  unittest.main()
