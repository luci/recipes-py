# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "file",
  "path",
  "json",
]

def RunSteps(api):
  sd = api.path['start_dir']

  api.file.ensure_directory('mkdir a', sd.join('a'))
  api.file.ensure_directory('mkdir b', sd.join('b'))

  for fname in ['thing.pat', 'other.pat', 'something', 'file']:
    api.file.write_text("write %s" % fname, sd.join(fname), 'data')
    api.file.write_text("write a/%s" % fname, sd.join('a', fname), 'data')
    api.file.write_text("write b/%s" % fname, sd.join('b', fname), 'data')

  hits = api.file.glob_paths("pat", sd, '*.pat', ['thing.pat', 'other.pat'])
  assert hits == [sd.join('other.pat'), sd.join('thing.pat')], hits

  hits = api.file.glob_paths("noop", sd, '*.nop', [])
  assert hits == [], hits

  hits = api.file.glob_paths("thing", sd, '*thing*', ['thing.pat', 'something'])
  assert hits == [sd.join('something'), sd.join('thing.pat')], hits

  hits = api.file.glob_paths("nest", sd, '*/*.pat', [
    'a/other.pat', 'b/thing.pat', 'b/other.pat', 'a/thing.pat',
  ])
  assert hits == [sd.join('a', 'other.pat'), sd.join('a', 'thing.pat'),
                  sd.join('b', 'other.pat'), sd.join('b', 'thing.pat')], hits


def GenTests(api):
  yield api.test('basic')

