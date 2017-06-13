#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import contextlib
import datetime
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import StringIO

import test_env

import libs.logdog.stream
import libs.logdog.varint
from google.protobuf import json_format as jsonpb
from recipe_engine import recipe_api
from recipe_engine import stream_logdog


import annotations_pb2 as pb


@contextlib.contextmanager
def tempdir():
  tdir = tempfile.mkdtemp(suffix='stream_logdog_test', dir=test_env.BASE_DIR)
  try:
    yield tdir
  finally:
    shutil.rmtree(tdir)


def _translate_annotation_datagram(dg):
  """Translate annotation datagram binary data into a Python dict modeled after
  the JSONPB projection of the datagram.

  This is chosen because it allows for easy idiomatic equality assertions in
  test cases.

  Args:
    dg (str): The serialized annotation pb.Step datagram.
  """
  msg = pb.Step()
  msg.ParseFromString(dg)
  return json.loads(jsonpb.MessageToJson(msg))


class _TestStreamClient(libs.logdog.stream.StreamClient):
  """A testing StreamClient that retains all data written to it."""

  class Stream(object):
    """A file-like object that is explicitly aware of LogDog stream protocol."""

    def __init__(self, stream_client):
      self._client = stream_client
      self._buf = StringIO.StringIO()
      self._header = None
      self._final_data = None
      self._data_offset = None

    def write(self, data):
      self._buf.write(data)
      self._attempt_registration()

    def close(self):
      # If we never parsed our header, register that we are incomplete.
      if self._header is None:
        self._client._register_incomplete(self)

      self._final_data = self.data
      self._buf.close()

    @contextlib.contextmanager
    def _read_from(self, offset):
      # Seek to the specified offset.
      self._buf.seek(offset, mode=0)
      try:
        yield self._buf
      finally:
        # Seek back to  he end of the stream so future writes will append.
        self._buf.seek(0, mode=2)

    def _attempt_registration(self):
      # Only need to register once.
      if self._header is not None:
        return

      # Can we parse a full LogDog stream header?
      #
      # This means pulling:
      # - The LogDog Butler header.
      # - The header size varint.
      # - The header JSON blob, which needs to be decoded.
      with self._read_from(0) as fd:
        # Read 'result' bytes.
        magic_data = fd.read(len(libs.logdog.stream.BUTLER_MAGIC))
        if len(magic_data) != len(libs.logdog.stream.BUTLER_MAGIC):
          # Incomplete magic number, cannot complete registration.
          return
        count = len(magic_data)

        try:
          size, varint_count = libs.logdog.varint.read_uvarint(fd)
        except ValueError:
          # Incomplete varint, cannot complete registration.
          return
        count += varint_count

        header_data = fd.read(size)
        if len(header_data) != size:
          # Incomplete header, cannot complete registration.
          return
        count += size

        # Parse the header as JSON.
        self._header = json.loads(header_data)
        self._data_offset = count # (varint + header size)
        self._client._register_stream(self, self._header)

    @property
    def data(self):
      # If we have already cached our data (on close), return it directly.
      if self._final_data is not None:
        return self._final_data

      # Load our data from our live buffer.
      if self._data_offset is None:
        # No header has been read, so there is no data.
        return None
      with self._read_from(self._data_offset) as fd:
        return fd.read()


  _StreamEntry = collections.namedtuple('_StreamEntry', (
      's', 'type', 'content_type'))

  _DATAGRAM_CONTENT_TRANSLATE = {
      stream_logdog.ANNOTATION_CONTENT_TYPE: _translate_annotation_datagram,
  }


  def __init__(self):
    super(_TestStreamClient, self).__init__()
    self.streams = {}
    self.incomplete = []
    self.unregistered = {}

  @classmethod
  def _create(cls, value):
    raise NotImplementedError('Instances must be created manually.')

  def _connect_raw(self):
    s = self.Stream(self)
    self.unregistered[id(s)] = s
    return s

  def get(self, name):
    se = self.streams[name]
    data = se.s.data

    if se.type == libs.logdog.stream.StreamParams.TEXT:
      # Return text stream data as a list of lines. We use unicode because it
      # fits in with the JSON dump from 'all_streams'.
      return [unicode(l) for l in data.splitlines()]
    elif se.type == libs.logdog.stream.StreamParams.BINARY:
      raise NotImplementedError('No support for fetching binary stream data.')
    elif se.type == libs.logdog.stream.StreamParams.DATAGRAM:
      # Return datagram stream data as a list of datagrams.
      sio = StringIO.StringIO(data)
      datagrams = []
      while sio.tell() < sio.len:
        size, _ = libs.logdog.varint.read_uvarint(sio)
        dg = sio.read(size)
        if len(dg) != size:
          raise ValueError('Incomplete datagram (%d != %d)' % (len(dg), size))

        # If this datagram is a known type (e.g., protobuf), transform it into
        # JSONPB.
        translator = self._DATAGRAM_CONTENT_TRANSLATE.get(se.content_type)
        if translator is not None:
          dg = translator(dg)
        datagrams.append(dg)

      sio.close()
      return dg
    else:
      raise ValueError('Unknown stream type [%s]' % (se.type,))

  def all_streams(self):
    return dict((name, self.get(name)) for name in self.streams.iterkeys())

  @property
  def stream_names(self):
    return set(self.streams.iterkeys())

  def _remove_from_unregistered(self, s):
    if id(s) not in self.unregistered:
      raise KeyError('Stream is not known to be unregistered.')
    del(self.unregistered[id(s)])

  def _register_stream(self, s, header):
    name = header.get('name')
    if name in self.streams:
      raise KeyError('Duplicate stream [%s]' % (name,))

    self._remove_from_unregistered(s)
    self.streams[name] = self._StreamEntry(
        s=s,
        type=header['type'],
        content_type=header.get('contentType'),
    )

  def _register_incomplete(self, s):
    self._remove_from_unregistered(s)
    self.incomplete.append(s)


