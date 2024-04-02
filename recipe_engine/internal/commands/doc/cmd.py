# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from builtins import object, range
from past.builtins import basestring

from io import StringIO

import ast
import difflib
import inspect
import json
import logging
import os
import posixpath
import sys
import types

import astunparse

from google.protobuf import json_format as jsonpb
from google.protobuf import text_format as textpb

from recipe_engine import engine_types
from recipe_engine import __path__ as RECIPE_ENGINE_PATH

from PB.recipe_engine import doc

from .... import config
from .... import recipe_api
from .... import util

from ...recipe_deps import Recipe, RecipeModule, RecipeRepo
from ...recipe_deps import parse_deps_spec

from . import doc_markdown


LOGGER = logging.getLogger(__name__)

RECIPE_ENGINE_BASE = os.path.dirname(os.path.abspath(RECIPE_ENGINE_PATH[0]))

join = posixpath.join
if sys.platform == 'win32':
  def _to_posix(native_path):
    return native_path.replace(os.path.sep, os.path.altsep)
else:
  def _to_posix(native_path):
    return native_path


def _grab_ast(repo, abspath):
  """Parses the Python file indicated by `abspath`.

  Args:
    * repo (RecipeRepo) - The repo which contains `abspath`. Used for error
      reporting.
    * abspath (str) - The absolute (native) path to the Python file to parse.

  Returns the Python AST object if the file exists and is parsable. Otherwise
  logs an error and returns None.
  """
  assert isinstance(repo, RecipeRepo), type(repo)
  relpath = os.path.relpath(abspath, repo.path)
  assert '..' not in relpath
  try:
    with open(abspath, 'rb') as f:
      return ast.parse(f.read(), relpath)
  except SyntaxError as ex:
    LOGGER.warn('skipping %s: bad syntax: %s', _to_posix(relpath), ex)
  except OSError as ex:
    LOGGER.warn('skipping %s: %s', _to_posix(relpath), ex)
  return None


def _unparse(node):
  """Prints Python code which could parse to `node`.

  Args:
    * node (ast.AST) - The AST to produce Python code for.

  Returns a str with the formatted code.
  """
  assert isinstance(node, ast.AST), type(node)
  buf = StringIO()
  astunparse.Unparser(node, buf)
  return buf.getvalue()


def _find_value_of(mod_ast, target):
  """Looks for an assignment to `target`, returning the assignment value AST
  node and the line number of the assignment.

  Example:

     some_var = 100
     other = 20 + 10

     _find_value_of(<code>, 'some_var')  ->  ast.Num(100)

  Args:
    * mod_ast (ast.Module) - The parsed Python module code.
    * target (str) - The variable name to look for an assignment to.

  Returns the Python AST object which is the right-hand-side of an assignment to
  `target`.
  """
  assert isinstance(mod_ast, ast.Module), type(mod_ast)
  for node in mod_ast.body:
    if isinstance(node, ast.Assign):
      if (len(node.targets) == 1 and
          isinstance(node.targets[0], ast.Name) and
          node.targets[0].id == target):
        return node.value, node.lineno
  return None, None


def _expand_mock_imports(*mock_imports):
  """Returns an expanded set of mock imports.

  mock_imports is expected to be a dict which looks like:
    {
      "absolute.module.name": SomeObject,
    }

  The objects in this dictionary will be the ones returned in the
  eval-compatible env dict. Think of it as a fake sys.modules. However, unlike
  sys.modules, mock_imports can be 'sparse'. For example, if mock_imports is:
    {
      'a.b': "foo",
      'a.c': "bar",
    }

  And the user does `import a`, this will make a fake object containing both .b
  and .c. However, this only works on leaf nodes. 'a.b' and 'a.b.d' would be an
  error (and this will raise ValueError if you attempt to do that).

  Returns a mock_imports, but with all the fake objects expanded.
  """
  combined_imports = {}
  for mi in mock_imports:
    combined_imports.update(mi)

  class expando(object):
    pass

  # expand combined_imports so it supports trivial lookups.
  expanded_imports = {}
  for dotted_name, obj in sorted(combined_imports.items()):
    if dotted_name in expanded_imports:
      raise ValueError('nested mock imports! %r', dotted_name)
    toks = dotted_name.split('.')
    expanded_imports[dotted_name] = obj
    if isinstance(obj, types.ModuleType):
      for name in (n for n in dir(obj) if not n.startswith('_')):
        expanded_imports[dotted_name+'.'+name] = getattr(obj, name)
    for i in range(len(toks)-1, 0, -1):
      partial = '.'.join(toks[:i])
      cur_obj = expanded_imports.setdefault(partial, expando())
      if not isinstance(cur_obj, expando):
        raise ValueError('nested mock imports! %r', partial)
      setattr(cur_obj, toks[i], expanded_imports[partial+'.'+toks[i]])

  return expanded_imports

