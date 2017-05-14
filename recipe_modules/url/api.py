# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import types
import urllib
import urlparse

from recipe_engine import recipe_api


class UrlApi(recipe_api.RecipeApi):
  quote = staticmethod(urllib.quote)
  urlencode = staticmethod(urllib.urlencode)

  # JSON prefix used with Gerrit and Gitiles.
  GERRIT_JSON_PREFIX = ")]}'\n"

  class HTTPError(recipe_api.StepFailure):
    def __init__(self, msg, response):
      super(UrlApi.HTTPError, self).__init__(msg)
      self.response = response


  class InfraHTTPError(recipe_api.InfraFailure):
    def __init__(self, msg, response):
      super(UrlApi.InfraHTTPError, self).__init__(msg)
      self.response = response


  # Status JSON output from "pycurl.py" resource.
  _PyCurlStatus = collections.namedtuple('_PyCurlStatus', (
      'status_code', 'success', 'size', 'error_body'))


  class Response(object):
    """Response is an HTTP response object."""

    def __init__(self, method, output, status, infra_step):
      self._method = method
      self._status = status
      self._output = output
      self._infra_step = infra_step

    @property
    def method(self):
      """Returns (str): The HTTP method, currently always GET."""
      return self._method

    @property
    def status_code(self):
      """Returns (int): The HTTP status code."""
      return self._status.status_code

    @property
    def output(self):
      """
      Returns:
        If JSON, the unmarshalled JSON response object.
        If text, the result as a text string.
        If file, the output Path.
        On error, will be None.
      """
      return self._output

    @property
    def error_body(self):
      """Returns the HTTP body when an error was encountered.

      Returns (str or None): The error body, or None if not an error.
      """
      return self._status.error_body

    @property
    def size(self):
      """Returns (int): The number of bytes in the HTTP response."""
      return self._status.size

    def raise_on_error(self):
      """Raises an exception if the HTTP operation was not successful.

      Raises:
        UrlApi.HTTPError on HTTP failure, if not an infra step.
        UrlApi.InfraHTTPError on HTTP failure, if an infra step.
      """
      if not self._status.success:
        cls = UrlApi.InfraHTTPError if self._infra_step else UrlApi.HTTPError
        raise cls('HTTP status (%d)' % (self.status_code,), self)


  def join(self, *parts):
    """Constructs a URL path from composite parts.

    Args:
      parts (str...): Strings to concastenate. Any leading or trailing slashes
          will be stripped from intermediate strings to ensure that they join
          together. Trailing slashes will not be stripped from the last part.
    """
    if parts:
      parts = list(parts)
      if len(parts) > 1:
        for i, p in enumerate(parts[:-1]):
          parts[i] = p.strip('/')
      parts[-1] = parts[-1].lstrip('/')
    return '/'.join(parts)

  def validate_url(self, v):
    """Validates that "v" is a valid URL.

    A valid URL has a scheme and netloc, and must begin with HTTP or HTTPS.

    Args:
      v (str): The URL to validate.

    Returns (bool): True if the URL is considered secure, False if not.

    Raises:
      ValueError: if "v" is not valid.
    """
    u = urlparse.urlparse(v)
    if u.scheme.lower() not in ('http', 'https'):
      raise ValueError('URL scheme must be either http:// or https://')
    if not u.netloc:
      raise ValueError('URL must specify a network location.')
    return u.scheme.lower() == 'https'

  def get_file(self, url, path, step_name=None, headers=None,
               transient_retry=True, strip_prefix=None, timeout=None):
    """GET data at given URL and writes it to file.

    Args:
      url: URL to request.
      path (Path): the Path where the content will be written.
      step_name: optional step name, 'fetch <url>' by default.
      headers: a {header_name: value} dictionary for HTTP headers.
      transient_retry (bool or int): Determines how transient HTTP errorts
          (>500) will be retried. If True (default), errors will be retried up
          to 10 times. If False, no transient retries will occur. If an integer
          is supplied, this is the number of transient retries to perform. All
          retries have exponential backoff applied.
      strip_prefix (str or None): If not None, this prefix must be present at
          the beginning of the response, and will be stripped from the resulting
          content (e.g., GERRIT_JSON_PREFIX).
      timeout: Timeout (see step.__call__).

    Returns (UrlApi.Response): Response with "path" as its "output" value.

    Raises:
      HTTPError, InfraHTTPError: if the request failed.
      ValueError: If the request was invalid.
    """
    return self._get_step(url, path, step_name, headers, transient_retry,
                          strip_prefix, False, timeout, '')

  def get_text(self, url, step_name=None, headers=None, transient_retry=True,
               timeout=None, default_test_data=None):
    """GET data at given URL and writes it to file.

    Args:
      url: URL to request.
      step_name: optional step name, 'fetch <url>' by default.
      headers: a {header_name: value} dictionary for HTTP headers.
      transient_retry (bool or int): Determines how transient HTTP errorts
          (>500) will be retried. If True (default), errors will be retried up
          to 10 times. If False, no transient retries will occur. If an integer
          is supplied, this is the number of transient retries to perform. All
          retries have exponential backoff applied.
      timeout: Timeout (see step.__call__).
      default_test_data (str): If provided, use this as the text output when
          testing if no overriding data is available.

    Returns (UrlApi.Response): Response with the content as its output value.

    Raises:
      HTTPError, InfraHTTPError: if the request failed.
      ValueError: If the request was invalid.
    """
    assert isinstance(default_test_data, (types.NoneType, str))
    return self._get_step(url, None, step_name, headers, transient_retry,
                          None, False, timeout, default_test_data)

  def get_json(self, url, step_name=None, headers=None, transient_retry=True,
               strip_prefix=None, log=False, timeout=None, default_test_data=None):
    """GET data at given URL and writes it to file.

    Args:
      url: URL to request.
      step_name: optional step name, 'fetch <url>' by default.
      headers: a {header_name: value} dictionary for HTTP headers.
      transient_retry (bool or int): Determines how transient HTTP errorts
          (>500) will be retried. If True (default), errors will be retried up
          to 10 times. If False, no transient retries will occur. If an integer
          is supplied, this is the number of transient retries to perform. All
          retries have exponential backoff applied.
      strip_prefix (str or None): If not None, this prefix must be present at
          the beginning of the response, and will be stripped from the resulting
          content (e.g., GERRIT_JSON_PREFIX).
      log (bool): If True, emit the JSON content as a log.
      timeout: Timeout (see step.__call__).
      default_test_data (jsonish): If provided, use this as the unmarshalled
          JSON result when testing if no overriding data is available.

    Returns (UrlApi.Response): Response with the JSON as its "output" value.

    Raises:
      HTTPError, InfraHTTPError: if the request failed.
      ValueError: If the request was invalid.
    """
    as_json = 'log' if log else True
    return self._get_step(url, None, step_name, headers, transient_retry,
                          strip_prefix, as_json, timeout, default_test_data)

  def _get_step(self, url, path, step_name, headers, transient_retry,
                strip_prefix, as_json, timeout, default_test_data):

    step_name = step_name or 'GET %s' % url
    is_secure = self.validate_url(url)

    args = [
        '--url', url,
        '--status-json', self.m.json.output(add_json_log=False,
                                            name='status_json'),
    ]

    if as_json:
      log = as_json == 'log'
      args += ['--outfile', self.m.json.output(add_json_log=log,
                                               name='output')]
    else:
      args += ['--outfile', self.m.raw_io.output_text(leak_to=path,
                                                      name='output')]

    if headers:
      has_authorization_header = any(k.lower() == 'authorization'
                                     for k in headers.iterkeys())
      if has_authorization_header and not is_secure:
        raise ValueError(
            'Refusing to send authorization header to insecure URL: %s' % (
            url,))

      args += ['--headers-json', self.m.json.input(headers)]
    if strip_prefix:
      args += ['--strip-prefix', self.m.json.dumps(strip_prefix)]

    assert isinstance(transient_retry, (bool, int, long))
    if transient_retry is False:
      args += ['--transient-retry', '0']
    elif transient_retry is not True:
      args += ['--transient-retry', str(transient_retry)]

    result = self.m.python(
        step_name,
        self.resource('pycurl.py'),
        args=args,
        venv=True,
        timeout=timeout,
        step_test_data=self.test_api._get_step_test_data(
            self._PyCurlStatus, as_json, default_test_data))

    output = path
    if not output:
      output_placeholder = (result.json.outputs if as_json
                            else result.raw_io.output_texts)
      output = output_placeholder['output']

    status = self._PyCurlStatus(**result.json.outputs['status_json'])
    response = self.Response('GET', output, status, self.m.context.infra_step)
    response.raise_on_error()
    return response
