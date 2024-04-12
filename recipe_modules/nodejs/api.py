# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib

from recipe_engine import recipe_api


class NodeJSApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(NodeJSApi, self).__init__(**kwargs)
    self._installed = {}  # {Path: installed nodejs version there}

  @contextlib.contextmanager
  def __call__(self, version, path=None, cache=None):
    """Installs a Node.js toolchain and activates it in the environment.

    Installs it under the given `path`, defaulting to `[CACHE]/nodejs`. Various
    cache directories used by npm are placed under `cache`, defaulting to
    `[CACHE]/npmcache`.

    `version` will be used to construct CIPD package version for packages under
    https://chrome-infra-packages.appspot.com/p/infra/3pp/tools/nodejs/.

    To reuse the Node.js toolchain deployment and npm caches across builds,
    declare the corresponding named caches in Buildbucket configs. E.g. when
    using defaults:

        luci.builder(
            ...
            caches = [
                swarming.cache("nodejs"),
                swarming.cache("npmcache"),
            ],
        )

    Args:
      * version (str) - a Node.js version to install (e.g. `17.1.0`).
      * path (Path) - a path to install Node.js into.
      * cache (Path) - a path to put Node.js caches under.
    """
    path = path or self.m.path.cache_dir.join('nodejs')
    cache = cache or self.m.path.cache_dir.join('npmcache')
    with self.m.context(infra_steps=True):
      env, env_pfx = self._ensure_installed(version, path, cache)
    with self.m.context(env=env, env_prefixes=env_pfx):
      yield

  def _ensure_installed(self, version, path, cache):
    if self._installed.get(path) != version:
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package(
          'infra/3pp/tools/nodejs/${platform}', 'version:2@' + version)
      self.m.cipd.ensure(path, pkgs)
      self._installed[path] = version

    env = {
        # npm's content-addressed cache.
        'npm_config_cache': cache.join('npm'),
        # Where packages are installed when using 'npm -g ...'.
        'npm_config_prefix': cache.join('pfx'),
    }

    env_prefixes = {
        'PATH': [
            # Putting this in front of PATH (before `bin` from the CIPD package)
            # allows doing stuff like `npm install -g npm@8.1.4` and picking up
            # the updated `npm` binary from `<npm_config_prefix>/bin`.
            env['npm_config_prefix'].join('bin'),
            path.join('bin'),
        ],
    }

    return env, env_prefixes