ALL_IMPORTS = {}  # used in doc_test to ensure everything is actually importable
KNOWN_OBJECTS = {}

_decorator_imports = {
  'recipe_engine.util.returns_placeholder': util.returns_placeholder,
}
KNOWN_OBJECTS.update(_decorator_imports)

_config_imports = {
  'recipe_engine.config.ConfigGroup': config.ConfigGroup,
  'recipe_engine.config.ConfigList': config.ConfigList,
  'recipe_engine.config.Set': config.Set,
  'recipe_engine.config.Dict': config.Dict,
  'recipe_engine.config.List': config.List,
  'recipe_engine.config.Single': config.Single,
  'recipe_engine.config.Static': config.Static,
  'recipe_engine.config.Enum': config.Enum,
}
KNOWN_OBJECTS.update(_config_imports)

_placeholder_imports = {
  'recipe_engine.util.OutputPlaceholder': util.OutputPlaceholder,
  'recipe_engine.util.InputPlaceholder': util.InputPlaceholder,
  'recipe_engine.util.Placeholder': util.Placeholder,
}
KNOWN_OBJECTS.update(_placeholder_imports)

_property_imports = {
  'recipe_engine.recipe_api.Property': recipe_api.Property,
}
KNOWN_OBJECTS.update(_property_imports)

_util_imports = {
  'recipe_engine.engine_types.freeze': engine_types.freeze,
}
KNOWN_OBJECTS.update(_util_imports)

_recipe_api_class_imports = {
  'recipe_engine.recipe_api.RecipeApi': recipe_api.RecipeApi,
}
KNOWN_OBJECTS.update(_recipe_api_class_imports)


def _parse_mock_imports(mod_ast, expanded_imports):
  """Parses a module AST node for import statements and resolves them against
  expanded_imports (such as you might get from _expand_mock_imports).

  If an import is not recognized, it is omitted from the returned dictionary.

  Returns a dictionary suitable for eval'ing a statement in mod_ast, with
  symbols from mod_ast's imports resolved to real objects, as per
  expanded_imports.
  """
  ret = {}

  for node in mod_ast.body:
    if isinstance(node, ast.Import):
      for alias in node.names:
        if alias.name in expanded_imports:
          ret[alias.asname or alias.name] = expanded_imports[alias.name]
    elif isinstance(node, ast.ImportFrom):
      if node.level == 0:
        for alias in node.names:
          fullname ='%s.%s' % (node.module, alias.name)
          if fullname in expanded_imports:
            ret[alias.asname or alias.name] = expanded_imports[fullname]

  return ret


def _apply_imports_to_unparsed_expression(exp_ast, imports):
  """Attempts to evaluate the code equivalent of `exp_ast`, with `imports`
  as available symbols. If it's successful, it returns the evaluated object.
  Otherwise this returns the unparsed code for `exp_ast`.

  Args:
    * exp_ast (Union[ast.Name, ast.Attribute, ast.Call]) - The expression to
      evaluate.
    * imports (Dict[str, object]) - The symbols to include during the evaluation
      of `exp_ast`.

  Returns the evaluation of `exp_ast` if it can successfully evaluate with
  `imports`. Otherwise this returns the source-code representation of exp_ast as
  a string.
  """
  allowed_types = (ast.Name, ast.Attribute, ast.Call, ast.Subscript)
  assert isinstance(exp_ast, allowed_types), type(exp_ast)
  unparsed = _unparse(exp_ast).strip()
  try:
    return eval(unparsed, {'__builtins__': None}, imports)
  except (NameError, AttributeError, TypeError):
    return unparsed


