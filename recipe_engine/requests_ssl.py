# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os

from . import env
import requests


ENV_VAR_IGNORE = 'RECIPE_ENGINE_IGNORE_SSL'
_CHECKED = False
def check_requests_ssl():
  global _CHECKED
  if _CHECKED or os.environ.get(ENV_VAR_IGNORE):
    return

  try:
    from requests.packages.urllib3.contrib import pyopenssl
    pyopenssl.inject_into_urllib3()
  except ImportError:
    print (
        'WARNING: You do not have proper SSL libraries installed for python. '
        'You may be at risk for man in the middle attacks. Installing '
        'pyOpenSSL (see https://urllib3.readthedocs.io/en/latest/user-guide.'
        'html#ssl-py2 for more details), or using the recipe engine '
        '`--use-bootstrap` flag will ensure proper python SSL libraries.'
    )
    from requests.packages import urllib3
    # TODO(martiniss): Make this mandatory by default, once chrome-infra is
    # using proper python SSL libraries.
    urllib3.disable_warnings()

  _CHECKED = True

def disable_check():
  """Disables ssl check. ONLY USE FOR TESTING."""
  global _CHECKED
  _CHECKED = True
