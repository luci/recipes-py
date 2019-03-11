# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


def header(input_api):
  """Returns the expected license header regexp for this project."""
  current_year = int(input_api.time.strftime('%Y'))
  allowed_years = (str(s) for s in reversed(xrange(2011, current_year + 1)))
  years_re = '(' + '|'.join(allowed_years) + ')'
  license_header = (
    r'.*? Copyright %(year)s The LUCI Authors\. '
      r'All rights reserved\.\n'
    r'.*? Use of this source code is governed under the Apache License, '
      r'Version 2\.0\n'
    r'.*? that can be found in the LICENSE file\.(?: \*/)?\n'
  ) % {
    'year': years_re,
  }
  return license_header


def CommonChecks(input_api, output_api):
  results = []

  results.extend(input_api.canned_checks.PanProjectChecks(
      input_api, output_api, license_header=header(input_api),
      excluded_paths=[
          r'.+_pb2\.py',
      ],
  ))

  results.extend(input_api.RunTests(
      input_api.canned_checks.GetUnitTestsInDirectory(
          input_api, output_api, 'unittests', whitelist=[r'.+_test\.py']) +
      input_api.canned_checks.CheckVPythonSpec(input_api, output_api)
  ))

  return results


CheckChangeOnUpload = CommonChecks
CheckChangeOnCommit = CommonChecks