def _extract_classes_funcs(body_ast, relpath, imports, do_fixup=True):
  """Extracts the classes and functions from the AST suite.

  Args:
    * body_ast (Union[ast.ClassDef, ast.Module]) - The statement suite to
      evaluate.
    * relpath (str) - The posix-style relative path which should be associated
      with the code in body_ast.
    * imports (Dict[str, object]) - The objects which should be available while
      evaluating body_ast.
    * do_fixup (bool) - If True, fixes all scanned classes so that any base
      classes they have which are defined in body_ast will be patched up as
      such. So if you have a `class A(B)`, and also `class B(object)` in the
      same file, the returned `classes['A'].bases[0] is classes['B']` will be
      True.

  Returns (classes : Dict[str, Doc.Class], funcs : Dict[str, Doc.Func]) for all
  classes and functions found in body_ast.
  """
  assert isinstance(body_ast, (ast.ClassDef, ast.Module)), type(body_ast)

  classes = {}
  funcs = {}

  for node in body_ast.body:
    if isinstance(node, ast.ClassDef):
      if not node.name.startswith('_'):
        classes[node.name] = parse_class(node, relpath, imports)
    elif isinstance(node, ast.FunctionDef):
      ok = (
        not node.name.startswith('_') or
        (node.name.startswith('__') and node.name.endswith('__'))
      )
      if ok:
        funcs[node.name] = parse_func(node, relpath, imports)

  if do_fixup:
    # frequently classes in a file inherit from other classes in the same file.
    # Do a best effort scan to re-attribute class bases when possible.
    for v in classes.values():
      for i, b in enumerate(v.bases):
        if isinstance(b, str):
          if b in classes:
            v.bases[i] = classes[b]

  return classes, funcs


def parse_class(class_ast, relpath, imports):
  """Parses a class AST object.

  Args:
    * class_ast (ast.ClassDef) - The class definition to parse.
    * relpath (str) - The posix-style relative path which should be associated
      with the code in class_ast.
    * imports (Dict[str, object]) - The objects which should be available while
      evaluating class_ast.

  Returns Doc.Class proto message.
  """
  assert isinstance(class_ast, ast.ClassDef), type(class_ast)

  classes, funcs = _extract_classes_funcs(class_ast, relpath, imports, False)

  ret = doc.Doc.Class(
    relpath=relpath,
    name=class_ast.name,
    docstring=ast.get_docstring(class_ast) or '',
    lineno=class_ast.lineno,
    classes=classes,
    funcs=funcs,
  )

  for b in class_ast.bases:
    item = _apply_imports_to_unparsed_expression(b, imports)
    if isinstance(item, str):
      ret.bases.add(generic=item)
    else:
      ret.bases.add(known=item.__module__+'.'+item.__name__)

  return ret


def parse_deps(repo_name, mod_ast, relpath):
  """Finds and parses the `DEPS` variable out of `mod_ast`.

  Args:
    * repo_name (str) - The implicit repo_name for DEPS entries which do not
      specify one.
    * mod_ast (ast.Module) - The Python module AST to parse from.
    * relpath (str) - The posix-style relative path which should be associated
      with the code in class_ast.

  Returns Doc.Deps proto message.
  """
  assert isinstance(mod_ast, ast.Module), type(mod_ast)
  ret = None

  DEPS, lineno = _find_value_of(mod_ast, 'DEPS')
  if DEPS:
    ret = doc.Doc.Deps(
      relpath=relpath,
      lineno=lineno,
    )
    spec = parse_deps_spec(repo_name, ast.literal_eval(_unparse(DEPS)))
    for dep_repo_name, mod_name in sorted(spec.values()):
      ret.module_links.add(repo_name=dep_repo_name, name=mod_name)

  return ret


