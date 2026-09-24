# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations
from collections.abc import Callable
from typing import Any

import http.client

from recipe_engine import recipe_test_api

class UrlTestApi(recipe_test_api.RecipeTestApi): # pragma: no cover

  def _response(
      self,
      step_name: str,
      data: recipe_test_api.StepTestData | None,
      size: int,
      status_code: int = 200,
      error_body: str | None = None,
  ) -> recipe_test_api.TestData:
    step_data = [
        self.m.json.output({
          'status_code': status_code,
          'success': status_code in (http.client.OK, http.client.NO_CONTENT),
          'size': size,
          'error_body': error_body,
        }, name='status_json'),
    ]
    if data:
      step_data.append(data)
    return self.step_data(step_name, *step_data)

  def error(
      self, step_name: str, status_code: int, body: str | None = None
  ) -> recipe_test_api.TestData:
    body = body or 'HTTP Error (%d)' % (status_code,)
    return self._response(
        step_name=step_name,
        data=None,
        size=len(body),
        status_code=status_code,
        error_body=body)

  def text(self, step_name: str, v: str) -> recipe_test_api.TestData:
    return self._response(
        step_name=step_name,
        data=self.m.raw_io.output_text(v, name='output'),
        size=len(v))

  def raw(self, step_name: str, v: bytes) -> recipe_test_api.TestData:
    return self._response(
        step_name=step_name,
        data=self.m.raw_io.output(v, name='output'),
        size=len(v))

  def json(self, step_name: str, obj: Any) -> recipe_test_api.TestData:
    return self._response(
        step_name=step_name,
        data=self.m.json.output(obj, name='output'),
        size=len(self.m.json.dumps(obj)))

  def _get_step_test_data(
      self,
      status_cls: type[Any],
      is_json: bool | str,
      is_bytes: bool,
      test_data: Any,
  ) -> Callable[[], recipe_test_api.StepTestData] | None:
    if test_data is None:
      return None

    output_class = (self.m.json.output if is_json
                    else self.m.raw_io.output if is_bytes
                    else self.m.raw_io.output_text)
    success_status = status_cls(
        status_code=200, success=True, size=len(test_data),
        error_body=None)._asdict()
    return lambda: (
        output_class(test_data, name='output') +
        self.m.json.output(success_status, name='status_json'))
