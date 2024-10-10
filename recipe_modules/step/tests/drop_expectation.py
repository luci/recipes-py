# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

# This is not really a test of the step module, but it's the most convenient
# way to test DropExpectations.

from recipe_engine import post_process

DEPS = [
  'step',
]


def RunSteps(api):
  with api.step.nest('abc'):
    api.step.empty('def')
  with api.step.nest('abcdef'):
    api.step.empty('ghi')
  api.step.empty('abc.de.f')


def GenTests(api):
  yield api.test(
      'one-arg',
      api.post_process(post_process.MustRun, 'abc'),
      api.post_process(post_process.MustRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc.de'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc.de.f'),
      api.post_process(post_process.DoesNotRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'multiple-args',
      api.post_process(post_process.MustRun, 'abc'),
      api.post_process(post_process.MustRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation, 'abc', 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc.def'),
      api.post_process(post_process.DoesNotRun, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-args',
      api.post_process(post_process.MustRun, 'abc'),
      api.post_process(post_process.MustRun, 'abc.def'),
      api.post_process(post_process.MustRun, 'abcdef'),
      api.post_process(post_process.MustRun, 'abcdef.ghi'),
      api.post_process(post_process.MustRun, 'abc.de.f'),
      api.post_process(post_process.DropExpectation),
      api.post_process(post_process.DoesNotRun, 'abc'),
      api.post_process(post_process.DoesNotRun, 'abc.def'),
      api.post_process(post_process.DoesNotRun, 'abcdef'),
      api.post_process(post_process.DoesNotRun, 'abcdef.ghi'),
      api.post_process(post_process.DoesNotRun, 'abc.de.f'),
  )
