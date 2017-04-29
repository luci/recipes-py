#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tool to interact with recipe repositories.

This tool operates on the nearest ancestor directory containing an
infra/config/recipes.cfg.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile

# This is necessary to ensure that str literals are by-default assumed to hold
# utf-8. It also makes the implicit str(unicode(...)) act like
# unicode(...).encode('utf-8'), rather than unicode(...).encode('ascii') .
reload(sys)
sys.setdefaultencoding('UTF8')

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from recipe_engine import env

import argparse  # this is vendored
from recipe_engine import arguments_pb2
from recipe_engine import util as recipe_util
from google.protobuf import json_format as jsonpb


def handle_recipe_return(recipe_result, result_filename, stream_engine,
                         engine_flags):
  if engine_flags and engine_flags.use_result_proto:
    return new_handle_recipe_return(
        recipe_result, result_filename, stream_engine)

  if 'recipe_result' in recipe_result.result:
    result_string = json.dumps(
        recipe_result.result['recipe_result'], indent=2)
    if result_filename:
      with open(result_filename, 'w') as f:
        f.write(result_string)
    with stream_engine.make_step_stream('recipe result') as s:
      with s.new_log_stream('result') as l:
        l.write_split(result_string)

  if 'traceback' in recipe_result.result:
    with stream_engine.make_step_stream('Uncaught Exception') as s:
      with s.new_log_stream('exception') as l:
        for line in recipe_result.result['traceback']:
          l.write_line(line)

  if 'reason' in recipe_result.result:
    with stream_engine.make_step_stream('Failure reason') as s:
      with s.new_log_stream('reason') as l:
        for line in recipe_result.result['reason'].splitlines():
          l.write_line(line)

  if 'status_code' in recipe_result.result:
    return recipe_result.result['status_code']
  else:
    return 0

def new_handle_recipe_return(result, result_filename, stream_engine):
  if result_filename:
    with open(result_filename, 'w') as fil:
      fil.write(jsonpb.MessageToJson(
          result, including_default_value_fields=True))

  if result.json_result:
    with stream_engine.make_step_stream('recipe result') as s:
      with s.new_log_stream('result') as l:
        l.write_split(result.json_result)

  if result.HasField('failure'):
    f = result.failure
    if f.HasField('exception'):
      with stream_engine.make_step_stream('Uncaught Exception') as s:
        s.add_step_text(f.human_reason)
        with s.new_log_stream('exception') as l:
          for line in f.exception.traceback:
            l.write_line(line)
    # TODO(martiniss): Remove this code once calling code handles these states
    elif f.HasField('timeout'):
      with stream_engine.make_step_stream('Step Timed Out') as s:
        with s.new_log_stream('timeout_s') as l:
          l.write_line(f.timeout.timeout_s)
    elif f.HasField('step_data'):
      with stream_engine.make_step_stream('Invalid Step Data Access') as s:
        with s.new_log_stream('step') as l:
          l.write_line(f.step_data.step)

    with stream_engine.make_step_stream('Failure reason') as s:
      with s.new_log_stream('reason') as l:
        l.write_split(f.human_reason)

    return 1

  return 0


