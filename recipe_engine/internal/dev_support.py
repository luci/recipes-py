# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Contains all logic w.r.t. the recipe engine's support for development
environments.

This includes generation of .recipe_deps/_dev folder, which includes:
  * python3 -> a symlink to the current virtualenv interpreter
  * typings -> a root folder for type stubs
"""

import os
import shutil
import sys
import tempfile


def ensure_typings(_):
  """Ensures that the .recipe_deps/_dev/typings directory is generated."""
  raise NotImplementedError("dev: typings")


def ensure_python3(deps):
  """Ensures that the .recipe_deps/_dev/python3 symlink is generated.

  No-op on windows.
  """
  if sys.platform.startswith('win32'):
    # Not supported on windows.
    #
    # If you're reading this and know how to make symlinking work in a pain-free
    # way on windows, please contact the owners of recipes :).
    return

  dev_dir = deps.recipe_deps_dev_path
  os.makedirs(dev_dir, exist_ok=True)

  py3_symlink = os.path.join(dev_dir, "python3")
  tmp_symlink_dir = tempfile.mkdtemp(suffix="python3_link", dir=dev_dir)
  try:
    tmp_symlink = os.path.join(tmp_symlink_dir, "python3")
    os.symlink(sys.executable, tmp_symlink)
    os.rename(tmp_symlink, py3_symlink)
  finally:
    shutil.rmtree(tmp_symlink_dir, ignore_errors=True)
