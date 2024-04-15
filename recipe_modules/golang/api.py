# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib

from recipe_engine import recipe_api


class GolangApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(GolangApi, self).__init__(**kwargs)
    self._installed = {}  # {Path: installed Go version there}

  @contextlib.contextmanager
  def __call__(self, version, path=None, cache=None):
    """Installs a Golang SDK and activates it in the environment.

    Installs it under the given `path`, defaulting to `[CACHE]/golang`. Various
    cache directories used by Go are placed under `cache`, defaulting to
    `[CACHE]/gocache`.

    `version` will be used to construct CIPD package version for packages under
    https://chrome-infra-packages.appspot.com/p/infra/3pp/tools/go/.

    To reuse the Go SDK deployment and caches across builds, declare the
    corresponding named caches in Buildbucket configs. E.g. when using defaults:

        luci.builder(
            ...
            caches = [
                swarming.cache("golang"),
                swarming.cache("gocache"),
            ],
        )

    Note: CGO is disabled on Windows currently, since Windows doesn't have
    a C compiler available by default.

    Args:
      * version (str) - a Go version to install (e.g. `1.16.10`).
      * path (Path) - a path to install Go into.
      * cache (Path) - a path to put Go caches under.
    """
    path = path or self.m.path.cache_dir / 'golang'
    cache = cache or self.m.path.cache_dir / 'gocache'
    with self.m.context(infra_steps=True):
      env, env_pfx, env_sfx = self._ensure_installed(version, path, cache)
    with self.m.context(env=env, env_prefixes=env_pfx, env_suffixes=env_sfx):
      yield

  def _ensure_installed(self, version, path, cache):
    if self._installed.get(path) != version:
      pkgs = self.m.cipd.EnsureFile()
      pkgs.add_package('infra/3pp/tools/go/${platform}', 'version:2@' + version)
      self.m.cipd.ensure(path, pkgs)
      self._installed[path] = version

    env = {
        'GOROOT': path,
        'GO111MODULE': 'on',
        'GOPROXY': None,
        'GOPATH': None,
        'GOPRIVATE': '*.googlesource.com,*.git.corp.google.com,google.com',
        'GOPACKAGESDRIVER': 'off',
        'GOTOOLCHAIN': 'local',

        # Caches and GOBIN can be shared across Go versions: defaults are shared
        # hardcoded paths under '~'.
        'GOBIN': cache / 'bin',
        'GOCACHE': cache / 'cache',
        'GOMODCACHE': cache / 'modcache',
    }

    # Disable cgo on Windows by default since it lacks a C compiler by default.
    if self.m.platform.is_win:
      env['CGO_ENABLED'] = '0'

    env_prefixes = {
        'PATH': [path / 'bin'],
    }

    env_suffixes = {
        'PATH': [env['GOBIN']],
    }

    return env, env_prefixes, env_suffixes