def extract_jsonish_assignments(mod_ast):
  """This extracts all single assignments where the target is a name, and the
  value is a simple 'jsonish' statement (aka Python literal).

  The result is returned as a dictionary of name to the decoded literal.

  Example:
    Foo = "hello"
    Bar = [1, 2, "something"]
    Other, Things = range(2)  # not single assignment
    Bogus = object()  # not a Python literal
    # returns: {"Foo": "hello", "Bar": [1, 2, "something"]}
  """
  ret = {}
  for node in mod_ast.body:
    if not isinstance(node, ast.Assign):
      continue
    if len(node.targets) != 1:
      continue
    if not isinstance(node.targets[0], ast.Name):
      continue
    try:
      ret[node.targets[0].id] = ast.literal_eval(node.value)
    except (KeyError, ValueError):
      pass
  return ret


def parse_parameter(param):
  """Parses a recipe parameter into a Doc.Parameter.

  Args:
    * param (recipe_api.Property) - The parameter to parse.

  Returns Doc.Parameter.
  """
  assert isinstance(param, recipe_api.Property), type(param)
  default = None
  if param._default is not recipe_api.PROPERTY_SENTINEL:
    default = json.dumps(param._default)

  return doc.Doc.Parameter(
    docstring=param.help,
    kind=param.kind.schema_proto() if param.kind else None,
    default_json=default)


MOCK_IMPORTS_PARAMETERS = _expand_mock_imports(
  _property_imports, _config_imports)
ALL_IMPORTS.update(MOCK_IMPORTS_PARAMETERS)


def parse_parameters(mod_ast, relpath):
  """Parses a set of recipe parameters from the PROPERTIES variable.

  Args:
    * mod_ast (ast.Module) - The parsed Python module code.
    * relpath (str) - The posix-style relative path which should be associated
      with the code in mod_ast.

  Returns Doc.Parameters.
  """
  assert isinstance(mod_ast, ast.Module), type(mod_ast)
  parameters, lineno = _find_value_of(mod_ast, 'PROPERTIES')
  if not parameters:
    return None

  if not isinstance(parameters, ast.Dict):
    # TODO(iannucci): Docs for new-style Protobuf PROPERTIES.
    return None

  imports = _parse_mock_imports(mod_ast, MOCK_IMPORTS_PARAMETERS)
  imports.update(extract_jsonish_assignments(mod_ast))
  data = eval(_unparse(parameters), imports, {'basestring': basestring})
  if not data:
    return None

  for k, v in sorted(data.items()):
    data[k] = parse_parameter(v)

  return doc.Doc.Parameters(relpath=relpath, lineno=lineno, parameters=data)


def parse_func(func_ast, relpath, imports):
  """Parses a function into a Doc.Func.

  Args:
    * func_ast (ast.FunctionDef) - The function to parse.
    * relpath (str) - The posix-style relative path which should be associated
      with the code in func_ast.
    * imports (Dict[str, object]) - The symbols to include during the evaluation
      of `func_ast`.

  Returns Doc.Func.
  """
  assert isinstance(func_ast, ast.FunctionDef), type(func_ast)
  # In python3.8, the lineno was fixed to point to the line of func def while
  # it points to its first decorator in earlier versions (for details, see -
  # bugs.python.org/issue33211). Force it to point back to the first decorator
  # in order to generate the same README.recipes.md file.
  # TODO(crbug.com/1147793): remove this hack post migration.
  lineno = func_ast.lineno
  deco_list = getattr(func_ast, 'decorator_list', [])
  if len(deco_list) > 0:
    lineno = deco_list[0].lineno
  ret = doc.Doc.Func(
    name=func_ast.name,
    relpath=relpath,
    lineno=lineno,
    docstring=ast.get_docstring(func_ast) or '',
  )

  for exp in func_ast.decorator_list:
    item = _apply_imports_to_unparsed_expression(exp, imports)
    if isinstance(item, str):
      ret.decorators.add(generic=item)
    else:
      ret.decorators.add(known=item.__module__+'.'+item.__name__)

  ret.signature = _unparse(func_ast.args).strip()
  return ret


MOCK_IMPORTS_RECIPE = _expand_mock_imports(
 _util_imports, _decorator_imports, _placeholder_imports)
ALL_IMPORTS.update(MOCK_IMPORTS_RECIPE)


