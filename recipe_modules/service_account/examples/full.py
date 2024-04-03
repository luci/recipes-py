# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
  'platform',
  'properties',
  'raw_io',
  'service_account',
  'path',
]

PROPERTIES = {
  'key_path': Property(),
  'scopes': Property(),
}


def RunSteps(api, key_path, scopes):
  if key_path:
    account = api.service_account.from_credentials_json(key_path)
    assert account.key_path == key_path
  else:
    account = api.service_account.default()
  account.get_access_token(scopes)
  account.get_id_token("http://www.example.com")


def GenTests(api):
  def props(key_path=None, scopes=None):
    return api.properties.generic(
        key_path=key_path,
        scopes=scopes)

  yield api.test(
      'default',
      api.platform('linux', 64),
      props(),
  )

  yield api.test(
      'windows',
      api.platform('win', 64),
      props(),
  )

  yield api.test(
      'json_key',
      api.platform('linux', 64),
      props(key_path=api.path['start_dir'].join('key_name.json')),
  )

  yield api.test(
      'custom_scopes',
      api.platform('linux', 64),
      props(scopes=['B', 'A']),
  )

  yield api.test(
      'no_authutil',
      api.platform('linux', 64),
      props(),
      api.step_data('get access token for default account', retcode=1),
      status='INFRA_FAILURE',
  )