def run(config_file, package_deps, args):
  from recipe_engine import run as recipe_run
  from recipe_engine import loader
  from recipe_engine import step_runner
  from recipe_engine import stream
  from recipe_engine import stream_logdog

  if args.props:
    for p in args.props:
      args.properties.update(p)

  def get_properties_from_operational_args(op_args):
    if not op_args.properties.property:
      return None
    return _op_properties_to_dict(op_args.properties.property)

  op_args = args.operational_args
  op_properties = get_properties_from_operational_args(op_args)
  if args.properties and op_properties:
    raise ValueError(
      'Got operational args properties as well as CLI properties.')

  properties = op_properties
  if not properties:
    properties = args.properties

  properties['recipe'] = args.recipe

  properties = recipe_util.strip_unicode(properties)

  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'

  universe_view = loader.UniverseView(
      loader.RecipeUniverse(
          package_deps, config_file), package_deps.root_package)

  workdir = (args.workdir or
      os.path.join(os.path.dirname(os.path.realpath(__file__)), 'workdir'))
  logging.info('Using %s as work directory' % workdir)
  if not os.path.exists(workdir):
    os.makedirs(workdir)

  old_cwd = os.getcwd()
  os.chdir(workdir)

  # Construct our stream engines. We may want to share stream events with more
  # than one StreamEngine implementation, so we will accumulate them in a
  # "stream_engines" list and compose them into a MultiStreamEngine.
  def build_annotation_stream_engine():
    return stream.AnnotatorStreamEngine(
        sys.stdout,
        emit_timestamps=(args.timestamps or
                         op_args.annotation_flags.emit_timestamp))

  stream_engines = []
  if op_args.logdog.streamserver_uri:
    logging.debug('Using LogDog with parameters: [%s]', op_args.logdog)
    stream_engines.append(stream_logdog.StreamEngine(
        streamserver_uri=op_args.logdog.streamserver_uri,
        name_base=(op_args.logdog.name_base or None),
        dump_path=op_args.logdog.final_annotation_dump_path,
    ))

    # If we're teeing, also fold in a standard annotation stream engine.
    if op_args.logdog.tee:
      stream_engines.append(build_annotation_stream_engine())
  else:
    # Not using LogDog; use a standard annotation stream engine.
    stream_engines.append(build_annotation_stream_engine())
  multi_stream_engine = stream.MultiStreamEngine.create(*stream_engines)

  emit_initial_properties = op_args.annotation_flags.emit_initial_properties
  engine_flags = op_args.engine_flags

  # Have a top-level set of invariants to enforce StreamEngine expectations.
  with stream.StreamEngineInvariants.wrap(multi_stream_engine) as stream_engine:
    try:
      ret = recipe_run.run_steps(
          properties, stream_engine,
          step_runner.SubprocessStepRunner(stream_engine, engine_flags),
          universe_view, engine_flags=engine_flags,
          emit_initial_properties=emit_initial_properties)
    finally:
      os.chdir(old_cwd)

    return handle_recipe_return(
        ret, args.output_result_json, stream_engine, engine_flags)


class ProjectOverrideAction(argparse.Action):
  def __call__(self, parser, namespace, values, option_string=None):
    p = values.split('=', 2)
    if len(p) != 2:
      raise ValueError('Override must have the form: repo=path')
    project_id, path = p

    v = getattr(namespace, self.dest, None)
    if v is None:
      v = {}
      setattr(namespace, self.dest, v)

    if v.get(project_id):
      raise ValueError('An override is already defined for [%s] (%s)' % (
                       project_id, v[project_id]))
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
      raise ValueError('Override path [%s] is not a directory' % (path,))
    v[project_id] = path


# Map of arguments_pb2.Property "value" oneof conversion functions.
#
# The fields here should be kept in sync with the "value" oneof field names in
# the arguments_pb2.Arguments.Property protobuf message.
_OP_PROPERTY_CONV = {
    's': lambda prop: prop.s,
    'int': lambda prop: prop.int,
    'uint': lambda prop: prop.uint,
    'd': lambda prop: prop.d,
    'b': lambda prop: prop.b,
    'data': lambda prop: prop.data,
    'map': lambda prop: _op_properties_to_dict(prop.map.property),
    'list': lambda prop: [_op_property_value(v) for v in prop.list.property],
}

def _op_property_value(prop):
  """Returns the Python-converted value of an arguments_pb2.Property.

  Args:
    prop (arguments_pb2.Property): property to convert.
  Returns: The converted value.
  Raises:
    ValueError: If 'prop' is incomplete or invalid.
  """
  typ = prop.WhichOneof('value')
  conv = _OP_PROPERTY_CONV.get(typ)
  if not conv:
    raise ValueError('Unknown property field [%s]' % (typ,))
  return conv(prop)


def _op_properties_to_dict(pmap):
  """Creates a properties dictionary from an arguments_pb2.PropertyMap entry.

  Args:
    pmap (arguments_pb2.PropertyMap): Map to convert to dictionary form.
  Returns (dict): A dictionary derived from the properties in 'pmap'.
  """
  return dict((k, _op_property_value(pmap[k])) for k in pmap)


