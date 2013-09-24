def convert_trie_to_flat_paths(trie, prefix=None):
  # Cloned from webkitpy.layout_tests.layout_package.json_results_generator
  # so that this code can stand alone.
  result = {}
  for name, data in trie.iteritems():
    if prefix:
      name = prefix + "/" + name

    if len(data) and not "actual" in data and not "expected" in data:
      result.update(convert_trie_to_flat_paths(data, name))
    else:
      result[name] = data

  return result


class TestResults(object):
  def __init__(self, jsonish=None):
    self.raw = jsonish or {}

    self.tests = convert_trie_to_flat_paths(self.raw.get('tests', {}))
    self.passes = {}
    self.unexpected_passes = {}
    self.failures = {}
    self.unexpected_failures = {}
    self.flakes = {}
    self.unexpected_flakes = {}

    for (test, result) in self.tests.iteritems():
      key = 'unexpected_' if result.get('is_unexpected') else ''
      actual_result = result['actual']
      data = actual_result
      if ' PASS' in actual_result:
        key += 'flakes'
      elif actual_result == 'PASS':
        key += 'passes'
        data = result
      else:
        key += 'failures'
      getattr(self, key)[test] = data

  def __getattr__(self, key):
    if key in self.raw:
      return self.raw[key]
    raise AttributeError("'%s' object has no attribute '%s'" %
                         (self.__class__, key))  # pragma: no cover

  def add_result(self, name, expected, actual=None):
    """Adds a test result to a 'json test results' compatible object.
    Args:
      name - A full test name delimited by '/'. ex. 'some/category/test.html'
      expected - The string value for the 'expected' result of this test.
      actual (optional) - If not None, this is the actual result of the test.
                          Otherwise this will be set equal to expected.

    The test will also get an 'is_unexpected' key if actual != expected.
    """
    actual = actual or expected
    entry = self.tests
    for token in name.split('/'):
      entry = entry.setdefault(token, {})
    entry['expected'] = expected
    entry['actual'] = actual
    if expected != actual:
      entry['is_unexpected'] = True

  def as_jsonish(self):
    ret = self.raw.copy()
    ret.setdefault('tests', {}).update(self.tests)
    return ret

