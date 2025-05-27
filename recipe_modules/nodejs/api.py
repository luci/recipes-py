# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import contextlib

from recipe_engine import recipe_api


class NodeJSApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super().__init__(**kwargs)
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
    path = path or self.m.path.cache_dir / 'nodejs'
    cache = cache or self.m.path.cache_dir / 'npmcache'
    with self.m.context(infra_steps=True):
      env, env_pfx = self._ensure_installed(version, path, cache)
    with self.m.context(env=env, env_prefixes=env_pfx):
      yield

  def _ensure_installed(self, version, path, cache):
    if self._installed.get(path) != version:
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package(
          'infra/3pp/tools/nodejs/${platform}', _3pp_version(version))
      self.m.cipd.ensure(path, pkgs)
      self._installed[path] = version

    env = {
        # npm's content-addressed cache.
        'npm_config_cache': cache / 'npm',
        # Where packages are installed when using 'npm -g ...'.
        'npm_config_prefix': cache / 'pfx',
        # Potential workaround for b/409370331.
        'UV_USE_IO_URING': '0',
    }

    env_prefixes = {
        'PATH': [
            # Putting this in front of PATH (before `bin` from the CIPD package)
            # allows doing stuff like `npm install -g npm@8.1.4` and picking up
            # the updated `npm` binary from `<npm_config_prefix>/bin`.
            env['npm_config_prefix']
            if self.m.platform.is_win else env['npm_config_prefix'] / 'bin',
            path if self.m.platform.is_win else path / 'bin',
        ],
    }

    return env, env_prefixes


def _3pp_version(version):
  """Returns 3pp CIPD package version given the nodejs version.

  This is just a look up table. Everything <=v17 is "version:v2@". Everything
  >=v23 is "version:v3@". In between there's a mess which we hardcode.
  """
  major = int(version.split('.')[0])
  if major <= 17:
    return 'version:2@' + version
  if major >=23:
    return 'version:3@' + version

  KNOWN_EPOCH2_VERSIONS = [
      '18.0.0',
      '18.1.0',
      '18.2.0',
      '18.3.0',
      '18.4.0',
      '18.5.0',
      '18.6.0',
      '18.7.0',
      '18.8.0',
      '18.9.0',
      '18.9.1',
      '18.10.0',
      '18.11.0',
      '18.16.0',
      '18.16.1',
      '18.17.0',
      '18.17.1',
      '18.18.0',
      '18.18.1',
      '18.18.2',
      '18.19.0',
      '18.19.1',
      '18.20.0',
      '18.20.1',
      '18.20.2',
      '19.0.0',
      '19.0.1',
      '19.1.0',
      '19.2.0',
      '19.3.0',
      '19.4.0',
      '19.5.0',
      '19.6.0',
      '19.6.1',
      '19.7.0',
      '19.8.0',
      '19.8.1',
      '19.9.0',
      '20.0.0',
      '20.1.0',
      '20.2.0',
      '20.3.0',
      '20.3.1',
      '20.4.0',
      '20.5.0',
      '20.5.1',
      '20.6.0',
      '20.6.1',
      '20.7.0',
      '20.8.0',
      '20.8.1',
      '20.10.0',
      '20.11.0',
      '20.11.1',
      '20.12.0',
      '20.12.1',
      '20.12.2',
      '20.13.0',
      '20.13.1',
      '20.14.0',
      '21.0.0',
      '21.1.0',
      '21.2.0',
      '21.3.0',
      '21.4.0',
      '21.5.0',
      '21.6.0',
      '21.6.1',
      '21.6.2',
      '21.7.0',
      '21.7.1',
      '21.7.2',
      '21.7.3',
      '22.0.0',
      '22.1.0',
      '22.2.0',
      '22.3.0',
  ]

  if version in KNOWN_EPOCH2_VERSIONS:
    return 'version:2@' + version
  return 'version:3@' + version
