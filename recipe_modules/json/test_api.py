import json

from slave import recipe_test_api

from .util import GTestResults, TestResults

class JsonTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None):
    return json.dumps(data), retcode

  # TODO(phajdan.jr): Rename to layout_test_results.
  @recipe_test_api.placeholder_step_data
  def test_results(self, test_results, retcode=None):
    return self.output(test_results.as_jsonish(), retcode)

  # TODO(phajdan.jr): Rename to canned_layout_test_output.
  def canned_test_output(self, passing, minimal=False, passes=9001,
                         num_additional_failures=0,
                         retcode=None):
    """Produces a 'json test results' compatible object with some canned tests.
    Args:
      passing - Determines if this test result is passing or not.
      passes - The number of (theoretically) passing tests.
      minimal - If True, the canned output will omit one test to emulate the
                effect of running fewer than the total number of tests.
      num_additional_failures - the number of failed tests to simulate in
                addition to the three generated if passing is False
    """
    if_failing = lambda fail_val: None if passing else fail_val
    t = TestResults()
    t.raw['num_passes'] = passes
    t.raw['num_regressions'] = 0
    t.add_result('flake/totally-flakey.html', 'PASS',
                 if_failing('TIMEOUT PASS'))
    t.add_result('flake/slow.html', 'SLOW',
                 if_failing('TIMEOUT SLOW'))
    t.add_result('tricky/totally-maybe-not-awesome.html', 'PASS',
                 if_failing('FAIL'))
    t.add_result('bad/totally-bad-probably.html', 'PASS',
                 if_failing('FAIL'))
    if not minimal:
      t.add_result('good/totally-awesome.html', 'PASS')
    for i in xrange(num_additional_failures):
        t.add_result('bad/failing%d.html' %i, 'PASS', 'FAIL')
    ret = self.test_results(t)
    if retcode is not None:
        ret.retcode = retcode
    else:
        ret.retcode = min(t.raw['num_regressions'], t.MAX_FAILURES_EXIT_STATUS)
    return ret

  @recipe_test_api.placeholder_step_data
  def gtest_results(self, test_results, retcode=None):
    return self.output(test_results.as_jsonish(), retcode)

  def canned_gtest_output(self, passing, minimal=False, passes=9001):
    """Produces a 'json test results' compatible object with some canned tests.
    Args:
      passing - Determines if this test result is passing or not.
      passes - The number of (theoretically) passing tests.
      minimal - If True, the canned output will omit one test to emulate the
                effect of running fewer than the total number of tests.
    """
    cur_iteration_data = {
      'Test.One': [
        {
          'elapsed_time_ms': 0,
          'output_snippet': '',
          'status': 'SUCCESS',
        },
      ],
      'Test.Two': [
        {
          'elapsed_time_ms': 0,
          'output_snippet': '',
          'status': 'SUCCESS' if passing else 'FAILURE',
        },
      ],
    }

    if not minimal:
      cur_iteration_data['Test.Three'] = [
        {
          'elapsed_time_ms': 0,
          'output_snippet': '',
          'status': 'SUCCESS',
        },
      ]

    canned_jsonish = {
      'per_iteration_data': [cur_iteration_data]
    }

    t = GTestResults(canned_jsonish)
    ret = self.gtest_results(t)
    ret.retcode = 0 if passing else 1
    return ret
