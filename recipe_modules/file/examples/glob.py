# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "file",
  "path",
  "json",
]

def RunSteps(api):
  sd = api.path.start_dir

  api.file.ensure_directory('mkdir a', sd / 'a')
  api.file.ensure_directory('mkdir b', sd / 'b')

  for fname in ['thing.pat', 'other.pat', 'something', 'file', '.hidden.pat']:
    api.file.write_text("write %s" % fname, sd / fname, 'data')
    api.file.write_text("write a/%s" % fname, sd / 'a' / fname, 'data')
    api.file.write_text("write b/%s" % fname, sd / 'b' / fname, 'data')

  hits = api.file.glob_paths("pat", sd, '*.pat', test_data=['thing.pat', 'other.pat'])
  assert hits == [sd / 'other.pat', sd / 'thing.pat'], hits

  hits = api.file.glob_paths("noop", sd, '*.nop', test_data=[])
  assert hits == [], hits

  hits = api.file.glob_paths("thing", sd, '*thing*', test_data=['thing.pat', 'something'])
  assert hits == [sd / 'something', sd / 'thing.pat'], hits

  hits = api.file.glob_paths("nest", sd, '*/*.pat', test_data=[
    'a/other.pat', 'b/thing.pat', 'b/other.pat', 'a/thing.pat',
  ])
  assert hits == [sd / 'a' / 'other.pat', sd / 'a' / 'thing.pat',
                  sd / 'b' / 'other.pat', sd / 'b' / 'thing.pat'], hits

  hits = api.file.glob_paths("recursive", sd, '**/*.pat', test_data=[
    'thing.pat', 'other.pat', 'a/other.pat', 'b/thing.pat',
    'b/other.pat', 'a/thing.pat',
  ])
  assert hits == [sd / 'a' / 'other.pat', sd / 'a' / 'thing.pat',
                  sd / 'b' / 'other.pat', sd / 'b' / 'thing.pat',
                  sd / 'other.pat', sd / 'thing.pat'], hits

  hits = api.file.glob_paths("hidden", sd, '*.pat', include_hidden=True, test_data=[
    '.hidden.pat', 'thing.pat', 'other.pat'])
  assert hits == [sd / '.hidden.pat', sd / 'other.pat',
                  sd / 'thing.pat'], hits


def GenTests(api):
  yield api.test('basic')
