# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'assertions',
  'cq',
  'step',
]


def RunSteps(api):
  api.step('disallow reuse only for full run', cmd=None)
  api.assertions.assertFalse(api.cq.allowed_reuse_mode_regexps)
  with api.assertions.assertRaises(ValueError):
    api.cq.allow_reuse_for()  # must provide mode_regex
  with api.assertions.assertRaises(ValueError):
    api.cq.allow_reuse_for('+')  # invalid regex
  api.cq.allow_reuse_for(api.cq.QUICK_DRY_RUN)
  api.assertions.assertListEqual(api.cq.allowed_reuse_mode_regexps,
                                 [api.cq.QUICK_DRY_RUN,])
  api.cq.allow_reuse_for(api.cq.DRY_RUN, api.cq.FULL_RUN)
  api.assertions.assertListEqual(api.cq.allowed_reuse_mode_regexps,
                                 [api.cq.DRY_RUN, api.cq.FULL_RUN])


def GenTests(api):
  yield api.test('example')
