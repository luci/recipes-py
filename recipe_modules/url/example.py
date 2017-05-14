# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'context',
  'path',
  'step',
  'url',
]

# NOTE: These examples *probably work*. They're not run as part of regular
# production testing, but they do access live resources that are available
# and functional at the time of writing this.
#
# If this test actually fails, please adjust the URLs to achieve the same
# effect.
TEST_HTTPS_URL = 'https://chromium.org'
TEST_HTTP_URL = 'http://chromium.org'
TEST_ERROR_URL = 'http://httpstat.us/500'
TEST_JSON_URL = 'https://chromium.googlesource.com/infra/infra?format=JSON'
TEST_BAD_CERTS = [
    'https://wrong.host.badssl.com/',
    'https://expired.badssl.com/',
]

def RunSteps(api):
  assert api.url.quote('~foo') == '%7Efoo'
  assert api.url.urlencode({'foo': 'bar'}) == 'foo=bar'

  # get_file
  dest = api.path['start_dir'].join('download.bin')
  v = api.url.get_file(TEST_HTTPS_URL, dest,
                       headers={'Authorization': 'thing'})
  assert str(v.output) == str(dest)

  # get_text (HTTP)
  v = api.url.get_text(TEST_HTTP_URL, default_test_data='will be overridden')
  assert v.method == 'GET'
  assert 'The Chromium Projects' in v.output
  assert v.size == len(v.output)
  assert v.status_code == 200

  v = api.url.get_text(TEST_HTTP_URL, default_test_data='The Chromium Projects')
  assert 'The Chromium Projects' in v.output
  assert v.size == len(v.output)
  assert v.status_code == 200

  # get_json (HTTPS)
  v = api.url.get_json(TEST_JSON_URL, log=True,
      strip_prefix=api.url.GERRIT_JSON_PREFIX)
  assert isinstance(v.output, dict)
  assert v.status_code == 200

  v = api.url.get_json(TEST_JSON_URL,
      strip_prefix=api.url.GERRIT_JSON_PREFIX,
      default_test_data={'pants': 'shirt'})
  assert isinstance(v.output, dict)
  assert v.status_code == 200

  # Check error conditions.
  def raises(fn, exc):
    raised = None
    try:
      fn()
    except exc as e:
      raised = e
    assert raised, 'Did not raise [%s]' % (exc,)
    return raised

  def test_error():
    api.url.get_text(TEST_ERROR_URL, step_name='error', transient_retry=4)
  exc = raises(test_error, api.url.HTTPError)
  assert exc.response.error_body == '500 Internal Server Error'

  def test_infra_error():
    with api.context(infra_steps=True):
      api.url.get_text(TEST_ERROR_URL, step_name='infra error',
                       transient_retry=False)
  exc = raises(test_infra_error, api.url.InfraHTTPError)
  assert exc.response.error_body == '500 Internal Server Error'

  def test_auth_over_http():
    api.url.get_text('http://foo/bar/text/error',
                     headers={'Authorization': 'SECRET'})
  raises(test_auth_over_http, ValueError)

  for bad_cert in TEST_BAD_CERTS:
    def test_bad_cert():
      api.url.get_text(bad_cert)
    raises(test_bad_cert, api.step.StepFailure)


def GenTests(api):
  def get(url):
    return 'GET %s' % (url,)

  test = (
      api.test('basic') +
      api.url.text(get(TEST_HTTP_URL), '<html>The Chromium Projects</html>') +
      api.url.json(get(TEST_JSON_URL), {'is_json': True}) +

      api.url.error('error', 500, body='500 Internal Server Error') +
      api.url.error('infra error', 500, body='500 Internal Server Error')
  )
  for bad_cert in TEST_BAD_CERTS:
    test += api.step_data('GET ' + bad_cert, retcode=1)
  yield test