def parse_recipe(recipe):
  """Parses a recipe object into a Doc.Recipe.

  Args:
    * recipe (Recipe) - The recipe object to parse.

  Returns Doc.Recipe.
  """
  assert isinstance(recipe, Recipe), type(recipe)
  relpath = _to_posix(recipe.relpath)

  recipe_ast = _grab_ast(recipe.repo, recipe.path)
  if not recipe_ast:
    return None
  classes, funcs = _extract_classes_funcs(recipe_ast, relpath,
                                          MOCK_IMPORTS_RECIPE)
  funcs.pop('GenTests', None)

  return doc.Doc.Recipe(
    name=recipe.name,
    relpath=relpath,
    docstring=ast.get_docstring(recipe_ast) or '',
    deps=parse_deps(recipe.repo.name, recipe_ast, relpath),
    parameters=parse_parameters(recipe_ast, relpath),
    classes=classes,
    funcs=funcs,
    python_version_compatibility=recipe.python_version_compatibility,
  )


MOCK_IMPORTS_MODULE = _expand_mock_imports(
  _recipe_api_class_imports, _decorator_imports, _placeholder_imports)
ALL_IMPORTS.update(MOCK_IMPORTS_MODULE)


def parse_module(module):
  """Parses a recipe module object into a Doc.Module.

  Args:
    * recipe (RecipeModule) - The module object to parse.

  Returns Doc.Module.
  """
  assert isinstance(module, RecipeModule), type(module)
  relpath = _to_posix(module.relpath)

  api = _grab_ast(module.repo, os.path.join(module.path, 'api.py'))
  if not api:
    return None

  init = _grab_ast(module.repo, os.path.join(module.path, '__init__.py'))
  if not init:
    return None

  imports = _parse_mock_imports(api, MOCK_IMPORTS_MODULE)
  classes, funcs = _extract_classes_funcs(
    api, posixpath.join(relpath, 'api.py'), imports)

  api_class = None
  for name, val in sorted(classes.items()):
    if any(b.known in _recipe_api_class_imports for b in val.bases):
      api_class = classes.pop(name)
      break
  if not api_class:
    LOGGER.error('could not determine main RecipeApi class: %r', relpath)
    return None

  init_relpath = posixpath.join(relpath, '__init__.py')

  return doc.Doc.Module(
    name=module.name,
    relpath=relpath,
    docstring=ast.get_docstring(api) or '',
    api_class=api_class,
    classes=classes,
    funcs=funcs,
    deps=parse_deps(module.repo.name, init, init_relpath),
    parameters=parse_parameters(init, init_relpath),
    python_version_compatibility=module.python_version_compatibility,
  )


def parse_repo(repo):
  """Parses a recipe repo object into a Doc.Repo.

  Args:
    * recipe (RecipeRepo) - The repo to parse.

  Returns Doc.Repo.
  """
  assert isinstance(repo, RecipeRepo), type(repo)
  ret = doc.Doc.Repo(repo_name=repo.name)
  ret.specs[repo.name].CopyFrom(repo.recipes_cfg_pb2)
  for dep_repo_name in repo.recipes_cfg_pb2.deps:
    ret.specs[dep_repo_name].CopyFrom(
        repo.recipe_deps.repos[dep_repo_name].recipes_cfg_pb2)

  readme = join(repo.recipes_root_path, 'README.recipes.intro.md')
  if os.path.isfile(readme):
    with open(readme, 'rb') as f:
      ret.docstring = f.read()

  for module in repo.modules.values():
    mod = parse_module(module)
    if mod:
      ret.recipe_modules[module.name].CopyFrom(mod)

  for recipe in repo.recipes.values():
    recipe = parse_recipe(recipe)
    if recipe:
      ret.recipes[recipe.name].CopyFrom(recipe)

  return ret


RECIPE_ENGINE_URL = 'https://chromium.googlesource.com/infra/luci/recipes-py'