def add_common_args(parser):
  from recipe_engine import package_io

  def package_type(value):
    if not os.path.isfile(value):
      raise argparse.ArgumentTypeError(
        'Given recipes config file %r does not exist.' % (value,))
    return package_io.PackageFile(value)

  parser.add_argument(
      '--package',
      type=package_type,
      help='Path to recipes.cfg of the recipe package to operate on'
        ', usually in infra/config/recipes.cfg')
  parser.add_argument(
      '--deps-path',
      type=os.path.abspath,
      help='Path where recipe engine dependencies will be extracted. Specify '
           '"-" to use a temporary directory for deps, which will be cleaned '
           'up on exit.')
  parser.add_argument(
      '--verbose', '-v', action='count',
      help='Increase logging verboisty')
  # TODO(phajdan.jr): Figure out if we need --no-fetch; remove if not.
  parser.add_argument(
      '--no-fetch', action='store_true',
      help='Disable automatic fetching')
  parser.add_argument('-O', '--project-override', metavar='ID=PATH',
      action=ProjectOverrideAction,
      help='Override a project repository path with a local one.')
  parser.add_argument(
      # Use 'None' as default so that we can recognize when none of the
      # bootstrap options were passed.
      '--use-bootstrap', action='store_true', default=None,
      help='Use bootstrap/bootstrap.py to create a isolated python virtualenv'
           ' with required python dependencies.')
  parser.add_argument(
      '--bootstrap-vpython-path', metavar='PATH',
      help='Specify the `vpython` executable path to use when bootstrapping ('
           'requires --use-bootstrap).')
  parser.add_argument(
      '--disable-bootstrap', action='store_false', dest='use_bootstrap',
      help='Disables bootstrap (see --use-bootstrap)')

  def operational_args_type(value):
    with open(value) as fd:
      return jsonpb.ParseDict(json.load(fd), arguments_pb2.Arguments())

  parser.set_defaults(
    operational_args=arguments_pb2.Arguments(),
    bare_command=False,  # don't call postprocess_func, don't use package_deps
    postprocess_func=lambda parser, args: None,
  )

  parser.add_argument(
      '--operational-args-path',
      dest='operational_args',
      type=operational_args_type,
      help='The path to an operational Arguments file. If provided, this file '
           'must contain a JSONPB-encoded Arguments protobuf message, and will '
           'be integrated into the runtime parameters.')

  def post_process_args(parser, args):
    if args.bare_command:
      # TODO(iannucci): this is gross, and only for the remote subcommand;
      # remote doesn't behave like ANY other commands. A way to solve this will
      # be to allow --package to take a remote repo and then simply remove the
      # remote subcommand entirely.
      if args.package is not None:
        parser.error('%s forbids --package' % args.command)
    else:
      if not args.package:
        parser.error('%s requires --package' % args.command)

  return post_process_args


