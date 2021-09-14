# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the ResultDB service.

Requires `rdb` command in `$PATH`:
https://godoc.org/go.chromium.org/luci/resultdb/cmd/rdb
"""

from future.utils import iteritems

from google.protobuf import json_format
from google.protobuf import timestamp_pb2
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_v1
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb

from . import common

_SECONDS_PER_DAY = 86400


class ResultDBAPI(recipe_api.RecipeApi):
  """A module for interacting with ResultDB."""

  # Maximum number of requests in a batch RPC.
  _BATCH_SIZE = 500

  # Prefix of an invocation name.
  _INVOCATION_NAME_PREFIX  = 'invocations/'

  # Expose serialize and deserialize functions.
  serialize = staticmethod(common.serialize)
  deserialize = staticmethod(common.deserialize)
  Invocation = common.Invocation

  @property
  def current_invocation(self):
    return self.m.context.resultdb_invocation_name

  @property
  def enabled(self):
    return self.current_invocation != ''

  def assert_enabled(self):
    assert self.enabled, (
      'ResultDB integration was not enabled for this build. '
      'See go/lucicfg#luci.builder and go/lucicfg#resultdb.settings'
    )

  def include_invocations(self, invocations, step_name=None):
    """Shortcut for resultdb.update_included_invocations()."""
    return self.update_included_invocations(
        add_invocations=invocations, step_name=step_name)

  def exclude_invocations(self, invocations, step_name=None):
    """Shortcut for resultdb.update_included_invocations()."""
    return self.update_included_invocations(
        remove_invocations=invocations, step_name=step_name)

  def update_included_invocations(self,
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
    self.assert_enabled()

    if not (add_invocations or remove_invocations):
      # Nothing to do.
      return

    names = lambda ids: ['invocations/%s' % id for id in ids or []]
    req = recorder.UpdateIncludedInvocationsRequest(
        including_invocation=self.current_invocation,
        add_invocations=names(add_invocations),
        remove_invocations=names(remove_invocations),
    )

    self._rpc(
        step_name or 'resultdb.update_included_invocations',
        'luci.resultdb.v1.Recorder',
        'UpdateIncludedInvocations',
        json_format.MessageToDict(req),
        include_update_token=True,
        step_test_data=lambda: self.m.raw_io.test_api.stream_output('{}'))

  def exonerate(self, test_exonerations, step_name=None):
    """Exonerates test variants in the current invocation.

    Args:
      test_exonerations (list): A list of test_result_pb2.TestExoneration.
      step_name (str): name of the step.
    """

    def args(test_exonerations, step_name):
      req = recorder.BatchCreateTestExonerationsRequest(
          invocation=self.current_invocation,
          request_id=self.m.uuid.random(),
      )
      for te in test_exonerations:
        req.requests.add(test_exoneration=te)

      return [
          step_name, 'luci.resultdb.v1.Recorder', 'BatchCreateTestExonerations',
          json_format.MessageToDict(req),
          True, lambda: self.m.raw_io.test_api.stream_output('{}')
      ]

    if not test_exonerations:
      return

    self.assert_enabled()
    step_name = step_name or 'resultdb.exonerate'

    if len(test_exonerations) <= self._BATCH_SIZE:
      self._rpc(*args(test_exonerations, step_name))
      return

    # Sends requests in batches.
    remaining = test_exonerations
    i = 0
    with self.m.step.nest(step_name):
      while remaining:
        batch = remaining[:self._BATCH_SIZE]
        remaining = remaining[self._BATCH_SIZE:]
        self.m.futures.spawn(self._rpc, *args(batch, 'batch (%d)' % i))
        i += 1

  def invocation_ids(self, inv_names):
    """Returns invocation ids by parsing invocation names.

    Args:
      inv_names (list of str): resultdb invocation names.

    Returns:
      A list of invocation_ids.
    """
    assert all(isinstance(name, str) for name in inv_names), inv_names
    assert all(name.startswith(
        self._INVOCATION_NAME_PREFIX) for name in inv_names), inv_names

    return [name[len(self._INVOCATION_NAME_PREFIX):] for name in inv_names]

  def query(self,
            inv_ids,
            variants_with_unexpected_results=False,
            merge=False,
            limit=None,
            step_name=None,
            tr_fields=None):
    """Returns test results in the invocations.

    Most users will be interested only in results of test variants that had
    unexpected results. This can be achieved by passing
    variants_with_unexpected_results=True. This significantly reduces output
    size and latency.

    Example:
      results = api.resultdb.query(
          [
            # invocation id for a swarming task.
            'task-chromium-swarm.appspot.com-deadbeef',
            # invocation id for a buildbucket build.
            'build-234298374982'
          ],
          variants_with_unexpected_results=True,
      )

    Args:
      inv_ids (list of str): ids of the invocations.
      variants_with_unexpected_results (bool): if True, return only test
        results from variants that have unexpected results.
      merge (bool): if True, return test results as if all invocations
        are one, otherwise, results will be ordered by invocation.
      limit (int): maximum number of test results to return.
        Unlimited if 0. Defaults to 1000.
      step_name (str): name of the step.
      tr_fields (list of str): test result fields in the response.
        Test result name will always be included regardless of this param value.
    Returns:
      A dict {invocation_id: api.Invocation}.
    """
    assert len(inv_ids) > 0
    assert all(isinstance(id, str) for id in inv_ids), inv_ids
    assert limit is None or limit >= 0
    assert tr_fields is None or all(
        isinstance(field, str) for field in tr_fields), tr_fields
    limit = 1000 if limit is None else limit

    args = [
      '-json',
      '-n', str(limit),
    ]
    if variants_with_unexpected_results:
      args += ['-u']
    if merge:
      args += ['-merge']
    if tr_fields:
      args += ['-tr-fields', ','.join(tr_fields)]

    args += list(inv_ids)

    step_res = self._run_rdb(
        subcommand='query',
        args=args,
        step_name=step_name,
        stdout=self.m.raw_io.output(add_output_log=True),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output(''),
    )
    return common.deserialize(step_res.stdout)

  def get_test_result_history(self,
                              realm,
                              test_id_regexp,
                              variant_predicate=None,
                              time_range=None,
                              page_size=10,
                              page_token=None,
                              step_name=None):
    """Receive test results for a given configuration.

    Makes a call to GetTestResultHistory rpc. Allows for test retrieval for
    all invocations with the specified configurations.

    Args:
      realm (str): the realm that the data being queried exists in.
        Example: "chromium:ci".
      test_id_regexp (str): the subset of test ids to request history for.
      variant_predicate (resultdb.proto.v1.predicate.VariantPredicate):
        the subset of test variants to request history for. Defaults to None,
        but specifying will improve runtime.
      time_range (common_v1.TimeRange): a range of timestamps in which to
        request history from. If no time_range is specified, it defaults to the
        past day.
      page_size (int): the number of results per page in the response. If the
        number of results satisfying the given configuration exceeds this
        number, only the page_size results will be available in the response.
        Defaults to 10 results.
      page_token (str): for instances in which the results span multiple pages,
        each response will contain a page token for the next page, which can be
        passed in to the next request. Defaults to None, which returns the first
        page.
      step_name (str): name of the step.

    Returns:
      A GetTestResultHistoryResponse proto message with entries for each test
      matching the configuration.

      For value format, see [`GetTestResultHistoryResponse` message]
      (https://bit.ly/3bSXxU1)
    """
    if time_range is None:
      now = int(self.m.time.time())
      time_range = common_v1.TimeRange(
          earliest=timestamp_pb2.Timestamp(seconds=now - _SECONDS_PER_DAY),
          latest=timestamp_pb2.Timestamp(seconds=now))

    req = resultdb.GetTestResultHistoryRequest(
        realm=realm,
        test_id_regexp=test_id_regexp,
        time_range=time_range,
        page_size=page_size)

    if variant_predicate:
      req.variant_predicate.CopyFrom(variant_predicate)

    if page_token:
      req.page_token = page_token

    res = self._rpc(
        step_name or 'get_test_result_history',
        'luci.resultdb.v1.ResultDB',
        'GetTestResultHistory',
        req=json_format.MessageToDict(req))

    return json_format.ParseDict(
        res,
        resultdb.GetTestResultHistoryResponse(),
        # Do not fail the build because recipe's proto copy is stale.
        ignore_unknown_fields=True)

  def query_test_result_statistics(self, invocations=None, step_name=None):
    """Retrieve stats of test results for the given invocations.

    Makes a call to the QueryTestResultStatistics API. Returns stats for all
    given invocations, including those included indirectly.

    Args:
      invocations (list): A list of the invocations to query statistics for.
        If None, the current invocation will be used.
      step_name (str): name of the step.

    Returns:
      A QueryTestResultStatisticsResponse proto message with statistics for the
      queried invocations.
    """

    if invocations is None:
      invocations = [self.current_invocation]

    req = resultdb.QueryTestResultStatisticsRequest(invocations=invocations)

    res = self._rpc(
        step_name or 'query_test_result_statistics',
        'luci.resultdb.v1.ResultDB',
        'QueryTestResultStatistics',
        req=json_format.MessageToDict(req))

    return json_format.ParseDict(
        res,
        resultdb.QueryTestResultStatisticsResponse(),
        ignore_unknown_fields=True)

  ##############################################################################
  # Implementation details.

  def _rpc(self,
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
        "luci.resultdb.v1.ResultDB".
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
        subcommand='rpc',
        step_name=step_name,
        args=args,
        stdin=self.m.json.input(req),
        stdout=self.m.json.output(),
        step_test_data=step_test_data,
    )
    step_res.presentation.logs['json.input'] = self.m.json.dumps(req, indent=2)

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

  def wrap(self,
           cmd,
           test_id_prefix='',
           base_variant=None,
           test_location_base='',
           base_tags=None,
           coerce_negative_duration=False,
           include=False,
           realm='',
           location_tags_file='',
           require_build_inv=True,
           exonerate_unexpected_pass=False,
  ):
    """Wraps the command with ResultSink.

    Returns a command that, when executed, runs cmd in a go/result-sink
    environment. For example:

       api.step('test', api.resultdb.wrap(['./my_test']))

    Args:
      cmd (list of strings): the command line to run.
      test_id_prefix (str): a prefix to prepend to test IDs of test results
        reported by cmd.
      base_variant (dict): variant key-value pairs to attach to all test results
        reported by cmd. If both base_variant and a reported variant have a
        value for the same key, the reported one wins.
        Example:
          base_variant={
            'bucket': api.buildbucket.build.builder.bucket,
            'builder': api.buildbucket.builder_name,
          }
      test_location_base (str): the base path to prepend to the test location
        file name with a relative path. The value must start with "//".
      base_tags (list of (string, string)): tags to attach to all test results
        reported by cmd. Each element is a tuple of (key, value), and a key
        may be repeated.
      coerce_negative_duration (bool): If true, negative duration values will
        be coerced to 0. If false, tests results with negative duration values
        will be rejected with an error.
      include (bool): If true, a new invocation will be created and included
        in the parent invocation.
      realm (str): realm used for the new invocation created if `include=True`.
        Default is the current realm used in buildbucket.
      location_tags_file (str): path to the file that contains test location
        tags in JSON format.
      require_build_inv(bool): flag to control if the build is required to have
        an invocation.
      exonerate_unexpected_pass(bool): flag to control if automatically
        exonerate unexpected passes.
    """
    if require_build_inv:
      self.assert_enabled()
    assert isinstance(test_id_prefix, (type(None), str)), test_id_prefix
    assert isinstance(base_variant, (type(None), dict)), base_variant
    assert isinstance(cmd, (tuple, list)), cmd
    assert isinstance(test_location_base, (type(None), str)), test_location_base
    assert not test_location_base or test_location_base.startswith(
        '//'), test_location_base
    assert isinstance(base_tags, (type(None), list)), base_tags
    assert isinstance(coerce_negative_duration, bool), coerce_negative_duration
    assert isinstance(include, bool), include
    assert isinstance(realm, (type(None), str)), realm
    assert isinstance(location_tags_file, (type(None), str)), location_tags_file
    assert isinstance(
        exonerate_unexpected_pass, bool), exonerate_unexpected_pass

    ret = ['rdb', 'stream']

    if test_id_prefix:
      ret += ['-test-id-prefix', test_id_prefix]

    for k, v in sorted(iteritems(base_variant or {})):
      ret += ['-var', '%s:%s' % (k, v)]

    if test_location_base:
      ret += ['-test-location-base', test_location_base]

    for k, v in sorted(base_tags or []):
      ret += ['-tag', '%s:%s' % (k, v)]

    if coerce_negative_duration:
      ret += ['-coerce-negative-duration']

    if include:
      ret += [
          '-new', '-realm', realm or self.m.context.realm,
          '-include'
      ]

    if location_tags_file:
      ret += ['-location-tags-file', location_tags_file]

    if exonerate_unexpected_pass:
      ret += ['-exonerate-unexpected-pass']

    ret += ['--'] + list(cmd)
    return ret

  def config_test_presentation(self, column_keys=(), grouping_keys=('status',)):
    """Specifies how the test results should be rendered.

    Args:
      column_keys:
        A list of keys that will be rendered as 'columns'. status is always the
        first column and name is always the last column (you don't need to
        specify them). A key must be one of the following:
        1. 'v.{variant_key}': variant.def[variant_key] of the test variant (e.g.
          v.gpu).

      grouping_keys:
        A list of keys that will be used for grouping tests. A key must be one
        of the following:
        1. 'status': status of the test variant.
        2. 'name': name of the test variant.
        3. 'v.{variant_key}': variant.def[variant_key] of the test variant (e.g.
        v.gpu).
        Caveat: test variants with only expected results are not affected by
        this setting and are always in their own group.
    """

    # To be consistent with the lucicfg implementation, set the test
    # presentation config only when it's not the default value.
    if list(column_keys) == [] and list(grouping_keys) == ['status']:
      return

    # Validate column_keys.
    for k in column_keys:
      assert k.startswith('v.')

    # Validate grouping_keys.
    for k in grouping_keys:
      assert k in ['status', 'name'] or k.startswith('v.')

    # The fact that it sets a property value is an implementation detail.
    res = self.m.step('set test presentation config', cmd=None)
    prop_name = '$recipe_engine/resultdb/test_presentation'
    res.presentation.properties[prop_name] = {
      'column_keys': column_keys,
      'grouping_keys': grouping_keys,
    }