class EnvironmentTest(unittest.TestCase):
  """Simple test to assert that _Environment, which is stubbed during our tests,
  actually works."""

  def testRealEnvironment(self):
    stream_logdog._Environment.real()


class StreamEngineTest(unittest.TestCase):

  def setUp(self):
    self.client = _TestStreamClient()
    self.now = datetime.datetime(2106, 6, 12, 1, 2, 3)
    self.env = stream_logdog._Environment(
        now_fn=lambda: self.now,
        argv=[],
        environ={},
        cwd=None,
    )
    self.maxDiff = 1024*1024


  @contextlib.contextmanager
  def _new_stream_engine(self, **kwargs):
    kwargs.setdefault('client', self.client)
    kwargs.setdefault('environment', self.env)

    # Initialize and open a StreamEngine.
    se = stream_logdog.StreamEngine(**kwargs)
    se.open()
    yield se

    # Close the StreamEngine after we're done with it.
    self._advance_time()
    se.close()

  @contextlib.contextmanager
  def _step_stream(self, se, **kwargs):
    # Initialize and yield a new step stream.
    self._advance_time()
    step_stream = se.new_step_stream(recipe_api.StepClient.StepConfig(**kwargs))
    yield step_stream

    # Close the step stream when we're done with it.
    self._advance_time()
    step_stream.close()

  @contextlib.contextmanager
  def _log_stream(self, step_stream, name):
    # Initialize and yield a new log stream.
    log_stream = step_stream.new_log_stream(name)
    yield log_stream

    # Close the log stream when we're done with it.
    log_stream.close()

  def _advance_time(self):
    self.now += datetime.timedelta(seconds=1)

  def testEmptyStreamEngine(self):
    self.env.argv = ['fake_program', 'arg0', 'arg1']
    self.env.environ['foo'] = 'bar'
    self.env.cwd = 'CWD'

    with self._new_stream_engine() as se:
      pass

    self.assertEqual(self.client.all_streams(), {
        u'annotations': {
            u'name': u'steps',
            u'status': u'SUCCESS',
            u'started': u'2106-06-12T01:02:03Z',
            u'ended': u'2106-06-12T01:02:04Z',
            u'command': {
              u'commandLine': [u'fake_program', u'arg0', u'arg1'],
              u'cwd': u'CWD',
              u'environ': {u'foo': u'bar'},
            },
        },
    })

  def testIncrementalUpdates(self):
    self.env.argv = ['fake_program', 'arg0', 'arg1']
    self.env.environ['foo'] = 'bar'
    self.env.cwd = 'CWD'

    # Create a StreamEngine with an update interval that will trigger each time
    # _advance_time is called.
    with self._new_stream_engine(
        update_interval=datetime.timedelta(seconds=1)) as se:
      # Initial stream state (no steps).
      self.assertEqual(self.client.all_streams(), {
          u'annotations': {
              u'name': u'steps',
              u'started': u'2106-06-12T01:02:03Z',
              u'command': {
                u'commandLine': [u'fake_program', u'arg0', u'arg1'],
                u'cwd': u'CWD',
                u'environ': {u'foo': u'bar'},
              },
          },
      })

      with self._step_stream(se, name='foo') as st:
        pass

      # Stream state (foo).
      self.assertEqual(self.client.all_streams(), {
          u'annotations': {
              u'name': u'steps',
              u'started': u'2106-06-12T01:02:03Z',
              u'command': {
                u'commandLine': [u'fake_program', u'arg0', u'arg1'],
                u'cwd': u'CWD',
                u'environ': {u'foo': u'bar'},
              },

              u'substep': [

                {u'step': {
                  u'name': u'foo',
                  u'status': u'SUCCESS',
                  u'started': u'2106-06-12T01:02:04Z',
                  u'ended': u'2106-06-12T01:02:05Z',
                }},
              ],
          },
      })

      with self._step_stream(se, name='bar') as st:
        pass

      # Stream state (bar).
      self.assertEqual(self.client.all_streams(), {
          u'annotations': {
              u'name': u'steps',
              u'started': u'2106-06-12T01:02:03Z',
              u'command': {
                u'commandLine': [u'fake_program', u'arg0', u'arg1'],
                u'cwd': u'CWD',
                u'environ': {u'foo': u'bar'},
              },

              u'substep': [

                {u'step': {
                  u'name': u'foo',
                  u'status': u'SUCCESS',
                  u'started': u'2106-06-12T01:02:04Z',
                  u'ended': u'2106-06-12T01:02:05Z',
                }},

                {u'step': {
                  u'name': u'bar',
                  u'status': u'SUCCESS',
                  u'started': u'2106-06-12T01:02:06Z',
                  u'ended': u'2106-06-12T01:02:07Z',
                }},
              ],
          },
      })

    # Final stream state.
    self.assertEqual(self.client.all_streams(), {
        u'annotations': {
            u'name': u'steps',
            u'status': u'SUCCESS',
            u'started': u'2106-06-12T01:02:03Z',
            u'ended': u'2106-06-12T01:02:08Z',
            u'command': {
              u'commandLine': [u'fake_program', u'arg0', u'arg1'],
              u'cwd': u'CWD',
              u'environ': {u'foo': u'bar'},
            },

            u'substep': [

              {u'step': {
                u'name': u'foo',
                u'status': u'SUCCESS',
                u'started': u'2106-06-12T01:02:04Z',
                u'ended': u'2106-06-12T01:02:05Z',
              }},

              {u'step': {
                u'name': u'bar',
                u'status': u'SUCCESS',
                u'started': u'2106-06-12T01:02:06Z',
                u'ended': u'2106-06-12T01:02:07Z',
              }},
            ],
        },
    })

  def testDumpFinalState(self):
    self.env.argv = ['fake_program', 'arg0', 'arg1']
    self.env.environ['foo'] = 'bar'
    self.env.cwd = 'CWD'

    # Create a StreamEngine with an update interval that will trigger each time
    # _advance_time is called.
    with tempdir() as tdir:
      dump_path = os.path.join(tdir, 'dump.bin')
      with self._new_stream_engine(
          update_interval=datetime.timedelta(seconds=1),
          dump_path=dump_path) as se:
        # Initial stream state (no steps).
        self.assertEqual(self.client.all_streams(), {
            u'annotations': {
                u'name': u'steps',
                u'started': u'2106-06-12T01:02:03Z',
                u'command': {
                  u'commandLine': [u'fake_program', u'arg0', u'arg1'],
                  u'cwd': u'CWD',
                  u'environ': {u'foo': u'bar'},
                },
            },
        })

      with open(dump_path, 'rb') as fd:
        step = _translate_annotation_datagram(fd.read())
      self.assertEqual(step, {
            u'name': u'steps',
            u'status': u'SUCCESS',
            u'started': u'2106-06-12T01:02:03Z',
            u'ended': u'2106-06-12T01:02:04Z',
            u'command': {
              u'commandLine': [u'fake_program', u'arg0', u'arg1'],
              u'cwd': u'CWD',
              u'environ': {u'foo': u'bar'},
            },
        })

  def testBasicStream(self):
    self.env.argv = ['fake_program', 'arg0', 'arg1']
    self.env.environ['foo'] = 'bar'
    self.env.cwd = 'CWD'

    with self._new_stream_engine(name_base='test/base') as se:
      with self._step_stream(se,
          name='first step',
          cmd=['first', 'step'],
          cwd='FIRST_CWD') as step:
        step.add_step_text('Sup')
        step.add_step_text('Dawg?')
        step.write_line('STDOUT for first step.')
        step.write_line('(Another line)')
        step.add_step_summary_text('Everything is great.')
        step.add_step_link('example 1', 'http://example.com/1')
        step.add_step_link('example 2', 'http://example.com/2')
        step.set_step_status('SUCCESS')

      with self._step_stream(se, name='second step') as step:
        step.set_step_status('SUCCESS')
        step.write_split('multiple\nlines\nof\ntext')

        # Create two log streams with the same name to test indexing.
        #
        # Note that "log stream" is an invalid LogDog stream name, so this
        # will also test normalization.
        with self._log_stream(step, 'log stream') as ls:
          ls.write_split('foo\nbar\nbaz\n')
        with self._log_stream(step, 'log stream') as ls:
          ls.write_split('qux\nquux\n')

      # This is a different stream name, but will normalize to the same log
      # stream name as 'second/step', so this will test that we disambiguate
      # the log stream names.
      with self._step_stream(se, name='second/step') as step:
        pass

    self.assertEqual(self.client.all_streams(), {
        u'test/base/annotations': {
          u'name': u'steps',
          u'status': u'SUCCESS',
          u'started': u'2106-06-12T01:02:03Z',
          u'ended': u'2106-06-12T01:02:10Z',
          u'command': {
            u'commandLine': [u'fake_program', u'arg0', u'arg1'],
            u'cwd': u'CWD',
            u'environ': {u'foo': u'bar'},
          },
          u'substep': [

            {u'step': {
              u'name': u'first step',
              u'status': u'SUCCESS',
              u'started': u'2106-06-12T01:02:04Z',
              u'ended': u'2106-06-12T01:02:05Z',
              u'command': {
                u'commandLine': [u'first', u'step'],
                u'cwd': u'FIRST_CWD',
              },
              u'stdoutStream': {
                  u'name': u'test/base/steps/first_step/stdout',
              },
              u'text': [u'Everything is great.', u'Sup', u'Dawg?'],
              u'otherLinks': [
                {
                  u'label': u'example 1',
                  u'url': u'http://example.com/1',
                },
                {
                  u'label': u'example 2',
                  u'url': u'http://example.com/2',
                },
              ],
            }},

            {u'step': {
              u'name': u'second step',
              u'status': u'SUCCESS',
              u'started': u'2106-06-12T01:02:06Z',
              u'ended': u'2106-06-12T01:02:07Z',
              u'stdoutStream': {
                  u'name': u'test/base/steps/second_step/stdout',
              },
              u'otherLinks': [
                {
                  u'label': u'log stream',
                  u'logdogStream': {
                    u'name': u'test/base/steps/second_step/logs/log_stream/0',
                  },
                },
                {
                  u'label': u'log stream',
                  u'logdogStream': {
                    u'name': u'test/base/steps/second_step/logs/log_stream/1',
                  },
                },
              ],
            }},

            {u'step': {
                u'name': u'second/step',
                u'status': u'SUCCESS',
                u'started': u'2106-06-12T01:02:08Z',
                u'ended': u'2106-06-12T01:02:09Z',
            }},
          ],
        },

        u'test/base/steps/first_step/stdout': [
          u'STDOUT for first step.',
          u'(Another line)',
        ],

        u'test/base/steps/second_step/stdout': [
          u'multiple',
          u'lines',
          u'of',
          u'text',
        ],

        u'test/base/steps/second_step/logs/log_stream/0': [
          u'foo',
          u'bar',
          u'baz',
        ],

        u'test/base/steps/second_step/logs/log_stream/1': [
          u'qux',
          u'quux',
        ],
    })

  def testWarningBasicStream(self):
    with self._new_stream_engine() as se:
      with self._step_stream(se, name='isuck') as step:
        step.add_step_summary_text('Something went wrong.')
        step.set_step_status('WARNING')

    self.assertEqual(self.client.all_streams(), {
        u'annotations': {
          u'name': u'steps',
          u'status': u'SUCCESS',
          u'started': u'2106-06-12T01:02:03Z',
          u'ended': u'2106-06-12T01:02:06Z',
          u'substep': [

            {u'step': {
              u'name': u'isuck',
              u'status': u'SUCCESS',
              u'failureDetails': {
                  u'text': u'Something went wrong.',
              },
              u'started': u'2106-06-12T01:02:04Z',
              u'ended': u'2106-06-12T01:02:05Z',
              u'text': [u'Something went wrong.'],
            }},
          ],
        },
    })

  def testFailedBasicStream(self):
    with self._new_stream_engine() as se:
      with self._step_stream(se, name='isuck') as step:
        step.add_step_summary_text('Oops I failed.')
        step.set_step_status('FAILURE')

      with self._step_stream(se, name='irock') as step:
        pass

    self.assertEqual(self.client.all_streams(), {
        u'annotations': {
          u'name': u'steps',
          u'status': u'FAILURE',
          u'started': u'2106-06-12T01:02:03Z',
          u'ended': u'2106-06-12T01:02:08Z',
          u'substep': [

            {u'step': {
              u'name': u'isuck',
              u'status': u'FAILURE',
              u'failureDetails': {
                  u'text': u'Oops I failed.',
              },
              u'started': u'2106-06-12T01:02:04Z',
              u'ended': u'2106-06-12T01:02:05Z',
              u'text': [u'Oops I failed.'],
            }},

            {u'step': {
              u'name': u'irock',
              u'status': u'SUCCESS',
              u'started': u'2106-06-12T01:02:06Z',
              u'ended': u'2106-06-12T01:02:07Z',
            }},
          ],
        },
    })

  def testNestedStream(self):
    with self._new_stream_engine() as se:
      # parent
      with self._step_stream(se, name='parent') as step:
        step.write_line('I am the parent.')

      # parent."child 1"
      with self._step_stream(se,
          name='child 1',
          nest_level=1) as step:
        step.write_line('I am child #1.')

      # parent."child 1"."grandchild"
      with self._step_stream(se,
          name='grandchild',
          nest_level=2) as step:
        step.write_line("I am child #1's child.")

      # parent."child 2". Mark this child as failed. This should not propagate
      # to the parent, since it has an explicit status.
      with self._step_stream(se,
          name='child 2',
          nest_level=1) as step:
        step.write_line('I am child #2.')

      # parent."child 2". Mark this child as failed. This should not propagate
      # to the parent, since it has an explicit status.
      with self._step_stream(se, name='friend') as step:
        step.write_line("I am the parent's friend.")

    self.assertEqual(self.client.all_streams(), {
        u'annotations': {
          u'name': u'steps',
          u'status': u'SUCCESS',
          u'started': u'2106-06-12T01:02:03Z',
          u'ended': u'2106-06-12T01:02:14Z',
          u'substep': [

            {u'step': {
              u'name': u'parent',
              u'status': u'SUCCESS',
              u'started': u'2106-06-12T01:02:04Z',
              u'ended': u'2106-06-12T01:02:05Z',
              u'stdoutStream': {
                  u'name': u'steps/parent/stdout',
              },
              u'substep': [

                {u'step': {
                  u'name': u'child 1',
                  u'status': u'SUCCESS',
                  u'started': u'2106-06-12T01:02:06Z',
                  u'ended': u'2106-06-12T01:02:07Z',
                  u'stdoutStream': {
                      u'name': u'steps/parent/steps/child_1/stdout',
                  },
                  u'substep': [

                    {u'step': {
                      u'name': u'grandchild',
                      u'status': u'SUCCESS',
                      u'started': u'2106-06-12T01:02:08Z',
                      u'ended': u'2106-06-12T01:02:09Z',
                      u'stdoutStream': {
                          u'name': u'steps/parent/steps/child_1/'
                                    'steps/grandchild/stdout',
                      },
                    }},
                  ],
                }},

                {u'step': {
                  u'name': u'child 2',
                  u'status': u'SUCCESS',
                  u'started': u'2106-06-12T01:02:10Z',
                  u'ended': u'2106-06-12T01:02:11Z',
                  u'stdoutStream': {
                      u'name': u'steps/parent/steps/child_2/stdout',
                  },
                }},
              ],
            }},

            {u'step': {
              u'name': u'friend',
              u'status': u'SUCCESS',
              u'started': u'2106-06-12T01:02:12Z',
              u'ended': u'2106-06-12T01:02:13Z',
              u'stdoutStream': {
                  u'name': u'steps/friend/stdout',
              },
            }},
          ],
        },

        u'steps/parent/stdout': [u'I am the parent.'],
        u'steps/parent/steps/child_1/stdout': [u'I am child #1.'],
        u'steps/parent/steps/child_1/steps/grandchild/stdout': [
            u"I am child #1's child."],
        u'steps/parent/steps/child_2/stdout': [u'I am child #2.'],
        u'steps/friend/stdout': [u"I am the parent's friend."],
    })

  def testTriggersRaiseException(self):
    with self._new_stream_engine() as se:
      with self._step_stream(se, name='trigger') as step:
        with self.assertRaises(NotImplementedError):
          step.trigger('trigger spec')

  def testTriggersIgnored(self):
    with self._new_stream_engine(ignore_triggers=True) as se:
      with self._step_stream(se, name='trigger') as step:
        step.trigger('trigger spec')

  def testNoSubannotations(self):
    with self._new_stream_engine(ignore_triggers=True) as se:
      with self.assertRaises(NotImplementedError):
        se.new_step_stream(recipe_api.StepClient.StepConfig(
            name='uses subannotations',
            allow_subannotations=True,
        ))

  def testInvalidStepStatusRaisesValueError(self):
    with self._new_stream_engine() as se:
      with self._step_stream(se, name='trigger') as step:
        with self.assertRaises(ValueError):
          step.set_step_status('OHAI')


