# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import json_format
from google.protobuf import timestamp_pb2
from google.protobuf.message import Message

from recipe_engine import recipe_test_api


class LuciAnalysisTestApi(recipe_test_api.RecipeTestApi):

  def construct_recent_verdicts(self, expected_count, unexpected_count):
    verdicts = []
    for i in range(expected_count):
      verdicts.append({
          'ingested_invocation_id': 'invocation_id_' + str(i),
          'hasUnexpectedRuns': False,
      })
    for i in range(unexpected_count):
      verdicts.append({
          'ingested_invocation_id': 'invocation_id_' + str(i * 10),
          'hasUnexpectedRuns': True,
      })
    return verdicts

  def construct_flaky_verdict_examples(self, example_times):
    verdict_examples = []
    if example_times:
      for example_time in example_times:
        verdict_examples.append({
            'partitionTime':
                timestamp_pb2.Timestamp(seconds=example_time).ToJsonString(),
        })
    return verdict_examples

  def generate_analysis(self,
                        test_id,
                        expected_count=10,
                        unexpected_count=0,
                        flaky_verdict_counts=(0, 0),
                        examples_times=None):
    interval_stats = [{
        'intervalAge': i + 1,
        'totalRunExpectedVerdicts': 300,
        'totalRunUnexpectedVerdicts': 1,
        'totalRunFlakyVerdicts': count,
    } for i, count in enumerate(flaky_verdict_counts)]

    return {
        'testId':
            test_id,
        'variantHash':
            'fake_variant_hash',
        'intervalStats':
            interval_stats,
        'recentVerdicts':
            self.construct_recent_verdicts(
                expected_count=expected_count,
                unexpected_count=unexpected_count,
            ),
        'runFlakyVerdictExamples':
            self.construct_flaky_verdict_examples(examples_times)
    }

  @recipe_test_api.mod_test_data
  @staticmethod
  def query_failure_rate_results(analysis_list):
    """Returns a test_id -> analysis dict to be used by the luci_analysis module

    analysis_list: List of analysis dicts created from generate_analysis()

    Returns: Dict
    """
    return {analysis['testId']: analysis for analysis in analysis_list}

  def generate_stability_analysis(
      self,
      test_id,
      failure_rate_is_met=False,
      flake_rate_is_met=False,
      run_flaky_verdicts_1wd=0,
      run_flaky_verdicts_12h=0,
  ):
    analysis = self.query_stability_example_analysis()
    analysis['testId'] = test_id
    analysis['failureRate']['isMet'] = failure_rate_is_met
    analysis['flakeRate']['isMet'] = flake_rate_is_met
    analysis['flakeRate']['runFlakyVerdicts1wd'] = run_flaky_verdicts_1wd
    analysis['flakeRate']['runFlakyVerdicts12h'] = run_flaky_verdicts_12h

    return analysis

  def generate_stability_response(self, stability_list):
    """Returns a fake luci.analysis.v1.TestVariants.QueryStabilityResponse

    stability_list: List of stability dicts created from
                    generate_stability_analysis()

    Returns: Dict
    """
    return {
        "testVariants": stability_list,
        "criteria": {
            "failureRate": {
                "failureThreshold": 6,
                "consecutiveFailureThreshold": 3
            },
            "flakeRate": {
                "minWindow": 100,
                "flakeThreshold": 2,
                "flakeRateThreshold": 0.01
            }
        }
    }

  def query_test_history(self,
                         response,
                         test_id,
                         parent_step_name=None,
                         step_iteration=1):
    """Emulates query_test_history() return value.
    Args:
      response: (luci.analysis.v1.test_history.QueryTestHistoryResponse) the
      response to simulate.
      test_id: (str) Test ID to query.
      parent_step_name: (str) The parent step name under which
        query_test_history is nested in, if any.
      step_iteration: (int) Used when the API is called multiple times for a
        same test_id.
    """
    parent_step_prefix = ''
    if parent_step_name:
      parent_step_prefix = ('%s.' % parent_step_name)
    step_suffix = ''
    if step_iteration > 1:
      step_suffix = ' (%d)' % step_iteration
    step_name = ('%sTest history query rpc call for %s%s' %
                 (parent_step_prefix, test_id, step_suffix))

    return self.step_data(
        step_name,
        self.m.json.output_stream(json_format.MessageToDict(response)))

  def query_variants(self,
                     response,
                     test_id,
                     parent_step_name=None,
                     step_iteration=1):
    """Emulates query_variants() return value.
    Args:
      response (luci.analysis.v1.test_history.QueryVariantsResponse): the
        response to simulate.
      test_id (str): Test ID to query.
      parent_step_name (str): The parent step name under which step is nested
        in, if any.
      step_iteration: (int) Used when the API is called multiple times for a
        same test_id.
    """
    parent_step_prefix = ''
    if parent_step_name:
      parent_step_prefix = ('%s.' % parent_step_name)
    step_suffix = ''
    if step_iteration > 1:
      step_suffix = ' (%d)' % step_iteration
    step_name = ('%sTest history query_variants rpc call for %s%s' %
                 (parent_step_prefix, test_id, step_suffix))

    return self.step_data(
        step_name,
        self.m.json.output_stream(json_format.MessageToDict(response)))

  def lookup_bug(self,
                 rules,
                 bug_id,
                 system='monorail',
                 parent_step_name=None,
                 step_iteration=1):
    """Emulates lookup_bug() return value.
    Args:
      rules (list of rules): Format: projects/{project}/rules/{rule_id}
      bug_id (str): Id is the bug tracking system-specific identity of the bug.
        For monorail, the scheme is {project}/{numeric_id}, for buganizer the
        scheme is {numeric_id}.
      system (str): System is the bug tracking system of the bug. This is either
        "monorail" or "buganizer". Defaults to monorail.
      parent_step_name (str): The parent step name under which step is nested
        in, if any.
      step_iteration: (int) Used when the API is called multiple times for a
        same test_id.
    """
    parent_step_prefix = ('%s.' % parent_step_name) if parent_step_name else ''
    step_suffix = (' (%d)' % step_iteration) if step_iteration > 1 else ''
    step_name = ('%sLookup Bug %s:%s%s' %
                 (parent_step_prefix, system, bug_id, step_suffix))

    return self.step_data(step_name,
                          self.m.json.output_stream({'rules': rules}))

  def query_cluster_failures(self,
                             failures,
                             cluster_name,
                             parent_step_name=None,
                             step_iteration=1):
    """Emulates query_cluster_failures() return value.
    Args:
      failures (list of DistinctClusterFailure): https://bit.ly/DistinctClusterFailure
      cluster_name (str): The resource name of the cluster to retrieve.
        Format: projects/{project}/clusters/{cluster_algorithm}/{cluster_id}
      parent_step_name (str): The parent step name under which step is nested
        in, if any.
      step_iteration: (int) Used when the API is called multiple times for a
        same test_id.
    """
    parent_step_prefix = ('%s.' % parent_step_name) if parent_step_name else ''
    step_suffix = (' (%d)' % step_iteration) if step_iteration > 1 else ''
    step_name = ('%sQuery Cluster Failure %s%s' %
                 (parent_step_prefix, cluster_name, step_suffix))

    return self.step_data(
        step_name,
        self.m.json.output_stream({
            'failures': [
                json_format.MessageToDict(x) if isinstance(x, Message) else x
                for x in failures
            ]
        }))

  @staticmethod
  def query_stability_example_input():
    return [{
        "testId": "tast.lockscreen.CloseLid.fieldtrial_testing_config_on",
        "variant": {
            "def": {
                "board": "hana",
                "build_target": "hana"
            }
        },
        "sources": {
            "changelists": [{
                "change": "5138795",
                "host": "chromium-review.googlesource.com",
                "patchset": "2",
                "project": "chromiumos/overlays/chromiumos-overlay"
            }],
            "gitilesCommit": {
                "host": "chrome-internal.googlesource.com",
                "project": "chromeos/manifest-internal",
                "ref": "refs/heads/snapshot",
                "commitHash": "47ccd8e3e33bcab3f56963c765c67deec7775292",
                "position": "92976"
            }
        }
    }]

  @staticmethod
  def query_stability_example_analysis():
    return {
        "testId": "tast.lockscreen.CloseLid.fieldtrial_testing_config_on",
        "variant": {
            "def": {
                "board": "hana",
                "build_target": "hana"
            }
        },
        "failureRate": {
            "isMet":
                True,
            "unexpectedTestRuns":
                10,
            "consecutiveUnexpectedTestRuns":
                10,
            "recentVerdicts": [{
                "position": "93211",
                "invocations": ["build-8759159713660408161"],
                "unexpectedRuns": 2,
                "totalRuns": 2
            }, {
                "position": "93210",
                "invocations": ["build-8759161637520826273"],
                "unexpectedRuns": 2,
                "totalRuns": 2
            }, {
                "position": "93208",
                "invocations": ["build-8759165807629055393"],
                "unexpectedRuns": 2,
                "totalRuns": 2
            }, {
                "position": "93207",
                "invocations": ["build-8759167441766272785"],
                "unexpectedRuns": 2,
                "totalRuns": 2
            }, {
                "position": "93206",
                "invocations": ["build-8759169052502629345"],
                "unexpectedRuns": 2,
                "totalRuns": 2
            }]
        },
        "flakeRate": {
            "isMet": True,
            "totalVerdicts": 134,
            "startPosition": "93206",
            "endPosition": "93552",
            "runFlakyVerdicts1wd": 3,
            "runFlakyVerdicts12h": 1
        }
    }

  @staticmethod
  def query_stability_example_output():
    return {
        "testVariants": [
            LuciAnalysisTestApi.query_stability_example_analysis()
        ],
        "criteria": {
            "failureRate": {
                "failureThreshold": 6,
                "consecutiveFailureThreshold": 3
            },
            "flakeRate": {
                "minWindow": 100,
                "flakeThreshold": 2,
                "flakeRateThreshold": 0.01
            }
        }
    }
