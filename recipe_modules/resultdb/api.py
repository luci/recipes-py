# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the ResultDB service.

Requires `rdb` command in `$PATH`:
https://godoc.org/go.chromium.org/luci/resultdb/cmd/rdb
"""

from google.protobuf import json_format
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import recorder

from . import common


class ResultDBAPI(recipe_api.RecipeApi):
  """A module for interacting with ResultDB."""

  # Expose serialize and deserialize functions.

  serialize = staticmethod(common.serialize)
  deserialize = staticmethod(common.deserialize)
  Invocation = common.Invocation

  # TODO(nodir): add query method, a wrapper of rdb-ls.

  def remove_invocations(self, invocations, step_name=None):
    """Shortcut for resultdb.update_inclusions()."""
    return self.update_inclusions(
        remove_invocations=invocations, step_name=step_name)

  def include_invocations(self, invocations, step_name=None):
    """Shortcut for resultdb.update_inclusions()."""
    return self.update_inclusions(
        add_invocations=invocations, step_name=step_name)

  def update_inclusions(self,
                        add_invocations=None,
                        remove_invocations=None,
                        step_name=None):
    """Add and/or remove included invocations to/from the current invocation.

    Args:
      add_invocations (list of str): invocation id's to add to the current
          invocation.
      remove_invocations (list of str): invocation id's to remove from the
          current invocation.

    This updates the inclusions of the current invocation specified in the
    LUCI_CONTEXT.
    """
    if not (add_invocations or remove_invocations):
      # Nothing to do.
      return
    args = []
    if add_invocations:
      args += ['-add', ','.join(sorted(add_invocations))]
    if remove_invocations:
      args += ['-remove', ','.join(sorted(remove_invocations))]
    return self._run_rdb(
        subcommand='update-inclusions',
        args=args,
        step_name=step_name,
    )

  def exonerate(self, test_exonerations, step_name=None):
    """Exonerates test variants in the current invocation.

    Args:
      test_exonerations (list): A list of test_result_pb2.TestExoneration.
      step_name (str): name of the step.
    """
    assert self.m.buildbucket.build.infra.resultdb.invocation, (
        'ResultDB integration was not enabled')

    req = recorder.BatchCreateTestExonerationsRequest(
        invocation=self.m.buildbucket.build.infra.resultdb.invocation,
        request_id=self.m.uuid.random(),
    )
    for te in test_exonerations:
      req.requests.add(test_exoneration=te)

    self._call(
        step_name or 'resultdb.exonerate',
        'luci.resultdb.rpc.v1.Recorder',
        'BatchCreateTestExonerations',
        json_format.MessageToDict(req),
        include_update_token=True,
        step_test_data=lambda: self.m.raw_io.test_api.stream_output('{}'))

  def chromium_derive(self,
                      swarming_host,
                      task_ids,
                      variants_with_unexpected_results=False,
                      limit=None,
                      step_name=None):
    """Returns results derived from the specified Swarming tasks.

    TODO(crbug.com/1030191): remove this function in favor of query().

    Most users will be interested only in results of test variants that had
    unexpected results. This can be achieved by passing
    variants_with_unexpected_results=True. This significantly reduces output
    size and latency.

    Blocks on task completion.

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
         *   optional tag "ninja_target" with a full name of the ninja target
             used to compile the test binary used in the task, e.g.
             "ninja_target://chrome/tests:browser_tests".
             If the tag is not present, the test paths are not prefixed.
    *   `variants_with_unexpected_results` (bool): if True, return only test
        results from variants that have unexpected results.
        This significantly reduces output size and latency.
    *   `limit` (int): maximum number of test results to return.
        Defaults to 1000.

    Returns:
      A dict {invocation_id: api.Invocation}.
    """
    assert isinstance(swarming_host, str) and swarming_host, swarming_host
    assert not swarming_host.startswith('http://'), swarming_host
    assert not swarming_host.startswith('https://'), swarming_host
    assert all(isinstance(id, str) for id in task_ids), task_ids
    assert limit is None or limit >= 0
    task_ids = list(task_ids)
    limit = limit or 1000

    args = [
      '-json',
      '-wait',
      '-n', str(limit),
    ]
    if variants_with_unexpected_results:
      args += ['-u']
    args += [swarming_host] + task_ids

    step_res = self._run_rdb(
        subcommand='chromium-derive',
        args=args,
        step_name=step_name,
        stdout=self.m.raw_io.output(add_output_log=True),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output(''),
    )
    return common.deserialize(step_res.stdout)

  ##############################################################################
  # Implementation details.

  def _call(self,
            step_name,
            service,
            method,
            req,
            include_update_token=False,
            step_test_data=None):
    """Makes a ResultDB RPC.

    Args:
      step_name (str): name of the step.
      service (string): the full name of a service, e.g.
        "luci.resultdb.rpc.v1.ResultDB".
      method (string): the name of the method, e.g. "GetInvocation".
      req (dict): request message.
      include_update_token (bool): A flag to indicate if the RPC requires the
        update token of the invocation.

    Returns:
      A dict representation of the response message.
    """
    args = [service, method]
    if include_update_token:
      args.append('-include-update-token')

    step_res = self._run_rdb(
        subcommand='call',
        step_name=step_name,
        args=args,
        stdin=self.m.json.input(req),
        stdout=self.m.json.output(),
        step_test_data=step_test_data,
    )
    return step_res.stdout

  def _run_rdb(self,
               subcommand,
               step_name=None,
               args=None,
               stdin=None,
               stdout=None,
               step_test_data=None,
               timeout=None):
    """Runs rdb tool."""
    cmdline = ['rdb', subcommand] + (args or [])

    return self.m.step(
        step_name or ('rdb ' + subcommand),
        cmdline,
        infra_step=True,
        stdin=stdin,
        stdout=stdout,
        step_test_data=step_test_data,
        timeout=timeout,
    )