class AnnotationMonitorTest(unittest.TestCase):
  """Tests the stream_logdog._AnnotationMonitor directly."""

  # A small timedelta, sufficient to block but fast enough to not make the
  # test slow.
  _SMALL_TIME_DELTA = datetime.timedelta(milliseconds=5)

  class _DatagramBuffer(object):

    def __init__(self):
      self.datagrams = []
      self.data_event = threading.Event()

    def send(self, dg):
      self.datagrams.append(dg)
      self.data_event.set()

    def __len__(self):
      return len(self.datagrams)

    @property
    def latest(self):
      if self.datagrams:
        return self.datagrams[-1]
      return None

    def wait_for_data(self):
      self.data_event.wait()
      self.data_event.clear()
      return self.latest


  def setUp(self):
    self.db = self._DatagramBuffer()
    self.now = datetime.datetime(2106, 6, 12, 1, 2, 3)
    self.env = stream_logdog._Environment(
        now_fn=lambda: self.now,
        argv=[],
        environ={},
        cwd=None,
    )

  @contextlib.contextmanager
  def _annotation_monitor(self, flush_period=None):
    # Use a really high flush period. This should never naturally trigger during
    # a test case.
    flush_period = flush_period or datetime.timedelta(hours=1)

    am = stream_logdog._AnnotationMonitor(self.env, self.db, flush_period)
    try:
      yield am
    finally:
      am.flush_and_join()

    with am._lock:
      # Assert that our timer has been shut down.
      self.assertIsNone(am._flush_timer)
      # Assert that there is no buffered data.
      self.assertIsNone(am._current_data)

  def testMonitorStartsAndJoinsWithNoData(self):
    with self._annotation_monitor() as am:
      pass

    # No datagrams should have been sent.
    self.assertIsNone(self.db.latest)
    self.assertEqual(len(self.db.datagrams), 0)

  def testMonitorBuffersAndSendsData(self):
    with self._annotation_monitor() as am:
      # The first piece of data should have been immediately sent.
      am.signal_update('initial')
      self.assertEqual(self.db.wait_for_data(), 'initial')

      # Subsequent iterations should not send data, but should start the flush
      # timer and buffer the latest data.
      with am._lock:
        self.assertIsNone(am._flush_timer)
      for i in xrange(10):
        am.signal_update('test%d' % (i,))
        time.sleep(self._SMALL_TIME_DELTA.total_seconds())
      with am._lock:
        self.assertEqual(am._current_data, 'test9')
        self.assertIsNotNone(am._flush_timer)

      # Pretend the timer triggered. We should receive the latest buffered data.
      am._flush_timer_expired()
      self.assertEqual(self.db.wait_for_data(), 'test9')
      with am._lock:
        # No more timer or buffered data.
        self.assertIsNone(am._flush_timer)
        self.assertIsNone(am._current_data)

      # Send one last chunk of data, but don't let the timer expire. This will
      # be sent on final flush.
      am.signal_update('final')
      with am._lock:
        self.assertIsNotNone(am._flush_timer)

    # Assert that the final chunk of data was sent.
    self.assertEqual(self.db.latest, 'final')

    # Only three datagrams should have been sent.
    self.assertEqual(len(self.db.datagrams), 3)

  def testMonitorIgnoresDuplicateData(self):
    with self._annotation_monitor() as am:
      # Get initial data out of the way.
      am.signal_update('initial')
      self.assertEqual(self.db.wait_for_data(), 'initial')

      # Send the same thing. It should not be buffered.
      am.signal_update('initial')
      with am._lock:
        self.assertIsNone(am._flush_timer)
        self.assertIsNone(am._current_data)

    # Only one datagrams should have been sent.
    self.assertEqual(len(self.db.datagrams), 1)

  def testStructuralUpdateSendsImmediately(self):
    with self._annotation_monitor() as am:
      # Get initial data out of the way.
      am.signal_update('initial')
      self.assertEqual(self.db.wait_for_data(), 'initial')

      # Send a structural update. It should send immediately.
      am.signal_update('test', structural=True)
      self.assertEqual(self.db.wait_for_data(), 'test')

      # Send a duplicate structural update. It should be ignored.
      am.signal_update('test', structural=True)
      with am._lock:
        self.assertIsNone(am._flush_timer)
        self.assertIsNone(am._current_data)

    # Only two datagrams should have been sent.
    self.assertEqual(len(self.db.datagrams), 2)

  def testFlushesPeriodically(self):
    with self._annotation_monitor(flush_period=self._SMALL_TIME_DELTA) as am:
      # Get initial data out of the way.
      am.signal_update('initial')
      self.assertEqual(self.db.wait_for_data(), 'initial')

      # Send a structural update. It should send immediately.
      am.signal_update('test')
      self.assertEqual(self.db.wait_for_data(), 'test')

    # Only two datagrams should have been sent.
    self.assertEqual(len(self.db.datagrams), 2)


