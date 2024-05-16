# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the ResultDB service.

Requires `rdb` command in `$PATH`:
https://godoc.org/go.chromium.org/luci/resultdb/cmd/rdb
"""
from google.protobuf import field_mask_pb2
from google.protobuf import json_format
from google.protobuf import timestamp_pb2
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.resultdb.proto.v1 import artifact
from PB.go.chromium.org.luci.resultdb.proto.v1 import common as common_v1
from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import predicate
from PB.go.chromium.org.luci.resultdb.proto.v1 import recorder
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_variant

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
      add_invocations (list of str): invocation IDs to add to the current
          invocation.
      remove_invocations (list of str): invocation IDs to remove from the
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
        step_test_data=lambda: self.m.json.test_api.output_stream({}))

  def get_included_invocations(self, inv_name=None, step_name=None):
    """Returns names of included invocations of the input invocation.

    Args:
      inv_name (str): the name of the input invocation. If input is None, will
          use current invocation.
      step_name (str): name of the step.

    Returns:
      A list of invocation name strs.
    """
    req = resultdb.GetInvocationRequest(
        name=inv_name or self.current_invocation)
    res = self._rpc(
        step_name or 'get_included_invocations',
        'luci.resultdb.v1.ResultDB',
        'GetInvocation',
        json_format.MessageToDict(req),
        include_update_token=True,
        step_test_data=lambda: self.m.json.test_api.output_stream({}))

    inv_msg = json_format.ParseDict(
        res, invocation_pb2.Invocation(), ignore_unknown_fields=True)
    return inv_msg.included_invocations or []

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
          True, lambda: self.m.json.test_api.output_stream({})
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
    """Returns invocation IDs by parsing invocation names.

    Args:
      inv_names (list of str): ResultDB invocation names.

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
            tr_fields=None,
            test_invocations=None,
            test_regex=None):
    """Returns test results in the invocations.

    Most users will be interested only in results of test variants that had
    unexpected results. This can be achieved by passing
    variants_with_unexpected_results=True. This significantly reduces output
    size and latency.

    Example:
      results = api.resultdb.query(
          [
            # Invocation ID for a Swarming task.
            'task-chromium-swarm.appspot.com-deadbeef',
            # Invocation ID for a Buildbucket build.
            'build-234298374982'
          ],
          variants_with_unexpected_results=True,
      )

    Args:
      inv_ids (list of str): IDs of the invocations.
      variants_with_unexpected_results (bool): if True, return only test
        results from variants that have unexpected results.
      merge (bool): if True, return test results as if all invocations
        are one, otherwise, results will be ordered by invocation.
      limit (int): maximum number of test results to return.
        Unlimited if 0. Defaults to 1000.
      step_name (str): name of the step.
      tr_fields (list of str): test result fields in the response.
        Test result name will always be included regardless of this param value.
      test_invocations (dict {invocation_id: api.Invocation}): Default test data
        to be used to simulate the step in tests. The format is the same as
        what this method returns.
      test_regex (str): A regular expression of the relevant test variants
        to query for.

    Returns:
      A dict {invocation_id: api.Invocation}.
    """
    assert len(inv_ids) > 0
    assert all(isinstance(id, str) for id in inv_ids), inv_ids
    assert limit is None or limit >= 0
    assert tr_fields is None or all(
        isinstance(field, str) for field in tr_fields), tr_fields
    assert test_regex is None or isinstance(test_regex, str)
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
    if test_regex:
      args += ['-test', test_regex]

    args += list(inv_ids)

    step_res = self._run_rdb(
        subcommand='query',
        args=args,
        step_name=step_name,
        stdout=self.m.raw_io.output_text(add_output_log=True),
        step_test_data=lambda: self.m.raw_io.test_api.stream_output_text(
            common.serialize(test_invocations or {})),
    )
    return common.deserialize(step_res.stdout)

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
        req=json_format.MessageToDict(req),
        step_test_data=lambda: self.m.json.test_api.output_stream({}))

    return json_format.ParseDict(
        res,
        resultdb.QueryTestResultStatisticsResponse(),
        ignore_unknown_fields=True)

  def upload_invocation_artifacts(
      self, artifacts, parent_inv=None, step_name=None):
    """Create artifacts with the given content type and contents or gcs_uri.

    Makes a call to the BatchCreateArtifacts API. Returns the created
    artifacts.

    Args:
      artifacts (dict): a collection of artifacts to create. Each key is an
        artifact ID, with the corresponding value being a dict containing:
          'content_type' (optional)
          one of 'contents' (binary string) or 'gcs_uri' (str)
      parent_inv (str): the name of the invocation to create the artifacts
        under. If None, the current invocation will be used.
      step_name (str): name of the step.

    Returns:
      A BatchCreateArtifactsResponse proto message listing the artifacts that
      were created.
    """

    # TODO: mohrr - Transition artifacts argument from dict[str, dict] to
    # specific types like dict[str, ContentsArtifact | GcsUriArtifact].

    def ensure_bytes(s: str | bytes) -> bytes:
      if isinstance(s, bytes):
        return s
      return s.encode()

    req = recorder.BatchCreateArtifactsRequest(requests=[
        recorder.CreateArtifactRequest(
            parent=parent_inv or self.current_invocation,
            artifact=artifact.Artifact(
                artifact_id=art_id,
                content_type=art.get('content_type', ''),
                contents=ensure_bytes(art.get('contents', b'')),
                gcs_uri=art.get('gcs_uri', ''),
            ),
        ) for art_id, art in artifacts.items()
    ])

    res = self._rpc(
        step_name or 'upload_invocation_artifacts',
        'luci.resultdb.v1.Recorder',
        'BatchCreateArtifacts',
        req=json_format.MessageToDict(req),
        include_update_token=True,
        step_test_data=lambda: self.m.json.test_api.output_stream({}))

    return json_format.ParseDict(
        res,
        recorder.BatchCreateArtifactsResponse(),
        ignore_unknown_fields=True)

  def query_test_results(self,
                         invocations,
                         test_id_regexp=None,
                         variant_predicate=None,
                         field_mask_paths=None,
                         page_size=100,
                         page_token=None,
                         step_name=None):
    """Retrieve test results from an invocation, recursively.

    Makes a call to QueryTestResults rpc. Returns a list of test results for the
    invocations and matching the given filters.

    Args:
      invocations (list of str): retrieve the test results included in these
        invocations.
      test_id_regexp (str): the subset of test IDs to request history for.
        Default to None.
      variant_predicate (resultdb.proto.v1.predicate.VariantPredicate):
        the subset of test variants to request history for. Defaults to None,
        but specifying will improve runtime.
      field_mask_paths (list of str): test result fields in the response.
        Test result name will always be included regardless of this param value.
      page_size (int): the maximum number of variants to return. The service may
        return fewer than this value. The maximum value is 1000; values above
        1000 will be coerced to 1000. Defaults to 100.
      page_token (str): for instances in which the results span multiple pages,
        each response will contain a page token for the next page, which can be
        passed in to the next request. Defaults to None, which returns the first
        page.
      step_name (str): name of the step.

    Returns:
      A QueryTestResultsResponse proto message with test_results and
      next_page_token.

      For value format, see [`QueryTestResultsResponse` message]
      (https://bit.ly/3dsChbo)
    """

    req = resultdb.QueryTestResultsRequest(
        invocations=invocations,
        predicate=predicate.TestResultPredicate(
            test_id_regexp=test_id_regexp,
            variant=variant_predicate,
        ),
        page_size=page_size,
        page_token=page_token,
        read_mask=field_mask_pb2.FieldMask(paths=field_mask_paths),
    )

    res = self._rpc(step_name or 'query_test_results',
                    'luci.resultdb.v1.ResultDB',
                    'QueryTestResults',
                    req=json_format.MessageToDict(req))

    return json_format.ParseDict(
        res,
        resultdb.QueryTestResultsResponse(),
        # Do not fail the build because recipe's proto copy is stale.
        ignore_unknown_fields=True)

  def query_test_variants(self,
                          invocations,
                          test_variant_status=None,
                          field_mask_paths=None,
                          page_size=100,
                          page_token=None,
                          step_name=None):
    """Retrieve test variants from an invocation, recursively.

    Makes a call to QueryTestVariants rpc. Returns a list of test variants for
    the invocations and matching the given filters.

    Args:
      invocations (list of str): retrieve the test results included in these
        invocations.
      test_variant_status (resultdb.proto.v1.test_variant.TestVariantStatus):
        Use the UNEXPECTED_MASK status to retrieve only variants with
        non-EXPECTED status.
      field_mask_paths (list of str): test variant fields in the response.
        Test id, variantHash and status will always be included. Example:
        use ["test_id", "variant", "status", "sources_id"] to exclude results
        from the response. (Note that test_id and status are still specified for
        clarity.)
      page_size (int): the maximum number of variants to return. The service may
        return fewer than this value. The maximum value is 1000; values above
        1000 will be coerced to 1000. Defaults to 100.
      page_token (str): for instances in which the results span multiple pages,
        each response will contain a page token for the next page, which can be
        passed in to the next request. Defaults to None, which returns the first
        page.
      step_name (str): name of the step.

    Returns:
      A QueryTestVariantsResponse proto message with test_results and
      next_page_token.

      For value format, see [`QueryTestVariantsResponse` message]
      (http://shortn/_hv3edsXidO)
    """
    predicate = None
    if test_variant_status:
      predicate = test_variant.TestVariantPredicate(
          status=test_variant.TestVariantStatus.Value(test_variant_status))
    req = resultdb.QueryTestVariantsRequest(
        invocations=invocations,
        predicate=predicate,
        page_size=page_size,
        page_token=page_token,
        read_mask=field_mask_pb2.FieldMask(paths=field_mask_paths),
    )

    res = self._rpc(
        step_name or 'query_test_variants',
        'luci.resultdb.v1.ResultDB',
        'QueryTestVariants',
        req=json_format.MessageToDict(req))

    return json_format.ParseDict(
        res,
        resultdb.QueryTestVariantsResponse(),
        # Do not fail the build because recipe's proto copy is stale.
        ignore_unknown_fields=True)

  def query_new_test_variants(
      self,
      invocation: str,
      baseline: str,
      step_name: str = None,
      step_test_data: dict = None) -> resultdb.QueryNewTestVariantsResponse():
    """Query ResultDB for new tests.

    Makes a QueryNewTestVariants rpc.

    Args:
      inovcation: Name of the invocation, e.g. "invocations/{id}".
      baseline: The baseline to compare test variants against, to determine if
        they are new. e.g. “projects/{project}/baselines/{baseline_id}”.

    Returns:
     A QueryNewTestVariantsResponse proto message with is_baseline_ready and
     new_test_variants.
    """
    req = resultdb.QueryNewTestVariantsRequest(
        invocation=invocation,
        baseline=baseline,
    )

    res = self._rpc(
        step_name or 'query_new_test_variants',
        'luci.resultdb.v1.ResultDB',
        'QueryNewTestVariants',
        req=json_format.MessageToDict(req),
        step_test_data=(
            lambda: self.m.json.test_api.output_stream(step_test_data or {})),
    )
    return json_format.ParseDict(
        res,
        resultdb.QueryNewTestVariantsResponse(),
        # Do not fail the build because recipe's proto copy is stale.
        ignore_unknown_fields=True)

  def update_invocation(self,
                        parent_inv='',
                        step_name=None,
                        source_spec=None,
                        baseline_id=None,
                        instructions=None):
    """Makes a call to the UpdateInvocation API to update the invocation

    Args:
      parent_inv (str): the name of the invocation to be updated.
      step_name (str): name of the step.
      source_spec (luci.resultdb.v1.SourceSpec): The source information
        to apply to the given invocation.
      baseline_id (str): Baseline identifier for this invocation, usually of
        the format {buildbucket bucket}:{buildbucket builder name}. For example,
        'try:linux-rel'. Baselines are used to detect new tests in invocations.
      instructions (luci.resultdb.v1.Instructions): The reproduction
        instructions for this invocation. It may contain step instructions and
        test result instructions. The test instructions may contain instructions
        for test results in this invocation and in included invocations.
    """
    field_mask_paths = []
    if source_spec:
      field_mask_paths.append('source_spec')
    if baseline_id:
      field_mask_paths.append('baseline_id')
    if instructions:
      field_mask_paths.append('instructions')

    req = recorder.UpdateInvocationRequest(
        invocation=invocation_pb2.Invocation(
            name=parent_inv or self.current_invocation,
            source_spec=source_spec,
            baseline_id=baseline_id,
            instructions=instructions),
        update_mask=field_mask_pb2.FieldMask(paths=field_mask_paths),
    )
    self._rpc(
        step_name or 'update_invocations',
        'luci.resultdb.v1.Recorder',
        'UpdateInvocation',
        req=json_format.MessageToDict(req),
        include_update_token=True,
        step_test_data=lambda: self.m.json.test_api.output_stream({}))


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

  def wrap(
      self,
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
      inv_properties='',
      inv_properties_file='',
      inherit_sources=False,
      sources='',
      sources_file='',
      baseline_id='',
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
      inv_properties(str): stringified JSON object that contains structured,
        domain-specific properties of the invocation. When not specified,
        invocation-level properties will not be updated.
      inv_properties_file(string): Similar to inv_properties but takes a path
        to the file that contains the JSON object. Cannot be used when
        inv_properties is specified.
      inherit_sources(bool): flag to enable inheriting sources from the parent
        invocation.
      sources(string): JSON-serialized luci.resultdb.v1.Sources object that
        contains information about the code sources tested by the invocation.
        Cannot be used when inherit_sources or sources_file is specified.
      sources_file(string): Similar to sources, but takes a path to the
        file that contains the JSON object. Cannot be used when
        inherit_sources or sources is specified.
      baseline_id(string): Baseline identifier for this invocation, usually of
        the format {buildbucket bucket}:{buildbucket builder name}.
        For example, 'try:linux-rel'.
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
    assert isinstance(inv_properties, (type(None), str)), inv_properties
    assert isinstance(
      inv_properties_file, (type(None), str)), inv_properties_file
    assert not (inv_properties and inv_properties_file), inv_properties_file
    assert isinstance(inherit_sources, bool), inherit_sources
    assert isinstance(sources, (type(None), str)), sources
    assert isinstance(sources_file, (type(None), str)), sources_file
    assert isinstance(baseline_id, (type(None), str)), baseline_id

    ret = ['rdb', 'stream']

    if test_id_prefix:
      ret += ['-test-id-prefix', test_id_prefix]

    for k, v in sorted((base_variant or {}).items()):
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

    if inv_properties:
      ret += ['-inv-properties', inv_properties]

    if inv_properties_file:
      ret += ['-inv-properties-file', inv_properties_file]

    if inherit_sources:
      ret += ['-inherit-sources']

    if sources:
      ret += ['-sources', sources]

    if sources_file:
      ret += ['-sources-file', sources_file]

    if baseline_id:
      ret += ['-baseline-id', baseline_id]

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
