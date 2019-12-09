# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the ResultDB service.

Requires `rdb` command in `$PATH`:
https://godoc.org/go.chromium.org/luci/resultdb/cmd/rdb
"""

import json

from google.protobuf import json_format
from recipe_engine import recipe_api

from . import common

from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import test_result as test_result_pb2


class ResultDBAPI(recipe_api.RecipeApi):
  """A module for interacting with ResultDB."""

  HOST_PROD = 'results.api.cr.dev'

  def initialize(self):
    self._host = (
        self.m.buildbucket.build.infra.resultdb.hostname or self.HOST_PROD
    )

  @property
  def host(self):
    """Hostname of ResultDB to use in API calls.

    Defaults to the hostname of the current build's invocation.
    """
    return self._host

  # TODO(nodir): add query method, a wrapper of rdb-ls.

  def chromium_derive_merge(self, *args, **kwargs):
    """Shortcut for chromium_derive(..., merge=True).get(None, [])."""
    kwargs['merge'] = True
    return self.chromium_derive(*args, **kwargs).get(None, [])

  def chromium_derive(
      self, swarming_host, task_ids, merge,
      variants_with_unexpected_results=False, limit=None, step_name=None):
    """Returns results derived from the specified Swarming tasks.

    TODO(crbug.com/1030191): remove this function in favor of query().

    Most users will be interested only in results of test variants that had
    unexpected results. This can be achieved by passing
    variants_with_unexpected_results=True. This significantly reduces output
    size and latency.

    Example:
      results = api.resultdb.derive(
          'chromium-swarm.appspot.com', ['deadbeef', 'badcoffee'],
          variants_with_unexpected_results=True,
      )
      failed_tests = {r.test_path for r in results}

    Args:
    *   `swarming_host` (str): hostname (without scheme) of the swarming server,
         such as chromium-swarm.appspot.com.
    *   `task_ids` (list of str): ids of the tasks to fetch results from.
         If more than one, then a union of their test results is returned.
         Its ok to pass same task ids, or ids of tasks that ran the same tests
         and had different results.
         Each task should have
         *   output.json or full_results.json in the isolated output.
             The file must be in Chromium JSON Test Result format or Chromium's
             GTest format. If the task does not have it, the request fails.
         *   optional tag "bucket" with the LUCI bucket, e.g. "ci"
             If the tag is not present, the test variants will not have the
             corresponding key.
         *   optional tag "buildername" with a builder name, e.g. "linux-rel"
             If the tag is not present, the test variants will not have the
             corresponding key.
         *   optional tag "test_suite" with a name of a test suite from a JSON
             file in
             https://chromium.googlesource.com/chromium/src/+/master/testing/buildbot/
             If the tag is not present, the test variants will not have the
             corresponding key.
         *   optional tag "gn_target" with a full name of the GN target used to
             compile the test binary used in the task, e.g.
             "gn_target://chrome/tests:browser_tests".
             If the tag is not present, the test paths are not prefixed.
    *   `merge` (bool): merge all results as if they were produced by one task.
        If a test X had expected and unexpected results in tasks T1 and T2,
        with merge=True, X's results from *both* T1 and T2 are returned;
        with merge=False, only from T2.
        merge=False should be used for tasks that might belong to unrelated
        builds, e.g. two builds of the same CI builder on different revisions,
        which is a rare case.
        If merge is True, the returned dict has only one key, None.
    *   `variants_with_unexpected_results` (bool): if True, return only test
        results from variants that have unexpected results.
        This significantly reduces output size and latency.
    *   `limit` (int): maximum number of test results to return.
        Defaults to 1000.

    Returns:
      A dict {invocation_id: [test_result_pb2.TestResult]}.
    """
    assert isinstance(swarming_host, str) and swarming_host, swarming_host
    assert not swarming_host.startswith('http://'), swarming_host
    assert not swarming_host.startswith('https://'), swarming_host
    assert all(isinstance(id, str) for id in task_ids), task_ids
    assert limit is None or limit >= 0
    task_ids = list(task_ids)
    limit = limit or 1000

    args = ['-n', str(limit)]
    if variants_with_unexpected_results:
      args += ['-u']
    if merge:
      args += ['-merge']
    args += [swarming_host] + task_ids

    step_res = self._run_rdb(
        subcommand='chromium-derive',
        args=args,
        step_name=step_name,
        stdout=self.m.raw_io.output(),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output(''),
    )
    return self._parse_query_output(step_res.stdout)

  ##############################################################################
  # Implementation details.

  def _parse_query_output(self, output):
    """Parses rdb-ls or rdb-derive output.

    Returns:
      A dict {invocation_id: [messages]}, where a message is
      test_result_pb2.TestResult or test_result_pb2.TestExoneration.
    """

    # The rdb output is a \n-separated JSON objects, where each object
    # does not have newlines, i.e. not indented.
    ret = {}

    for line in output.splitlines():
      entry = json.loads(line)
      assert isinstance(entry, dict), line
      msgs = ret.setdefault(entry.get('invocationId'), [])
      found = False
      for key, ctor in common.KINDS:
        if key in entry:
          found = True
          msg = ctor()
          json_format.ParseDict(
            entry[key], msg,
            # Do not fail the build because recipe's proto copy is stale.
            ignore_unknown_fields=True
          )
          msgs.append(msg)
          break
      assert found, entry

    return ret

  def _run_rdb(
      self, subcommand, step_name=None, args=None, stdout=None,
      step_test_data=None, timeout=None):
    """Runs rdb tool."""
    cmdline = [
      'rdb', subcommand,
      '-host', self._host,
      '-json',
    ] + (args or [])

    return self.m.step(
        step_name or ('rdb ' + subcommand),
        cmdline,
        infra_step=True,
        stdout=stdout,
        step_test_data=step_test_data,
        timeout=timeout,
    )