class AnnotationStateTest(unittest.TestCase):
  """Tests the stream_logdog._AnnotationState directly."""

  def setUp(self):
    self.env = stream_logdog._Environment(
        None,
        argv=['command', 'arg0', 'arg1'],
        cwd='path/to/cwd',
        environ={
          'foo': 'bar',
          'FOO': 'baz',
        },
    )
    self.astate = stream_logdog._AnnotationState.create(
        stream_logdog._StreamName('strean/name'),
        environment=self.env,
        properties={'foo': 'bar'},
    )

  def testFirstCheckReturnsData(self):
    # The first check should return data.
    self.assertIsNotNone(self.astate.check())
    # The second will, since nothing has changed.
    self.assertIsNone(self.astate.check())

  def testCanCreateAndGetStep(self):
    # Root step.
    base = self.astate.base
    self.astate.create_step(recipe_api.StepClient.StepConfig(name='first'))
    self.assertEqual(len(base.substep), 1)
    self.assertEqual(base.substep[0].step.name, 'first')
    self.assertIsNotNone(self.astate.check())

    # Child step.
    self.astate.create_step(recipe_api.StepClient.StepConfig(
      name='first child',
      nest_level=1))
    self.assertEqual(len(base.substep), 1)
    self.assertEqual(len(base.substep[0].step.substep), 1)
    self.assertEqual(base.substep[0].step.substep[0].step.name, 'first child')
    self.assertIsNotNone(self.astate.check())

    # Sibling step to 'first'.
    self.astate.create_step(recipe_api.StepClient.StepConfig(name='second'))
    self.assertEqual(len(base.substep), 2)
    self.assertEqual(base.substep[1].step.name, 'second')
    self.assertIsNotNone(self.astate.check())

  def testCanUpdateProperties(self):
    self.astate.update_properties(foo='baz', qux='quux')
    self.assertEqual(list(self.astate.base.property), [
        pb.Step.Property(name='foo', value='baz'),
        pb.Step.Property(name='qux', value='quux'),
    ])


