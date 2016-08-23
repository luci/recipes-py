# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Sets up recipe engine Python environment."""

import contextlib
import os
import sys

# Hook up our third party vendored packages.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIRD_PARTY = os.path.join(BASE_DIR, 'recipe_engine', 'third_party')

# Real path manipulation.
sys.path = [
    os.path.join(THIRD_PARTY),
    os.path.join(THIRD_PARTY, 'requests'),
    os.path.join(THIRD_PARTY, 'six'),
    os.path.join(THIRD_PARTY, 'client-py'),
    os.path.join(THIRD_PARTY, 'mock-1.0.1'),
] + sys.path

# Hack up our "pkg_resources" to import our local protobuf instead of the system
# one.
#
# As per https://github.com/google/protobuf/issues/1484:
# The protobuf library is meant to be installed. It is either a system library
# or a virtualenv library, but not something you can just point "sys.path" to
# anymore ... well, not without hacks.
#
# Ideally we'd run recipe engine in its own virtualenv and make this happen. In
# the meantime, we will go through the following ritual to ensure that our
# protobuf package is preferred.
#
# We need to:
# a) Load pkg_resources from third_party.
# b) Ensure that our protobuf is the only element in sys.path. This causes it
#    to cache it as the only option, rather than preferring the system library.
# c) Build our standard first-is-preferred path for the remainder of the
#    engine.
@contextlib.contextmanager
def temp_sys_path():
  orig_path = sys.path[:]
  try:
    yield
  finally:
    sys.path = orig_path

import pkg_resources
with temp_sys_path():
  # In a temporary environment where "sys.path" consists solely of our
  # "third_party" directory, register the google namespace. By restricting the
  # options in "sys.path", "pkg_resources" will not cache or prefer system
  # resources for this namespace or its derivatives.
  sys.path = [THIRD_PARTY]

  # Remove module if there is preloaded 'google' module
  sys.modules.pop('google', None)

  pkg_resources.declare_namespace('google')
  pkg_resources.fixup_namespace_packages(THIRD_PARTY)

# From here on out, we're back to normal imports. Let's assert that the we're
# using the correct protobuf package, though.
#
# We use "realpath" here because the importer may resolve the path differently
# based on symlinks, and we want to make sure our calculated path matches the
# impoter's path regardless.
import google.protobuf
assert (os.path.realpath(THIRD_PARTY) in
        os.path.realpath(google.protobuf.__path__[0]))
