# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""API for interacting with the LUCI Analysis RPCs

This API is for calling LUCI Analysis RPCs for various aggregated info about
test results.
See go/luci-analysis for more info.
"""

import re
import attr

from google.protobuf import json_format
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.go.chromium.org.luci.analysis.proto.v1.predicate import TestVerdictPredicate
from PB.go.chromium.org.luci.analysis.proto.v1.test_history import (
    QueryTestHistoryRequest, QueryTestHistoryResponse, QueryVariantsRequest,
    QueryVariantsResponse)
from PB.go.chromium.org.luci.analysis.proto.v1.test_variants import (
    TestVariantFailureRateAnalysis, TestVariantStabilityAnalysis,
    TestStabilityCriteria)
from PB.go.chromium.org.luci.analysis.proto.v1.clusters import QueryClusterFailuresResponse

CLUSTER_STEP_NAME = 'cluster failing test results with luci analysis'


class LuciAnalysisApi(recipe_api.RecipeApi):

  def _run(self, step_name, rpc_endpoint, request_input, step_test_data=None):
    args = [
        'prpc',
        'call',
        'luci-analysis.appspot.com',
        rpc_endpoint,
    ]
    result = self.m.step(
        step_name,
        args,
        stdin=self.m.json.input(request_input),
        stdout=self.m.json.output(add_json_log=True),
        step_test_data=step_test_data,
    )
    result.presentation.logs['input'] = self.m.json.dumps(
        request_input, indent=2)
    return result.stdout

  def _query_failure_rate_step_test_data(self, test_ids):
    analysis_by_test_id = self._test_data.get('query_failure_rate_results', {})
    intervals = [{
        "endTime": "2022-12-01T18:49:23.160302198Z",
        "intervalAge": 1,
        "startTime": "2022-11-30T18:49:23.160302198Z"
    }, {
        "endTime": "2022-11-30T18:49:23.160302198Z",
        "intervalAge": 2,
        "startTime": "2022-11-29T18:49:23.160302198Z"
    }, {
        "endTime": "2022-11-29T18:49:23.160302198Z",
        "intervalAge": 3,
        "startTime": "2022-11-28T18:49:23.160302198Z"
    }, {
        "endTime": "2022-11-28T18:49:23.160302198Z",
        "intervalAge": 4,
        "startTime": "2022-11-25T18:49:23.160302198Z"
    }, {
        "endTime": "2022-11-25T18:49:23.160302198Z",
        "intervalAge": 5,
        "startTime": "2022-11-24T18:49:23.160302198Z"
    }]

    def _create_individual_test_variant(test_id):
      if test_id not in analysis_by_test_id:
        return self.test_api.generate_analysis(test_id=test_id)
      return analysis_by_test_id[test_id]

    return self.m.json.test_api.output_stream({
        'intervals': intervals,
        'testVariants': [_create_individual_test_variant(t) for t in test_ids],
    })

  def query_failure_rate(self, test_and_variant_list, project='chromium'):
    """Queries LUCI Analysis for failure rates

    Args:
      test_and_variant_list list(Test): List of dicts containing testId and
        variantHash
      project (str): Optional. The LUCI project to query the failures from.
    Returns:
      List of TestVariantFailureRateAnalysis protos
    """
    with self.m.step.nest('query LUCI Analysis for failure rates'):

      failure_analysis_dicts = self._run(
          'rpc call',
          'luci.analysis.v1.TestVariants.QueryFailureRate',
          {
              'project': project,
              'testVariants': test_and_variant_list,
          },
          step_test_data=lambda: self._query_failure_rate_step_test_data(
              [t['testId'] for t in test_and_variant_list]),
      ).get('testVariants')

      # Should not happen unless there's a server issue with the RPC
      if not failure_analysis_dicts:
        return {}

      return [
          json_format.ParseDict(
              d, TestVariantFailureRateAnalysis(), ignore_unknown_fields=True)
          for d in failure_analysis_dicts
      ]

  def query_stability(self, test_variant_position_list, project='chromium'):
    """Queries LUCI Analysis for test stability.

    Args:
      test_variant_position_list list(TestVariantPosition): List of dicts
        containing testId, variant and source position
      project (str): Optional. The LUCI project to query the failures from.
    Returns:
      Tuple of (List(TestVariantStabilityAnalysis), TestStabilityCriteria)
    Raises:
      StepFailure if query is invalid or service returns unexpected responses.
    """
    with self.m.step.nest('query LUCI Analysis for stability'):
      response_dicts = self._run(
          'rpc call',
          'luci.analysis.v1.TestVariants.QueryStability',
          {
              'project': project,
              'testVariants': test_variant_position_list,
          },
      )
      # This is not likely to happen, although invalid request may result in a
      # StepFailure directly raised from the above step.
      if not response_dicts or not response_dicts.get(
          'testVariants') or not response_dicts.get('criteria'):
        raise StepFailure(
            'Unexpected failure: unexpected response from RPC call')
      return [
          json_format.ParseDict(
              d, TestVariantStabilityAnalysis(), ignore_unknown_fields=True)
          for d in response_dicts.get('testVariants')
      ], json_format.ParseDict(
          response_dicts.get('criteria'),
          TestStabilityCriteria(),
          ignore_unknown_fields=True)

  def query_test_history(self,
                         test_id,
                         project='chromium',
                         sub_realm=None,
                         variant_predicate=None,
                         partition_time_range=None,
                         submitted_filter=None,
                         page_size=1000,
                         page_token=None):
    """A wrapper method to use `luci.analysis.v1.TestHistory` `Query` API.

    Args:
      test_id (str): test ID to query.
      project (str): Optional. The LUCI project to query the history from.
      sub_realm (str): Optional. The realm without the "<project>:" prefix.
        E.g. "try". Default all test verdicts will be returned.
      variant_predicate (luci.analysis.v1.VariantPredicate): Optional. The
        subset of test variants to request history for. Default all will be
        returned.
      partition_time_range (luci.analysis.v1.common.TimeRange): Optional. A
        range of timestamps to query the test history from. Default all will be
        returned. (At most recent 90 days as TTL).
      submitted_filter (luci.analysis.v1.common.SubmittedFilter): Optional.
        Whether test verdicts generated by code with unsubmitted changes (e.g.
        Gerrit changes) should be included in the response. Default all will be
        returned. Default all will be returned.
      page_size (int): Optional. The number of results per page in the response.
        If the number of results satisfying the given configuration exceeds this
        number, only the page_size results will be available in the response.
        Defaults to 1000.
      page_token (str): Optional. For instances in which the results span
        multiple pages, each response will contain a page token for the next
        page, which can be passed in to the next request. Defaults to None,
        which returns the first page.

    Returns:
      (list of parsed luci.analysis.v1.TestVerdict objects, next page token)
    """
    predicate = TestVerdictPredicate(
        sub_realm=sub_realm,
        variant_predicate=variant_predicate,
        submitted_filter=submitted_filter,
        partition_time_range=partition_time_range,
    )

    request = QueryTestHistoryRequest(
        project=project,
        test_id=test_id,
        predicate=predicate,
        page_size=page_size,
    )
    if page_token:
      request.page_token = page_token

    response_json = self._run('Test history query rpc call for %s' % test_id,
                              'luci.analysis.v1.TestHistory.Query',
                              json_format.MessageToDict(request))
    response = json_format.ParseDict(
        response_json, QueryTestHistoryResponse(), ignore_unknown_fields=True)
    return response.verdicts, response.next_page_token

  def query_variants(self,
                     test_id,
                     project='chromium',
                     sub_realm=None,
                     variant_predicate=None,
                     page_size=1000,
                     page_token=None):
    """A wrapper method to use `luci.analysis.v1.TestHistory` `QueryVariants`
    API.

    Args:

      test_id (str): test ID to query.
      project (str): Optional. The LUCI project to query the variants from.
      sub_realm (str): Optional. The realm without the "<project>:" prefix.
        E.g. "try". Default all test verdicts will be returned.
      variant_predicate (luci.analysis.v1.VariantPredicate): Optional. The
        subset of test variants to request history for. Default all will be
        returned.
      page_size (int): Optional. The number of results per page in the response.
        If the number of results satisfying the given configuration exceeds this
        number, only the page_size results will be available in the response.
        Defaults to 1000.
      page_token (str): Optional. For instances in which the results span
        multiple pages, each response will contain a page token for the next
        page, which can be passed in to the next request. Defaults to None,
        which returns the first page.

    Returns:
      (list of VariantInfo { variant_hash: str, variant: { def: dict } },
       next page token)
    """
    request = QueryVariantsRequest(
        project=project,
        test_id=test_id,
        sub_realm=sub_realm,
        variant_predicate=variant_predicate,
        page_size=page_size,
        page_token=page_token,
    )

    response_json = self._run(
        'Test history query_variants rpc call for %s' % test_id,
        'luci.analysis.v1.TestHistory.QueryVariants',
        json_format.MessageToDict(request))
    response = json_format.ParseDict(
        response_json, QueryVariantsResponse(), ignore_unknown_fields=True)
    return response.variants, response.next_page_token

  def lookup_bug(self, bug_id, system='monorail'):
    """Looks up the rule associated with a given bug.

    This is a wrapper of `luci.analysis.v1.Rules` `LookupBug` API.

    Args:
      bug_id (str): Bug Id is the bug tracking system-specific identity of the
        bug. For monorail, the scheme is {project}/{numeric_id}, for buganizer
        the scheme is {numeric_id}.
      system (str): System is the bug tracking system of the bug. This is either
        "monorail" or "buganizer". Defaults to monorail.

    Returns:
      list of rules (str), Format: projects/{project}/rules/{rule_id}
    """
    response_json = self._run(
        'Lookup Bug %s:%s' % (system, bug_id),
        'luci.analysis.v1.Rules.LookupBug', {
            'system': system,
            'id': bug_id,
        },
        step_test_data=lambda: self.m.json.test_api.output_stream({}))
    return response_json.get('rules', [])

  def rule_name_to_cluster_name(self, rule):
    """Convert the resource name for a rule to its corresponding cluster.
    Args:
      rule (str): Format: projects/{project}/rules/{rule_id}
    Returns:
      cluster (str): Format:
        projects/{project}/clusters/{cluster_algorithm}/{cluster_id}.
    """
    return re.sub(r'projects/(\w+)/rules/(\w+)',
                  'projects/\\1/clusters/rules/\\2', rule)

  def query_cluster_failures(self, cluster_name):
    """Queries examples of failures in the given cluster.

    This is a wrapper of `luci.analysis.v1.Clusters` `QueryClusterFailures` API.

    Args:
      cluster_name (str): The resource name of the cluster to retrieve.
        Format: projects/{project}/clusters/{cluster_algorithm}/{cluster_id}

    Returns:
      list of DistinctClusterFailure

      For value format, see [`DistinctClusterFailure` message]
      (https://bit.ly/DistinctClusterFailure)
    """
    assert not cluster_name.endswith('/failures'), cluster_name
    cluster_failure_name = cluster_name + '/failures'

    response_json = self._run(
        'Query Cluster Failure %s' % cluster_name,
        'luci.analysis.v1.Clusters.QueryClusterFailures', {
            'parent': cluster_failure_name,
        },
        step_test_data=(
            lambda: self.m.json.test_api.output_stream({'failures': []})))
    response = json_format.ParseDict(
        response_json,
        QueryClusterFailuresResponse(),
        ignore_unknown_fields=True)
    return response.failures
