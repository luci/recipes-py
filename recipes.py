#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tool to interact with recipe repositories.

This tool operates on the nearest ancestor directory containing an
infra/config/recipes.cfg.
"""

import argparse
import json
import logging
import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, 'recipe_engine', 'third_party'))
sys.path.insert(0, ROOT_DIR)

def get_package_config(args):
  from recipe_engine import package

  assert args.package, 'No recipe config (--package) given.'
  assert os.path.exists(args.package), (
      'Given recipes config file %s does not exist.' % args.package)
  return (
      package.InfraRepoConfig().from_recipes_cfg(args.package),
      package.ProtoFile(args.package)
  )


def simulation_test(package_deps, args):
  from recipe_engine import simulation_test
  from recipe_engine import loader

  _, config_file = get_package_config(args)
  universe = loader.RecipeUniverse(package_deps, config_file)
  universe_view = loader.UniverseView(universe, package_deps.root_package)

  simulation_test.main(universe_view, args=json.loads(args.args))


def lint(package_deps, args):
  from recipe_engine import lint_test
  from recipe_engine import loader

  _, config_file = get_package_config(args)
  universe = loader.RecipeUniverse(package_deps, config_file)
  universe_view = loader.UniverseView(universe, package_deps.root_package)

  lint_test.main(universe_view, args.whitelist or [])


def handle_recipe_return(recipe_result, result_filename, stream_engine):
  if 'recipe_result' in recipe_result.result:
    result_string = json.dumps(
        recipe_result.result['recipe_result'], indent=2)
    if result_filename:
      with open(result_filename, 'w') as f:
        f.write(result_string)
    with stream_engine.new_step_stream('recipe result') as s:
      with s.new_log_stream('result') as l:
        l.write_split(result_string)

  if 'traceback' in recipe_result.result:
    with stream_engine.new_step_stream('Uncaught Exception') as s:
      s.set_step_status('EXCEPTION')
      with s.new_log_stream('exception') as l:
        for line in recipe_result.result['traceback']:
          l.write_line(line)

  if 'reason' in recipe_result.result:
    with stream_engine.new_step_stream('Failure reason') as s:
      s.set_step_status('FAILURE')
      with s.new_log_stream('reason') as l:
        for line in recipe_result.result['reason'].splitlines():
          l.write_line(line)

  if 'status_code' in recipe_result.result:
    return recipe_result.result['status_code']
  else:
    return 0


def run(package_deps, args):
  from recipe_engine import run as recipe_run
  from recipe_engine import loader
  from recipe_engine import step_runner
  from recipe_engine import stream

  def get_properties_from_args(args):
    properties = dict(x.split('=', 1) for x in args)
    for key, val in properties.iteritems():
      try:
        properties[key] = json.loads(val)
      except (ValueError, SyntaxError):
        pass  # If a value couldn't be evaluated, keep the string version
    return properties

  def get_properties_from_file(filename):
    properties_file = sys.stdin if filename == '-' else open(filename)
    properties = json.load(properties_file)
    assert isinstance(properties, dict)
    return properties

  def get_properties_from_json(props):
    return json.loads(props)

  arg_properties = get_properties_from_args(args.props)
  assert len(filter(bool,
      [arg_properties, args.properties_file, args.properties])) <= 1, (
          'Only one source of properties is allowed')
  if args.properties:
    properties = get_properties_from_json(args.properties)
  elif args.properties_file:
    properties = get_properties_from_file(args.properties_file)
  else:
    properties = arg_properties

  properties['recipe'] = args.recipe

  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONIOENCODING'] = 'UTF-8'

  _, config_file = get_package_config(args)
  universe = loader.UniverseView(
      loader.RecipeUniverse(
          package_deps, config_file), package_deps.root_package)

  workdir = (args.workdir or
      os.path.join(os.path.dirname(os.path.realpath(__file__)), 'workdir'))
  logging.info('Using %s as work directory' % workdir)
  if not os.path.exists(workdir):
    os.makedirs(workdir)

  old_cwd = os.getcwd()
  os.chdir(workdir)
  stream_engine = stream.ProductStreamEngine(
      stream.StreamEngineInvariants(),
      stream.AnnotatorStreamEngine(sys.stdout, emit_timestamps=args.timestamps))
  with stream_engine:
    try:
      ret = recipe_run.run_steps(
          properties, stream_engine,
          step_runner.SubprocessStepRunner(stream_engine),
          universe=universe)
    finally:
      os.chdir(old_cwd)

    return handle_recipe_return(ret, args.output_result_json, stream_engine)


def remote(args):
  from recipe_engine import remote

  return remote.main(args)


def autoroll(args):
  from recipe_engine import autoroll

  repo_root, config_file = get_package_config(args)

  return autoroll.main(args, repo_root, config_file)


class ProjectOverrideAction(argparse.Action):
  def __call__(self, parser, namespace, values, option_string=None):
    p = values.split('=', 2)
    if len(p) != 2:
      raise ValueError("Override must have the form: repo=path")
    project_id, path = p

    v = getattr(namespace, self.dest, None)
    if v is None:
      v = {}
      setattr(namespace, self.dest, v)

    if v.get(project_id):
      raise ValueError("An override is already defined for [%s] (%s)" % (
                       project_id, v[project_id]))
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
      raise ValueError("Override path [%s] is not a directory" % (path,))
    v[project_id] = path


def depgraph(package_deps, args):
  from recipe_engine import depgraph
  from recipe_engine import loader

  _, config_file = get_package_config(args)
  universe = loader.RecipeUniverse(package_deps, config_file)

  depgraph.main(universe, package_deps.root_package,
                args.ignore_package, args.output, args.recipe_filter)


def doc(package_deps, args):
  from recipe_engine import doc
  from recipe_engine import loader

  _, config_file = get_package_config(args)
  universe = loader.RecipeUniverse(package_deps, config_file)
  universe_view = loader.UniverseView(universe, package_deps.root_package)

  doc.main(universe_view)


def info(args):
  from recipe_engine import package
  repo_root, config_file = get_package_config(args)
  package_spec = package.PackageSpec.load_proto(config_file)

  if args.recipes_dir:
    print package_spec.recipes_path


def main():
  from recipe_engine import package

  # Super-annoyingly, we need to manually parse for simulation_test since
  # argparse is bonkers and doesn't allow us to forward --help to subcommands.
  # Save old_args for if we're using bootstrap
  original_sys_argv = sys.argv[:]
  if 'simulation_test' in sys.argv:
    index = sys.argv.index('simulation_test')
    sys.argv = sys.argv[:index+1] + [json.dumps(sys.argv[index+1:])]

  parser = argparse.ArgumentParser(
      description='Interact with the recipe system.')

  parser.add_argument(
      '--package',
      help='Path to recipes.cfg of the recipe package to operate on'
        ', usually in infra/config/recipes.cfg')
  parser.add_argument(
      '--deps-path',
      help='Path where recipe engine dependencies will be extracted.')
  parser.add_argument(
      '--verbose', '-v', action='store_true',
      help='Increase logging verboisty')
  # TODO(phajdan.jr): Figure out if we need --no-fetch; remove if not.
  parser.add_argument(
      '--no-fetch', action='store_true',
      help='Disable automatic fetching')
  parser.add_argument(
      '--bootstrap-script',
      help='Path to the script used to bootstrap this tool (internal use only)')
  parser.add_argument('-O', '--project-override', metavar='ID=PATH',
      action=ProjectOverrideAction,
      help='Override a project repository path with a local one.')
  parser.add_argument(
      '--use-bootstrap', action='store_true',
      help='Use bootstrap/bootstrap.py to create a isolated python virtualenv'
           ' with required python dependencies.')

  subp = parser.add_subparsers()

  fetch_p = subp.add_parser(
      'fetch',
      description='Fetch and update dependencies.')
  fetch_p.set_defaults(command='fetch')

  simulation_test_p = subp.add_parser(
    'simulation_test',
    description='Generate or check expectations by simulation')
  simulation_test_p.set_defaults(command='simulation_test')
  simulation_test_p.add_argument('args')

  lint_p = subp.add_parser(
      'lint',
      description='Check recipes for stylistic and hygenic issues')
  lint_p.set_defaults(command='lint')

  lint_p.add_argument(
      '--whitelist', '-w', action='append',
      help='A regexp matching module names to add to the default whitelist. '
           'Use multiple times to add multiple patterns,')

  run_p = subp.add_parser(
      'run',
      description='Run a recipe locally')
  run_p.set_defaults(command='run')
  run_p.add_argument(
      '--properties-file',
      help='A file containing a json blob of properties')
  run_p.add_argument(
      '--properties',
      help='A json string containing the properties')
  run_p.add_argument(
      '--workdir',
      help='The working directory of recipe execution')
  run_p.add_argument(
      '--output-result-json',
      help='The file to write the JSON serialized returned value \
            of the recipe to')
  run_p.add_argument(
      'recipe',
      help='The recipe to execute')
  run_p.add_argument(
      'props',
      nargs=argparse.REMAINDER,
      help='A list of property pairs; e.g. mastername=chromium.linux '
           'issue=12345')
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

  remote_p = subp.add_parser(
      'remote',
      description='Invoke a recipe command from specified repo and revision')
  remote_p.set_defaults(command='remote')
  remote_p.add_argument(
      '--repository', required=True,
      help='URL of a git repository to fetch')
  remote_p.add_argument(
      '--revision',
      help='Git commit hash to check out; defaults to latest revision (HEAD)')
  remote_p.add_argument(
      '--workdir',
      help='The working directory of repo checkout')
  remote_p.add_argument(
      '--use-gitiles', action='store_true',
      help='Use Gitiles-specific way to fetch repo (potentially cheaper for '
           'large repos)')
  remote_p.add_argument(
      'remote_args', nargs='*',
      help='Arguments to pass to fetched repo\'s recipes.py')

  autoroll_p = subp.add_parser(
      'autoroll',
      help='Roll dependencies of a recipe package forward (implies fetch)')
  autoroll_p.set_defaults(command='autoroll')
  autoroll_p.add_argument(
      '--output-json',
      help='A json file to output information about the roll to.')

  depgraph_p = subp.add_parser(
      'depgraph',
      description=(
          'Produce graph of recipe and recipe module dependencies. Example: '
          './recipes.py --package infra/config/recipes.cfg depgraph | tred | '
          'dot -Tpdf > graph.pdf'))
  depgraph_p.set_defaults(command='depgraph')
  depgraph_p.add_argument(
      '--output', type=argparse.FileType('w'), default=sys.stdout,
      help='The file to write output to')
  depgraph_p.add_argument(
      '--ignore-package', action='append', default=[],
      help='Ignore a recipe package (e.g. recipe_engine). Can be passed '
           'multiple times')
  depgraph_p.add_argument(
      '--recipe-filter', default='',
      help='A recipe substring to examine. If present, the depgraph will '
           'include a recipe section containing recipes whose names contain '
           'this substring. It will also filter all nodes of the graph to only '
           'include modules touched by the filtered recipes.')

  doc_p = subp.add_parser(
      'doc',
      description='List all known modules reachable from the current package, '
          'with their documentation')
  doc_p.set_defaults(command='doc')

  info_p = subp.add_parser(
      'info',
      description='Query information about the current recipe package')
  info_p.set_defaults(command='info')
  info_p.add_argument(
      '--recipes-dir', action='store_true',
      help='Get the subpath where the recipes live relative to repository root')

  args = parser.parse_args()

  if args.use_bootstrap and not os.environ.pop('RECIPES_RUN_BOOTSTRAP', None):
    subprocess.check_call(
        [sys.executable, 'bootstrap/bootstrap.py', '--deps-file',
         'bootstrap/deps.pyl', 'ENV'],
        cwd=os.path.dirname(os.path.realpath(__file__)))

    os.environ['RECIPES_RUN_BOOTSTRAP'] = '1'
    args = sys.argv
    return subprocess.call(
        [os.path.join(
            os.path.dirname(os.path.realpath(__file__)), 'ENV/bin/python'),
         os.path.join(ROOT_DIR, 'recipes.py')] + original_sys_argv[1:])

  if args.verbose:
    logging.getLogger().setLevel(logging.INFO)

  # Commands which do not require config_file, package_deps, and other objects
  # initialized later.
  if args.command == 'remote':
    return remote(args)

  repo_root, config_file = get_package_config(args)

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

  if args.command == 'fetch':
    # We already did everything in the create() call above.
    assert not args.no_fetch, 'Fetch? No-fetch? Make up your mind!'
    return 0
  if args.command == 'simulation_test':
    return simulation_test(package_deps, args)
  elif args.command == 'lint':
    return lint(package_deps, args)
  elif args.command == 'run':
    return run(package_deps, args)
  elif args.command == 'autoroll':
    return autoroll(args)
  elif args.command == 'depgraph':
    return depgraph(package_deps, args)
  elif args.command == 'doc':
    return doc(package_deps, args)
  elif args.command == 'info':
    return info(args)
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
  ret = main()
  if not isinstance(ret, int):
    if ret is None:
      ret = 0
    else:
      print >> sys.stderr, ret
      ret = 1
  sys.stdout.flush()
  sys.stderr.flush()
  os._exit(ret)
