# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.service_account.examples import full as full_pb

DEPS = [
  'platform',
  'properties',
  'raw_io',
  'service_account',
  'path',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  string key_path = 1;
  repeated string scopes = 2;
}
"""

PROPERTIES = full_pb.InputProperties


def RunSteps(api, props: full_pb.InputProperties):
  if props.key_path:
    account = api.service_account.from_credentials_json(props.key_path)
    assert account.key_path == props.key_path
  else:
    account = api.service_account.default()
  account.get_access_token(props.scopes)
  account.get_id_token("http://www.example.com")


def GenTests(api):
  def props(key_path='', scopes=None):
    return api.properties(full_pb.InputProperties(
        key_path=key_path,
        scopes=scopes))

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
      props(key_path='[START_DIR]/key_name.json'),
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
