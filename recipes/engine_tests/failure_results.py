# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that run_steps is handling recipe failures correctly."""

from PB.recipe_engine import result as result_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import post_process

DEPS = [
  'step',
  'json'
]

def RunSteps(api):
    raw_result = result_pb2.RawResult()
    try:
        result = api.step('step_result',
            ['cmd', api.json.output()], timeout=480)
        if result.json.output:
            raw_result.summary_markdown = result.json.output['summary']
            raw_result.status = common_pb2.SUCCESS
        else:
            raw_result.summary_markdown = 'No json output.'
            raw_result.status = common_pb2.FAILURE
    except api.step.StepFailure:
        step_data = api.step.active_result
        if step_data.json.output:
            raw_result.summary_markdown = step_data.json.output['summary']

        if step_data.exc_result.had_timeout:
            raw_result.summary_markdown += 'Failure : Timeout'
            raw_result.status = common_pb2.FAILURE
        elif step_data.exc_result.retcode == 1:
            raw_result.status = common_pb2.FAILURE
        else:
            raw_result.status = common_pb2.INFRA_FAILURE
        if raw_result.summary_markdown == '':
            raise

    return raw_result

def GenTests(api):
    yield (
        api.test('successful_result') +
        api.step_data('step_result', api.json.output(
            {'summary': 'This test should be successful'})) +
        api.post_process(post_process.StatusSuccess) +
        api.post_process(post_process.DropExpectation)
    )

    yield (
        api.test('successful_result_no_json') +
        api.step_data('step_result', api.json.output({})) +
        api.post_process(post_process.StatusFailure) +
        api.post_process(post_process.ResultReason, "No json output.") +
        api.post_process(post_process.DropExpectation)
    )

    yield (
        api.test('failure_result') +
        api.step_data('step_result', api.json.output(
            {'summary': 'Failure: step failed at line 90'}, retcode=1)) +
        api.post_process(post_process.StatusFailure) +
        api.post_process(post_process.ResultReason,
            "Failure: step failed at line 90") +
        api.post_process(post_process.DropExpectation)
    )

    yield (
        api.test('infra_failure_result') +
        api.step_data('step_result', api.json.output(
            {'summary': 'Infra Failure: no memory'}, retcode=2)) +
        api.post_process(post_process.StatusException) +
        api.post_process(post_process.ResultReason,
            "Infra Failure: no memory") +
        api.post_process(post_process.DropExpectation)
    )

    yield (
        api.test('failure_result_no_json') +
        api.step_data('step_result', api.json.output(None, retcode=1)) +
        api.post_process(post_process.StatusFailure) +
        api.post_process(post_process.ResultReason,
            "Step('step_result') (retcode: 1)") +
        api.post_process(post_process.DropExpectation)
    )

    yield (
        api.test('infra_failure_result_no_json') +
        api.step_data('step_result', api.json.output(None, retcode=2)) +
        api.post_process(post_process.StatusFailure) +
        api.post_process(post_process.ResultReason,
            "Step('step_result') (retcode: 2)") +
        api.post_process(post_process.DropExpectation)
    )

    yield (
        api.test('timeout_result') +
        api.step_data('step_result', api.json.output({'summary': ''}),
            times_out_after=60*20) +
        api.post_process(post_process.StatusFailure) +
        api.post_process(post_process.ResultReason, "Failure : Timeout") +
        api.post_process(post_process.DropExpectation)
    )
