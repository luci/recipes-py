# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PRESUBMIT_VERSION = '2.0.0'

# This line is 'magic' in that git-cl looks for it to decide whether to
# use Python3 instead of Python2 when running the code in this file.
USE_PYTHON3 = True


def header(input_api):
  """Returns the expected license header regexp for this project."""
  current_year = int(input_api.time.strftime('%Y'))
  allowed_years = (str(s) for s in reversed(range(2011, current_year + 1)))
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


def CheckCommon(input_api, output_api):
  return input_api.canned_checks.PanProjectChecks(
      input_api, output_api, license_header=header(input_api),
      excluded_paths=[
          r'.+_pb2\.py',
      ],
  )


def CheckPatchFormatted(input_api, output_api):
  return input_api.canned_checks.CheckPatchFormatted(
      input_api, output_api, check_clang_format=False)


def CheckDevVpythonMatches(input_api, output_api):
  affected_files = input_api.AffectedTestableFiles(
      lambda f: f.LocalPath().endswith('.vpython'))
  results = []
  if affected_files:
    root = input_api.PresubmitLocalPath()
    vpy3 = input_api.ReadFile(input_api.os_path.join(root, '.vpython3'))
    for debugger in ('vscode', 'pycharm'):
      devvpy3 = input_api.ReadFile(
          input_api.os_path.join(root, f'./.{debugger}.vpython3'))
      if not devvpy3.startswith(vpy3):
        results.append(
            output_api.PresubmitError(
                f'.{debugger}.vpython3 does not have the contents of .vpython3 as a prefix.'
            ))
  return results


def CheckIntegrationTests(input_api, output_api):
  results = []
  # Explicitly run these independently because they update files on disk and are
  # called implicitly with the other tests. The vpython check is nominally
  # locked with a file lock, but updating the protos, etc. of recipes.py is not.
  recipes_py = input_api.os_path.join(
      input_api.PresubmitLocalPath(), 'recipes.py')
  run_first = (
    input_api.canned_checks.CheckVPythonSpec(input_api, output_api) + [
      input_api.Command(
          'Compile recipe protos',
          ['python3', recipes_py, 'fetch'],
          {},
          output_api.PresubmitError,
      ),
    ])

  for cmd in run_first:
    result = input_api.thread_pool.CallCommand(cmd)
    if result:
      results.append(result)

  # Now run all the unit tests except run_test in parallel and then run run_test
  # separately. The reason is that run_test depends on the wall clock on the
  # host and if the host gets busy, the tests are likely to be flaky.
  results.extend(
      input_api.RunTests(
          input_api.canned_checks.GetUnitTestsInDirectory(
              input_api,
              output_api,
              'unittests',
              files_to_check=[r'.+_test\.py'],
              files_to_skip=[r'run_test\.py'],
              run_on_python2=False,
              run_on_python3=True,
          )))

  results.extend(
      input_api.RunTests(
          input_api.canned_checks.GetUnitTestsInDirectory(
              input_api,
              output_api,
              'unittests',
              files_to_check=[r'run_test\.py'],
              run_on_python2=False,
              run_on_python3=True,
          )))
  return results