class StreamNameTest(unittest.TestCase):
  """Tests the stream_logdog._StreamName directly."""

  def testEmptyStreamNameRaisesValueError(self):
    sn = stream_logdog._StreamName(None)
    with self.assertRaises(ValueError):
      str(sn)

  def testInvalidBaseRaisesValueError(self):
    with self.assertRaises(ValueError):
      stream_logdog._StreamName('!!! invalid !!!')

  def testAppendComponents(self):
    sn = stream_logdog._StreamName('base')
    self.assertEqual(str(sn.append()), 'base')
    self.assertEqual(str(sn.append('foo')), 'base/foo')
    self.assertEqual(str(sn.append('foo', 'bar')), 'base/foo/bar')
    self.assertEqual(str(sn.append('foo', 'bar/baz')), 'base/foo/bar_baz')

  def testAugment(self):
    sn = stream_logdog._StreamName('base')
    self.assertEqual(str(sn.augment('')), 'base')
    self.assertEqual(str(sn.augment('foo')), 'basefoo')
    self.assertEqual(str(sn.augment('foo/bar baz')), 'basefoo_bar_baz')

  def testAppendInvalidStreamNameNormalizes(self):
    sn = stream_logdog._StreamName('base')
    sn = sn.append('#!!! stream name !!!')
    self.assertEqual(str(sn), 'base/s______stream_name____')

  def testAugmentInvalidStreamNameNormalizes(self):
    sn = stream_logdog._StreamName('base')
    self.assertEqual(str(sn.augment(' !!! other !!! ')), 'base_____other_____')


if __name__ == '__main__':
  unittest.main()
