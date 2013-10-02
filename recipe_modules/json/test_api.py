import json

from slave import recipe_test_api

from .util import TestResults

class JsonTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None):
    return json.dumps(data), retcode

  @recipe_test_api.placeholder_step_data
  def test_results(self, test_results, retcode=None):
    return self.output(test_results.as_jsonish(), retcode)

  def canned_test_output(self, passing, minimal=False, passes=9001):
    """Produces a 'json test results' compatible object with some canned tests.
    Args:
      passing - Determines if this test result is passing or not.
      passes - The number of (theoretically) passing tests.
      minimal - If True, the canned output will omit one test to emulate the
                effect of running fewer than the total number of tests.
    """
    if_failing = lambda fail_val: None if passing else fail_val
    t = TestResults()
    t.raw['num_passes'] = passes
    t.add_result('flake/totally-flakey.html', 'PASS',
                 if_failing('TIMEOUT PASS'))
    t.add_result('tricky/totally-maybe-not-awesome.html', 'PASS',
                 if_failing('FAIL'))
    t.add_result('bad/totally-bad-probably.html', 'PASS',
                 if_failing('FAIL'))
    if not minimal:
      t.add_result('good/totally-awesome.html', 'PASS')
    ret = self.test_results(t)
    ret.retcode = 0 if passing else 1
    return ret
