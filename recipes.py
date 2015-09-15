#!/usr/bin/env python

"""Tool to interact with recipe repositories.

This tool operates on the nearest ancestor directory containing an
infra/config/recipes.cfg.
"""

import argparse
import ast
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
  simulation_test.main(package_deps, args=json.loads(args.args))


def lint(package_deps, args):
  from recipe_engine import lint_test
  lint_test.main(package_deps, args.whitelist or [])


def run(package_deps, args):
  from recipe_engine import run as recipe_run
  from recipe_engine import loader
  from recipe_engine import package
  from recipe_engine.third_party import annotator

  def get_properties_from_args(args):
    properties = dict(x.split('=', 1) for x in args)
    for key, val in properties.iteritems():
      try:
        properties[key] = ast.literal_eval(val)
      except (ValueError, SyntaxError):
        pass  # If a value couldn't be evaluated, keep the string version
    return properties

  def get_properties_from_file(filename):
    properties_file = sys.stdin if filename == '-' else open(filename)
    properties = ast.literal_eval(properties_file.read())
    assert isinstance(properties, dict)

  def get_properties_from_json(args):
    return ast.literal_eval(args.properties)

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

  universe = loader.RecipeUniverse(package_deps)

  workdir = (args.workdir or
      os.path.join(os.path.dirname(os.path.realpath(__file__)), 'workdir'))
  logging.info('Using %s as work directory' % workdir)
  if not os.path.exists(workdir):
    os.makedirs(workdir)

  old_cwd = os.getcwd()
  os.chdir(workdir)
  try:
    ret = recipe_run.run_steps(
        properties, annotator.StructuredAnnotationStream(), universe=universe)
    return ret.status_code
  finally:
    os.chdir(old_cwd)


def roll(args):
  from recipe_engine import package
  repo_root, config_file = get_package_config(args)
  context = package.PackageContext.from_proto_file(repo_root, config_file)
  package_spec = package.PackageSpec.load_proto(config_file)

  for update in package_spec.iterate_consistent_updates(config_file, context):
    config_file.write(update.spec.dump())
    print 'Wrote %s' % config_file.path

    updated_deps = {
        dep_id: dep.revision
        for dep_id, dep in update.spec.deps.iteritems()
        if dep.revision != package_spec.deps[dep_id].revision
    }
    print 'To commit this roll, run:'
    print ' '.join([
        'git commit -a -m "Roll dependencies"',
        ' '.join([ '-m "Roll %s to %s"' % (dep_id, rev)
                   for dep_id, rev in sorted(updated_deps.iteritems())]),
    ])

    break
  else:
    print 'No consistent rolls found'


def doc(package_deps, args):
  from recipe_engine import doc
  doc.main(package_deps)


def main():
  from recipe_engine import package

  # Super-annoyingly, we need to manually parse for simulation_test since
  # argparse is bonkers and doesn't allow us to forward --help to subcommands.
  if 'simulation_test' in sys.argv:
    index = sys.argv.index('simulation_test')
    sys.argv = sys.argv[:index+1] + [json.dumps(sys.argv[index+1:])]

  parser = argparse.ArgumentParser(description='Do things with recipes.')

  parser.add_argument(
      '--package',
      help='Package to operate on (directory containing '
           'infra/config/recipes.cfg)')
  parser.add_argument(
      '--verbose', '-v', action='store_true',
      help='Increase logging verboisty')
  parser.add_argument(
      '--no-fetch', action='store_true',
      help='Disable automatic fetching')
  parser.add_argument(
      '--bootstrap-script',
      help='Path to the script used to bootstrap this tool (internal use only)')

  subp = parser.add_subparsers()

  fetch_p = subp.add_parser(
      'fetch',
      help='Fetch and update dependencies.')
  fetch_p.set_defaults(command='fetch')

  simulation_test_p = subp.add_parser('simulation_test',
      help='Generate or check expectations by simulating with mock actions')
  simulation_test_p.set_defaults(command='simulation_test')
  simulation_test_p.add_argument('args')

  lint_p = subp.add_parser(
      'lint',
      help='Check recipes for stylistic and hygenic issues')
  lint_p.set_defaults(command='lint')

  lint_p.add_argument(
      '--whitelist', '-w', action='append',
      help='A regexp matching module names to add to the default whitelist. '
           'Use multiple times to add multiple patterns,')

  run_p = subp.add_parser(
      'run',
      help='Run a recipe locally')
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
      'recipe',
      help='The recipe to execute')
  run_p.add_argument(
      'props', nargs=argparse.REMAINDER,
      help='A list of property pairs; e.g. mastername=chromium.linux '
           'issue=12345')

  roll_p = subp.add_parser(
      'roll',
      help='Roll dependencies of a recipe package forward (implies fetch)')
  roll_p.set_defaults(command='roll')

  show_me_the_modules_p = subp.add_parser(
      'doc',
      help='List all known modules reachable from the current package with '
           'various info about each')
  show_me_the_modules_p.set_defaults(command='doc')

  args = parser.parse_args()

  if args.verbose:
    logging.getLogger().setLevel(logging.INFO)

  repo_root, config_file = get_package_config(args)
  package_deps = package.PackageDeps.create(
      repo_root, config_file, allow_fetch=not args.no_fetch)

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
  elif args.command == 'roll':
    return roll(args)
  elif args.command == 'doc':
    return doc(package_deps, args)
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
  sys.exit(main())