def main():
  parser = argparse.ArgumentParser(
      description='Interact with the recipe system.')

  common_postprocess_func = add_common_args(parser)

  from recipe_engine import fetch, lint_test, bundle, depgraph, autoroll
  from recipe_engine import remote, refs, doc, test
  to_add = [
    fetch, lint_test, bundle, depgraph, autoroll, remote, refs, doc, test,
  ]

  subp = parser.add_subparsers()
  for module in to_add:
    module.add_subparser(subp)


  def properties_file_type(filename):
    with (sys.stdin if filename == '-' else open(filename)) as f:
      obj = json.load(f)
      if not isinstance(obj, dict):
        raise argparse.ArgumentTypeError(
          'must contain a JSON object, i.e. `{}`.')
      return obj

  def parse_prop(prop):
    key, val = prop.split('=', 1)
    try:
      val = json.loads(val)
    except (ValueError, SyntaxError):
      pass  # If a value couldn't be evaluated, keep the string version
    return {key: val}

  def properties_type(value):
    obj = json.loads(value)
    if not isinstance(obj, dict):
      raise argparse.ArgumentTypeError('must contain a JSON object, i.e. `{}`.')
    return obj

  run_p = subp.add_parser(
      'run',
      description='Run a recipe locally')
  run_p.set_defaults(command='run', properties={})

  run_p.add_argument(
      '--workdir',
      type=os.path.abspath,
      help='The working directory of recipe execution')
  run_p.add_argument(
      '--output-result-json',
      type=os.path.abspath,
      help='The file to write the JSON serialized returned value \
            of the recipe to')
  run_p.add_argument(
      '--timestamps',
      action='store_true',
      help='If true, emit CURRENT_TIMESTAMP annotations. '
           'Default: false. '
           'CURRENT_TIMESTAMP annotation has one parameter, current time in '
           'Unix timestamp format. '
           'CURRENT_TIMESTAMP annotation will be printed at the beginning and '
           'end of the annotation stream and also immediately before each '
           'STEP_STARTED and STEP_CLOSED annotations.',
  )
  prop_group = run_p.add_mutually_exclusive_group()
  prop_group.add_argument(
      '--properties-file',
      dest='properties',
      type=properties_file_type,
      help=('A file containing a json blob of properties. '
            'Pass "-" to read from stdin'))
  prop_group.add_argument(
      '--properties',
      type=properties_type,
      help='A json string containing the properties')

  run_p.add_argument(
      'recipe',
      help='The recipe to execute')
  run_p.add_argument(
      'props',
      nargs=argparse.REMAINDER,
      type=parse_prop,
      help='A list of property pairs; e.g. mastername=chromium.linux '
           'issue=12345. The property value will be decoded as JSON, but if '
           'this decoding fails the value will be interpreted as a string.')

  args = parser.parse_args()
  common_postprocess_func(parser, args)
  args.postprocess_func(parser, args)

  # TODO(iannucci): We should always do logging.basicConfig() (probably with
  # logging.WARNING), even if no verbose is passed. However we need to be
  # careful as this could cause issues with spurious/unexpected output. I think
  # it's risky enough to do in a different CL.

  if args.verbose > 0:
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)
  if args.verbose > 1:
    logging.getLogger().setLevel(logging.DEBUG)

  # If we're bootstrapping, construct our bootstrap environment. If we're
  # using a custom deps path, install our enviornment there too.
  if args.use_bootstrap and not env.USING_BOOTSTRAP:
    logging.debug('Bootstrapping recipe engine through vpython...')

    bootstrap_env = os.environ.copy()
    bootstrap_env[env.BOOTSTRAP_ENV_KEY] = '1'

    cmd = [
        sys.executable,
        os.path.join(ROOT_DIR, 'bootstrap', 'bootstrap_vpython.py'),
    ]
    if args.bootstrap_vpython_path:
      cmd += ['--vpython-path', args.bootstrap_vpython_path]
    cmd += [
        '--',
        os.path.join(ROOT_DIR, 'recipes.py'),
    ] + sys.argv[1:]

    logging.debug('Running bootstrap command (cwd=%s): %s', ROOT_DIR, cmd)
    return subprocess.call(
        cmd,
        cwd=ROOT_DIR,
        env=bootstrap_env)

  # Standard recipe engine operation.
  return _real_main(args)


def _real_main(args):
  from recipe_engine import package

  if args.bare_command:
    return args.func(None, args)

  config_file = args.package
  repo_root = package.InfraRepoConfig().from_recipes_cfg(args.package.path)

  try:
    # TODO(phajdan.jr): gracefully handle inconsistent deps when rolling.
    # This fails if the starting point does not have consistent dependency
    # graph. When performing an automated roll, it'd make sense to attempt
    # to automatically find a consistent state, rather than bailing out.
    # Especially that only some subcommands refer to package_deps.
    package_deps = package.PackageDeps.create(
        repo_root, config_file, allow_fetch=not args.no_fetch,
        deps_path=args.deps_path, overrides=args.project_override)
  except subprocess.CalledProcessError:
    # A git checkout failed somewhere. Return 2, which is the sign that this is
    # an infra failure, rather than a test failure.
    return 2

  if hasattr(args, 'func'):
    return args.func(package_deps, args)

  if args.command == 'run':
    return run(config_file, package_deps, args)
  else:
    print """Dear sir or madam,
        It has come to my attention that a quite impossible condition has come
    to pass in the specification you have issued a request for us to fulfill.
    It is with a heavy heart that I inform you that, at the present juncture,
    there is no conceivable next action to be taken upon your request, and as
    such, we have decided to abort the request with a nonzero status code.  We
    hope that your larger goals have not been put at risk due to this
    unfortunate circumstance, and wish you the best in deciding the next action
    in your venture and larger life.

    Warmly,
    recipes.py
    """
    return 1

  return 0

if __name__ == '__main__':
  # Use os._exit instead of sys.exit to prevent the python interpreter from
  # hanging on threads/processes which may have been spawned and not reaped
  # (e.g. by a leaky test harness).
  try:
    ret = main()
  except Exception as e:
    import traceback
    traceback.print_exc(file=sys.stderr)
    print >> sys.stderr, 'Uncaught exception (%s): %s' % (type(e).__name__, e)
    sys.exit(1)

  if not isinstance(ret, int):
    if ret is None:
      ret = 0
    else:
      print >> sys.stderr, ret
      ret = 1
  sys.stdout.flush()
  sys.stderr.flush()
  os._exit(ret)
