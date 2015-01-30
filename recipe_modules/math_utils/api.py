# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""General statistical or mathematical functions."""

import math

from slave import recipe_api

class MathUtilsApi(recipe_api.RecipeApi):

  @staticmethod
  def truncated_mean(data_set, truncate_percent):
    """Calculates the truncated mean of a set of values.

    Note that this isn't just the mean of the set of values with the highest
    and lowest values discarded; the non-discarded values are also weighted
    differently depending how many values are discarded.

    Args:
      data_set: Non-empty list of values.
      truncate_percent: How much of the upper and lower portions of the data set
          to discard, expressed as a value in [0, 1].

    Returns:
      The truncated mean as a float.

    Raises:
      TypeError: The data set was empty after discarding values.
    """
    if len(data_set) > 2:
      data_set = sorted(data_set)

      discard_num_float = len(data_set) * truncate_percent
      discard_num_int = int(math.floor(discard_num_float))
      kept_weight = len(data_set) - discard_num_float * 2

      data_set = data_set[discard_num_int:len(data_set)-discard_num_int]

      weight_left = 1.0 - (discard_num_float - discard_num_int)

      if weight_left < 1:
        # If the % to discard leaves a fractional portion, need to weight those
        # values.
        unweighted_vals = data_set[1:len(data_set)-1]
        weighted_vals = [data_set[0], data_set[len(data_set)-1]]
        weighted_vals = [w * weight_left for w in weighted_vals]
        data_set = weighted_vals + unweighted_vals
    else:
      kept_weight = len(data_set)

    _truncated_mean = reduce(lambda x, y: float(x) + float(y),
                            data_set) / kept_weight
    return _truncated_mean

  @staticmethod
  def mean(values):
    """Calculates the arithmetic mean of a list of values."""
    return MathUtilsApi.truncated_mean(values, 0.0)

  @staticmethod
  def variance(values):
    """Calculates the sample variance."""
    if len(values) == 1:
      return 0.0
    mean = MathUtilsApi.mean(values)
    differences_from_mean = [float(x) - mean for x in values]
    squared_differences = [float(x * x) for x in differences_from_mean]
    _variance = sum(squared_differences) / (len(values) - 1)
    return _variance

  @staticmethod
  def standard_deviation(values):
    """Calculates the sample standard deviation of the given list of values."""
    return math.sqrt(MathUtilsApi.variance(values))

  @staticmethod
  def relative_change(before, after):
    """Returns the relative change of before and after, relative to before.

    There are several different ways to define relative difference between
    two numbers; sometimes it is defined as relative to the smaller number,
    or to the mean of the two numbers. This version returns the difference
    relative to the first of the two numbers.

    Args:
      before: A number representing an earlier value.
      after: Another number, representing a later value.

    Returns:
      A non-negative floating point number; 0.1 represents a 10% change.
    """
    if before == after:
      return 0.0
    if before == 0:
      return float('nan')
    difference = after - before
    return math.fabs(difference / before)

  @staticmethod
  def pooled_standard_error(work_sets):
    """Calculates the pooled sample standard error for a set of samples.

    Args:
      work_sets: A collection of collections of numbers.

    Returns:
      Pooled sample standard error.
    """
    numerator = 0.0
    denominator1 = 0.0
    denominator2 = 0.0

    for current_set in work_sets:
      std_dev = MathUtilsApi.standard_deviation(current_set)
      numerator += (len(current_set) - 1) * std_dev ** 2
      denominator1 += len(current_set) - 1
      if len(current_set) > 0:
        denominator2 += 1.0 / len(current_set)

    if denominator1 == 0:
      return 0.0

    return math.sqrt(numerator / denominator1) * math.sqrt(denominator2)

  @staticmethod
  def standard_error(values):
    """Calculates the standard error of a list of values."""
    if len(values) <= 1:
      return 0.0
    std_dev = MathUtilsApi.standard_deviation(values)
    return std_dev / math.sqrt(len(values))

  #Copied this from BisectResults
  @staticmethod
  def confidence_score(sample1, sample2,
                      accept_single_bad_or_good=False):
    """Calculates a confidence score.

    This score is a percentage which represents our degree of confidence in the
    proposition that the good results and bad results are distinct groups, and
    their differences aren't due to chance alone.


    Args:
      sample1: A flat list of "good" result numbers.
      sample2: A flat list of "bad" result numbers.
      accept_single_bad_or_good: If True, computes confidence even if there is
          just one bad or good revision, otherwise single good or bad revision
          always returns 0.0 confidence. This flag will probably get away when
          we will implement expanding the bisect range by one more revision for
          such case.

    Returns:
      A number in the range [0, 100].
    """
    # If there's only one item in either list, this means only one revision was
    # classified good or bad; this isn't good enough evidence to make a
    # decision. If an empty list was passed, that also implies zero confidence.
    if not accept_single_bad_or_good:
      if len(sample1) <= 1 or len(sample2) <= 1:
        return 0.0

    # If there were only empty lists in either of the lists (this is unexpected
    # and normally shouldn't happen), then we also want to return 0.
    if not sample1 or not sample2:
      return 0.0

    # The p-value is approximately the probability of obtaining the given set
    # of good and bad values just by chance.
    _, _, p_value = MathUtilsApi.welchs_t_test(sample1, sample2)
    return 100.0 * (1.0 - p_value)

  @staticmethod
  def welchs_t_test(sample1, sample2):
    """Performs Welch's t-test on the two samples.

    Welch's t-test is an adaptation of Student's t-test which is used when the
    two samples may have unequal variances. It is also an independent two-sample
    t-test.

    Args:
      sample1: A collection of numbers.
      sample2: Another collection of numbers.

    Returns:
      A 3-tuple (t-statistic, degrees of freedom, p-value).
    """
    mean1 = MathUtilsApi.mean(sample1)
    mean2 = MathUtilsApi.mean(sample2)
    v1 = MathUtilsApi.variance(sample1)
    v2 = MathUtilsApi.variance(sample2)
    n1 = len(sample1)
    n2 = len(sample2)
    t = MathUtilsApi._t_value(mean1, mean2, v1, v2, n1, n2)
    df = MathUtilsApi._degrees_of_freedom(v1, v2, n1, n2)
    p = MathUtilsApi._lookup_p_value(t, df)
    return t, df, p

  @staticmethod
  def _t_value(mean1, mean2, v1, v2, n1, n2):
    """Calculates a t-statistic value using the formula for Welch's t-test.

    The t value can be thought of as a signal-to-noise ratio; a higher t-value
    tells you that the groups are more different.

    Args:
      mean1: Mean of sample 1.
      mean2: Mean of sample 2.
      v1: Variance of sample 1.
      v2: Variance of sample 2.
      n1: Sample size of sample 1.
      n2: Sample size of sample 2.

    Returns:
      A t value, which may be negative or positive.
    """
    # If variance of both segments is zero, return some large t-value.
    if v1 == 0 and v2 == 0:
      return 1000.0
    return (mean1 - mean2) / (math.sqrt(v1 / n1 + v2 / n2))

  @staticmethod
  def _degrees_of_freedom(v1, v2, n1, n2):
    """Calculates degrees of freedom using the Welch-Satterthwaite formula.

    Degrees of freedom is a measure of sample size. For other types of tests,
    degrees of freedom is sometimes N - 1, where N is the sample size. However,

    Args:
      v1: Variance of sample 1.
      v2: Variance of sample 2.
      n1: Size of sample 2.
      n2: Size of sample 2.

    Returns:
      An estimate of degrees of freedom. Must be at least 1.0.
    """
    # When there's no variance in either sample, return 1.
    if v1 == 0 and v2 == 0:
      return 1
    # If the sample size is too small, also return the minimum (1).
    if n1 <= 1 or n2 <= 2:
      return 1
    df = (((v1 / n1 + v2 / n2) ** 2) /
          ((v1 ** 2) / ((n1 ** 2) * (n1 - 1)) +
           (v2 ** 2) / ((n2 ** 2) * (n2 - 1))))
    return max(1, df)


  # Below is a hard-coded table for looking up p-values.
  #
  # Normally, p-values are calculated based on the t-distribution formula.
  # Looking up pre-calculated values is a less accurate but less complicated
  # alternative.
  #
  # Reference: http://www.sjsu.edu/faculty/gerstman/StatPrimer/t-table.pdf

  # A list of p-values for a two-tailed test. The entries correspond to to
  # entries in the rows of the table below.
  TWO_TAIL = [1, 0.20, 0.10, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001]

  # A map of degrees of freedom to lists of t-values. The index of the t-value
  # can be used to look up the corresponding p-value.
  TABLE = {
      1: [0, 3.078, 6.314, 12.706, 31.820, 63.657, 127.321, 318.309, 636.619],
      2: [0, 1.886, 2.920, 4.303, 6.965, 9.925, 14.089, 22.327, 31.599],
      3: [0, 1.638, 2.353, 3.182, 4.541, 5.841, 7.453, 10.215, 12.924],
      4: [0, 1.533, 2.132, 2.776, 3.747, 4.604, 5.598, 7.173, 8.610],
      5: [0, 1.476, 2.015, 2.571, 3.365, 4.032, 4.773, 5.893, 6.869],
      6: [0, 1.440, 1.943, 2.447, 3.143, 3.707, 4.317, 5.208, 5.959],
      7: [0, 1.415, 1.895, 2.365, 2.998, 3.499, 4.029, 4.785, 5.408],
      8: [0, 1.397, 1.860, 2.306, 2.897, 3.355, 3.833, 4.501, 5.041],
      9: [0, 1.383, 1.833, 2.262, 2.821, 3.250, 3.690, 4.297, 4.781],
      10: [0, 1.372, 1.812, 2.228, 2.764, 3.169, 3.581, 4.144, 4.587],
      11: [0, 1.363, 1.796, 2.201, 2.718, 3.106, 3.497, 4.025, 4.437],
      12: [0, 1.356, 1.782, 2.179, 2.681, 3.055, 3.428, 3.930, 4.318],
      13: [0, 1.350, 1.771, 2.160, 2.650, 3.012, 3.372, 3.852, 4.221],
      14: [0, 1.345, 1.761, 2.145, 2.625, 2.977, 3.326, 3.787, 4.140],
      15: [0, 1.341, 1.753, 2.131, 2.602, 2.947, 3.286, 3.733, 4.073],
      16: [0, 1.337, 1.746, 2.120, 2.584, 2.921, 3.252, 3.686, 4.015],
      17: [0, 1.333, 1.740, 2.110, 2.567, 2.898, 3.222, 3.646, 3.965],
      18: [0, 1.330, 1.734, 2.101, 2.552, 2.878, 3.197, 3.610, 3.922],
      19: [0, 1.328, 1.729, 2.093, 2.539, 2.861, 3.174, 3.579, 3.883],
      20: [0, 1.325, 1.725, 2.086, 2.528, 2.845, 3.153, 3.552, 3.850],
      21: [0, 1.323, 1.721, 2.080, 2.518, 2.831, 3.135, 3.527, 3.819],
      22: [0, 1.321, 1.717, 2.074, 2.508, 2.819, 3.119, 3.505, 3.792],
      23: [0, 1.319, 1.714, 2.069, 2.500, 2.807, 3.104, 3.485, 3.768],
      24: [0, 1.318, 1.711, 2.064, 2.492, 2.797, 3.090, 3.467, 3.745],
      25: [0, 1.316, 1.708, 2.060, 2.485, 2.787, 3.078, 3.450, 3.725],
      26: [0, 1.315, 1.706, 2.056, 2.479, 2.779, 3.067, 3.435, 3.707],
      27: [0, 1.314, 1.703, 2.052, 2.473, 2.771, 3.057, 3.421, 3.690],
      28: [0, 1.313, 1.701, 2.048, 2.467, 2.763, 3.047, 3.408, 3.674],
      29: [0, 1.311, 1.699, 2.045, 2.462, 2.756, 3.038, 3.396, 3.659],
      30: [0, 1.310, 1.697, 2.042, 2.457, 2.750, 3.030, 3.385, 3.646],
      31: [0, 1.309, 1.695, 2.040, 2.453, 2.744, 3.022, 3.375, 3.633],
      32: [0, 1.309, 1.694, 2.037, 2.449, 2.738, 3.015, 3.365, 3.622],
      33: [0, 1.308, 1.692, 2.035, 2.445, 2.733, 3.008, 3.356, 3.611],
      34: [0, 1.307, 1.691, 2.032, 2.441, 2.728, 3.002, 3.348, 3.601],
      35: [0, 1.306, 1.690, 2.030, 2.438, 2.724, 2.996, 3.340, 3.591],
      36: [0, 1.306, 1.688, 2.028, 2.434, 2.719, 2.991, 3.333, 3.582],
      37: [0, 1.305, 1.687, 2.026, 2.431, 2.715, 2.985, 3.326, 3.574],
      38: [0, 1.304, 1.686, 2.024, 2.429, 2.712, 2.980, 3.319, 3.566],
      39: [0, 1.304, 1.685, 2.023, 2.426, 2.708, 2.976, 3.313, 3.558],
      40: [0, 1.303, 1.684, 2.021, 2.423, 2.704, 2.971, 3.307, 3.551],
      42: [0, 1.302, 1.682, 2.018, 2.418, 2.698, 2.963, 3.296, 3.538],
      44: [0, 1.301, 1.680, 2.015, 2.414, 2.692, 2.956, 3.286, 3.526],
      46: [0, 1.300, 1.679, 2.013, 2.410, 2.687, 2.949, 3.277, 3.515],
      48: [0, 1.299, 1.677, 2.011, 2.407, 2.682, 2.943, 3.269, 3.505],
      50: [0, 1.299, 1.676, 2.009, 2.403, 2.678, 2.937, 3.261, 3.496],
      60: [0, 1.296, 1.671, 2.000, 2.390, 2.660, 2.915, 3.232, 3.460],
      70: [0, 1.294, 1.667, 1.994, 2.381, 2.648, 2.899, 3.211, 3.435],
      80: [0, 1.292, 1.664, 1.990, 2.374, 2.639, 2.887, 3.195, 3.416],
      90: [0, 1.291, 1.662, 1.987, 2.369, 2.632, 2.878, 3.183, 3.402],
      100: [0, 1.290, 1.660, 1.984, 2.364, 2.626, 2.871, 3.174, 3.391],
      120: [0, 1.289, 1.658, 1.980, 2.358, 2.617, 2.860, 3.160, 3.373],
      150: [0, 1.287, 1.655, 1.976, 2.351, 2.609, 2.849, 3.145, 3.357],
      200: [0, 1.286, 1.652, 1.972, 2.345, 2.601, 2.839, 3.131, 3.340],
      300: [0, 1.284, 1.650, 1.968, 2.339, 2.592, 2.828, 3.118, 3.323],
      500: [0, 1.283, 1.648, 1.965, 2.334, 2.586, 2.820, 3.107, 3.310],
  }

  @staticmethod
  def _lookup_p_value(t, df):
    """Looks up a p-value in a t-distribution table.

    Args:
      t: A t statistic value; the result of a t-test.
      df: Number of degrees of freedom.

    Returns:
      A p-value, which represents the likelihood of obtaining a result at least
      as extreme as the one observed just by chance (the null hypothesis).
    """
    assert df >= 1, 'Degrees of freedom must be positive'

    # We ignore the negative sign on the t-value because our null hypothesis
    # is that the two samples are the same; our alternative hypothesis is that
    # the second sample is lesser OR greater than the first.
    t = abs(t)

    def greatest_smaller(nums, target):
      """Returns the largest number that is <= the target number."""
      lesser_equal = [n for n in nums if n <= target]
      assert lesser_equal, 'No number in number list <= target.'
      return max(lesser_equal)

    df_key = greatest_smaller(MathUtilsApi.TABLE.keys(), df)
    t_table_row = MathUtilsApi.TABLE[df_key]
    approximate_t_value = greatest_smaller(t_table_row, t)
    t_value_index = t_table_row.index(approximate_t_value)

    return MathUtilsApi.TWO_TAIL[t_value_index]
