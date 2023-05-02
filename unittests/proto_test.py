#!/usr/bin/env vpython3
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os
import shutil
import subprocess
import textwrap

import test_env

from recipe_engine.internal.simple_cfg import RECIPES_CFG_LOCATION_REL


class TestProtoSupport(test_env.RecipeEngineUnitTest):
  def setUp(self):
    super(TestProtoSupport, self).setUp()
    self.deps = self.FakeRecipeDeps()
    self.deps.ambient_toplevel_code = [
      '''
        def _dumps(msg):
          import json
          from google.protobuf.json_format import MessageToDict
          return json.dumps(
              MessageToDict(msg), separators=(', ', ': '), indent=2,
              sort_keys=True)
      '''
    ]

  def assertProtoInOutput(self, data, output):
    self.assertIn(
        json.dumps(data, separators=(', ', ': '), indent=2, sort_keys=True),
        output)

  def test_recipe_proto_in_main(self):
    main = self.deps.main_repo

    with main.write_file('recipes/my_proto.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipes.main.my_proto;
        message Input {
          string hello = 1;
        }
      ''')

    with main.write_recipe('my_proto') as recipe:
      recipe.imports = [
        'from PB.recipes.main import my_proto',
      ]
      recipe.DEPS.append('recipe_engine/json')
      recipe.RunSteps.write('''
        api.step('Hello!', ['echo', _dumps(
          my_proto.Input(hello="I am a banana"))])
      ''')

    output, retcode = main.recipes_py('run', 'my_proto')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({"hello": "I am a banana"}, output)

  def test_recipe_module_proto_in_main(self):
    main = self.deps.main_repo

    with main.write_module('modname') as mod:
      mod.api.write('''
        def get_pb(self):
          from PB.recipe_modules.main.modname import mod_proto
          return mod_proto.Data(field="value")
      ''')
      mod.path

    with main.write_file('recipe_modules/modname/mod_proto.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipe_modules.main.modname;
        message Data {
          string field = 1;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.recipe_modules.main.modname import mod_proto',
      ]
      recipe.DEPS.append('modname')
      recipe.RunSteps.write('''
        data = api.modname.get_pb()
        assert isinstance(data, mod_proto.Data)
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'recipe')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({"field": "value"}, output)

  def test_global_proto_in_main(self):
    main = self.deps.main_repo

    with main.write_file('recipe_proto/some.example.com/cool.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package arbitrary.package;
        message Data {
          string field = 1;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.some.example.com import cool',
      ]
      recipe.RunSteps.write('''
        data = cool.Data(field="value")
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'recipe')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({"field": "value"}, output)

  def test_proto_import_from_recipe(self):
    main = self.deps.main_repo

    with main.write_file('recipes/subdir/common.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipes.main.subdir.common;
        message Common {
          string common_field = 1;
        }
      ''')

    with main.write_file('recipes/a.proto') as proto:
      proto.write('''
        syntax = "proto3";
        import "recipes/main/subdir/common.proto";
        package recipes.main.a;
        message Data {
          string field = 1;
          recipes.main.subdir.common.Common common = 2;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.recipes.main import a',
      ]
      recipe.RunSteps.write('''
        data = a.Data(field="value")
        data.common.common_field = "neat"
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'recipe')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({
      "field": "value",
      "common": {
        "commonField": "neat",
      }
    }, output)

  def test_proto_import_from_module(self):
    main = self.deps.main_repo

    with main.write_file('recipe_modules/modname/common.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipe_modules.main.modname;
        message Moddata {
          string modname_field = 1;
        }
      ''')

    with main.write_file('recipes/a.proto') as proto:
      proto.write('''
        syntax = "proto3";
        import "recipe_modules/main/modname/common.proto";
        package recipes.main.a;
        message Data {
          string field = 1;
          recipe_modules.main.modname.Moddata mod_data = 2;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.recipes.main import a',
      ]
      recipe.RunSteps.write('''
        data = a.Data(field="value")
        data.mod_data.modname_field = "neat"
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'recipe')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({
      "field": "value",
      "modData": {
        "modnameField": "neat",
      }
    }, output)

  def test_proto_import_from_engine(self):
    main = self.deps.main_repo

    with main.write_file('recipes/a.proto') as proto:
      proto.write('''
        syntax = "proto3";
        import "recipe_engine/recipes_cfg.proto";
        package recipes.main.a;
        message Data {
          string field = 1;
          recipe_engine.RepoSpec spec = 2;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.recipes.main import a',
      ]
      recipe.RunSteps.write('''
        data = a.Data(field="value")
        data.spec.deps['hello'].revision = 'deadbeef'
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'recipe')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({
      "field": "value",
      "spec": {
        "deps": {
          "hello": {
            "revision": "deadbeef",
          }
        }
      }
    }, output)

  def test_proto_import_from_buildbucket(self):
    main = self.deps.main_repo

    with main.write_file('recipes/a.proto') as proto:
      proto.write('''
        syntax = "proto3";
        import "go.chromium.org/luci/buildbucket/proto/build.proto";
        package recipes.main.a;
        message Data {
          string field = 1;
          buildbucket.v2.Build build = 2;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.recipes.main import a',
      ]
      recipe.RunSteps.write('''
        data = a.Data(field="value")
        data.build.input.experimental = True
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'recipe')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({
      "field": "value",
      "build": {
        "input": {
          "experimental": True,
        }
      }
    }, output)

  def test_bundled_protoc(self):
    main = self.deps.main_repo

    with main.write_file('recipe_modules/modname/cool.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipe_modules.main.modname;
        message ModData {
          string mod_field = 1;
        }
      ''')

    with main.write_file('recipes/a.proto') as proto:
      proto.write('''
        syntax = "proto3";
        import "recipe_engine/recipes_cfg.proto";
        import "recipe_modules/main/modname/cool.proto";
        package recipes.main.a;
        message Data {
          string field = 1;
          recipe_engine.RepoSpec spec = 2;
          recipe_modules.main.modname.ModData mod_stuff = 3;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.recipes.main import a',
      ]
      recipe.RunSteps.write('''
        data = a.Data(field="value")
        data.spec.deps['hello'].revision = 'deadbeef'
        data.mod_stuff.mod_field = 'awesome'
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    main.commit('commit everything')

    bundle_dir = self.tempdir()
    output, retcode = main.recipes_py('bundle', '--destination', bundle_dir)
    self.assertEqual(retcode, 0, output)

    proc = subprocess.Popen(
        [os.path.join(bundle_dir, 'recipes'), 'run', 'recipe'],
        cwd=bundle_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output, _ = proc.communicate()

    self.assertEqual(proc.returncode, 0, output)
    self.assertProtoInOutput({
      "field": "value",
      "spec": {
        "deps": {
          "hello": {
            "revision": "deadbeef",
          }
        }
      },
      "modStuff": {
        "modField": "awesome"
      },
    }, output)

  def test_filesystem_repo_scan(self):
    main = self.deps.main_repo

    with main.write_file('recipe_modules/modname/cool.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipe_modules.main.modname;
        message ModData {
          string mod_field = 1;
        }
      ''')

    with main.write_file('recipes/a.proto') as proto:
      proto.write('''
        syntax = "proto3";
        import "recipe_engine/recipes_cfg.proto";
        import "recipe_modules/main/modname/cool.proto";
        package recipes.main.a;
        message Data {
          string field = 1;
          recipe_engine.RepoSpec spec = 2;
          recipe_modules.main.modname.ModData mod_stuff = 3;
        }
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.imports = [
        'from PB.recipes.main import a',
      ]
      recipe.RunSteps.write('''
        data = a.Data(field="value")
        data.spec.deps['hello'].revision = 'deadbeef'
        data.mod_stuff.mod_field = 'awesome'
        api.step('Hello!', ['echo', _dumps(data)])
      ''')

    # Removing the .git directory forces the filesystem scan to be used for the
    # main repo.
    shutil.rmtree(os.path.join(main.path, '.git'))

    output, retcode = main.recipes_py(
        '--package', os.path.join(main.path, RECIPES_CFG_LOCATION_REL),
        'run', 'recipe')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({
      "field": "value",
      "spec": {
        "deps": {
          "hello": {
            "revision": "deadbeef",
          }
        }
      },
      "modStuff": {
        "modField": "awesome"
      },
    }, output)

  def test_update_proto_file(self):
    main = self.deps.main_repo

    with main.write_file('recipes/cool.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipes.main.cool;
        message CoolData {
          string field = 1;
        }
      ''')

    with main.write_recipe('cool') as recipe:
      recipe.imports = [
        'from PB.recipes.main.cool import CoolData'
      ]
      recipe.RunSteps.write('''
        data = CoolData(field="norp")
        api.step('hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'cool')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({"field": "norp"}, output)

    with main.write_file('recipes/cool.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipes.main.cool;
        message CoolData {
          string field = 1;
          string fweep = 2;
        }
      ''')

    with main.write_recipe('cool') as recipe:
      recipe.imports = [
        'from PB.recipes.main.cool import CoolData'
      ]
      recipe.RunSteps.write('''
        data = CoolData(field="norp", fweep="dorp")
        api.step('hello!', ['echo', _dumps(data)])
      ''')

    output, retcode = main.recipes_py('run', 'cool')
    self.assertEqual(retcode, 0, output)
    self.assertProtoInOutput({"field": "norp", "fweep": "dorp"}, output)

  def test_conflicting_proto_error(self):
    main = self.deps.main_repo
    upstream = self.deps.add_repo('upstream')

    with upstream.write_file('recipe_proto/something.proto') as buf:
      buf.write('''
        syntax = "proto3";
        package global;
        message GlobalProto {
          string field = 1;
        }
      ''')

    up_commit = upstream.commit('add proto')

    with main.write_file('recipe_proto/something.proto') as buf:
      buf.write('''
        syntax = "proto3";
        package global;
        message GlobalProto {
          string field = 1;
        }
      ''')

    with main.edit_recipes_cfg_pb2() as spec:
      spec.deps['upstream'].revision = up_commit.revision

    output, retcode = main.recipes_py('fetch')
    self.assertEqual(retcode, 1, output)
    self.assertIn(textwrap.dedent('''
      BadProtoDefinitions: Multiple repos have the same .proto file:
        'something.proto' in main, upstream
    ''').strip(), output)

  def test_reserved_proto_error(self):
    main = self.deps.main_repo

    with main.write_file('recipes/recipes/is_ok.proto'):
      pass

    with main.write_file('recipe_modules/recipe_modules/is_ok.proto'):
      pass

    with main.write_file('recipe_proto/recipe_engine/reserved.proto'):
      pass

    with main.write_file('recipe_proto/recipe_modules/reserved.proto'):
      pass

    with main.write_file('recipe_proto/recipes/reserved.proto'):
      pass

    output, retcode = main.recipes_py('fetch')
    self.assertEqual(retcode, 1, output)
    self.assertIn(textwrap.dedent('''
        BadProtoDefinitions: Repos have reserved .proto files:
          'recipe_engine/reserved.proto' in main
          'recipe_modules/reserved.proto' in main
          'recipes/reserved.proto' in main
    ''').strip(), output)

  def test_bad_proto_syntax_recipes(self):
    main = self.deps.main_repo

    with main.write_file('recipes/norp.proto') as proto:
      proto.write('syntax = "proto3"; norp')

    output, retcode = main.recipes_py('fetch')
    self.assertEqual(retcode, 1, output)
    self.assertIn(textwrap.dedent('''
      Error while compiling protobufs. Output:

      BASE/recipes/norp.proto:1:20: Expected top-level statement (e.g. "message").
    ''').strip(), output.replace(main.path, 'BASE').replace('\\', '/'))

  def test_bad_proto_syntax_recipe_modules(self):
    main = self.deps.main_repo

    with main.write_file('recipe_modules/foop/norp.proto') as proto:
      proto.write('syntax = "proto3"; norp')

    output, retcode = main.recipes_py('fetch')
    self.assertEqual(retcode, 1, output)
    self.assertIn(textwrap.dedent('''
      Error while compiling protobufs. Output:

      BASE/recipe_modules/foop/norp.proto:1:20: Expected top-level statement (e.g. "message").
    ''').strip(), output.replace(main.path, 'BASE').replace('\\', '/'))

  def test_bad_proto_syntax_global(self):
    main = self.deps.main_repo

    with main.write_file('recipe_proto/foop/norp.proto') as proto:
      proto.write('syntax = "proto3"; norp')

    output, retcode = main.recipes_py('fetch')
    self.assertEqual(retcode, 1, output)
    self.assertIn(textwrap.dedent('''
      Error while compiling protobufs. Output:

      BASE/recipe_proto/foop/norp.proto:1:20: Expected top-level statement (e.g. "message").
    ''').strip(), output.replace(main.path, 'BASE').replace('\\', '/'))

  def test_bad_packages(self):
    main = self.deps.main_repo

    with main.write_file('recipes/bad_namespace.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipes.main;
        message Input {
          string hello = 1;
        }
      ''')

    with main.write_file('recipe_modules/foobar/bad_namespace.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipe_modules.main.foobar.etc;
        message Input {
          string hello = 1;
        }
      ''')

    with main.write_file('recipe_proto/impersonates_recipe.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipes.foobar.etc;
        message Input {
          string hello = 1;
        }
      ''')

    with main.write_file('recipe_proto/impersonates_module.proto') as proto:
      proto.write('''
        syntax = "proto3";
        package recipe_modules.foobar.etc;
        message Input {
          string hello = 1;
        }
      ''')

    output, retcode = main.recipes_py('fetch')
    self.assertEqual(retcode, 1, output)
    output = output.replace(main.path, 'BASE').replace('\\', '/')
    self.assertIn(("BASE/recipe_proto/impersonates_module.proto: bad package: "
                   "uses reserved namespace 'recipe_modules'"), output)
    self.assertIn(("BASE/recipe_proto/impersonates_recipe.proto: bad package: "
                   "uses reserved namespace 'recipes'"), output)
    self.assertIn((
        "BASE/recipe_modules/foobar/bad_namespace.proto: bad package: "
        "expected 'recipe_modules.main.foobar', got 'recipe_modules.main.foobar.etc'"
    ), output)
    self.assertIn(("BASE/recipes/bad_namespace.proto: bad package: "
                   "expected 'recipes.main.bad_namespace', got 'recipes.main'"),
                  output)


if __name__ == '__main__':
  test_env.main()