def _set_known_objects(base):
  """Populates `base` with all registered known objects.

  Args:
    * base (Doc.Repo) - The repo doc message to populate.
  """
  assert isinstance(base, doc.Doc.Repo), type(base)

  source_cache = {}

  def _add_it(key, fname, target):
    relpath = os.path.relpath(fname, RECIPE_ENGINE_BASE)
    for node in source_cache[fname].body:
      if isinstance(node, ast.ClassDef) and node.name == target:
        # This is a class definition in the form of:
        #   def Target(...)
        base.known_objects[key].klass.CopyFrom(parse_class(node, relpath, {}))
        return
      elif isinstance(node, ast.FunctionDef) and node.name == target:
        # This is a function definition in the form of:
        #   def Target(...)
        base.known_objects[key].func.CopyFrom(parse_func(node, relpath, {}))
        return
      elif isinstance(node, ast.Assign) and node.targets[0].id == target:
        # This is an alias in the form of:
        #   Target = RealImplementation
        _add_it(key, fname, node.value.id)
        return

    raise ValueError('could not find %r in %r' % (key, relpath))

  for k, v in KNOWN_OBJECTS.items():
    base.known_objects[k].url = RECIPE_ENGINE_URL
    _, target = k.rsplit('.', 1)
    fname = inspect.getsourcefile(v)
    if fname not in source_cache:
      # we load and cache the whole source file so that ast.parse gets the right
      # line numbers for all the definitions.
      source_lines, _ = inspect.findsource(v)
      source_cache[fname] = ast.parse(''.join(source_lines), fname)

    _add_it(k, fname, target)


def regenerate_doc(repo, output_file):
  """Rewrites `README.recipes.md` for the given recipe repo to the given output
  file.

  Args:
    * repo (RecipeRepo) - The repo to regenerate the markdown docs for.
    * output_file (I/O classes) - where the markdown docs will be printed.
  """
  assert isinstance(repo, RecipeRepo), type(repo)
  node = parse_repo(repo)
  _set_known_objects(node)
  doc_markdown.Emit(doc_markdown.Printer(output_file), node)


def doc_diff(repo):
  """Check if the `README.recipes.md` is changed and return the diff as a list
  of lines.

  Args:
    * repo (RecipeRepo) - The repo for this readme file.

  Returns boolean.
  """
  if repo.recipes_cfg_pb2.no_docs:
    new_lines = []
  else:
    with StringIO() as outf:
      regenerate_doc(repo, outf)
      new_lines = outf.getvalue().splitlines(keepends=True)

  if os.path.exists(repo.readme_path):
    with open(repo.readme_path, 'r', encoding='utf-8') as oldfile:
      old_lines = oldfile.read().splitlines(keepends=True)
  else:
    old_lines = []

  return list(difflib.unified_diff(
      old_lines, new_lines,
      fromfile='current', tofile='actual'))


def main(args):
  # defer to regenerate_doc for consistency between train and 'doc --kind gen'
  repo = args.recipe_deps.main_repo
  if repo.recipes_cfg_pb2.no_docs:
    LOGGER.warning('"no_docs" is set in recipes.cfg, generating docs anyway')

  if args.kind == 'gen':
    if not args.check:
      print('Generating README.recipes.md')
      with open(repo.readme_path, 'w', encoding='utf-8') as outf:
        regenerate_doc(repo, outf)
      return 0

    diff = doc_diff(repo)
    if not diff:
      return 0

    print('Found diff in README.recipes.md. Run `recipes.py doc` to regenerate.')
    for line in diff:
      print(line, end='')
    return 1

  if args.recipe:
    node = parse_recipe(args.recipe_deps.recipes[args.recipe])
  else:
    node = parse_repo(repo)

  _set_known_objects(node)

  if args.kind == 'jsonpb':
    sys.stdout.write(jsonpb.MessageToJson(
      node, including_default_value_fields=True,
      preserving_proto_field_name=True))
  elif args.kind == 'binarypb':
    sys.stdout.write(node.SerializeToString())
  elif args.kind == 'textpb':
    sys.stdout.write(textpb.MessageToString(node))
  elif args.kind == 'markdown':
    doc_markdown.Emit(doc_markdown.Printer(sys.stdout), node)
  else:
    raise NotImplementedError('--kind=%s' % args.kind)
