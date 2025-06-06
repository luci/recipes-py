# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Recipe API for LUCI Change Verifier.

LUCI Change Verifier is the pre-commit verification service that will replace
CQ daemon. See:
  https://chromium.googlesource.com/infra/luci/luci-go/+/HEAD/cv

This recipe module depends on the prpc binary being available in $PATH:
  https://godoc.org/go.chromium.org/luci/grpc/cmd/prpc

his recipe module depends on experimental API provided by LUCI CV and may
subject to change in the future. Please reach out to the LUCI team first if you
want to use this recipe module; file a ticket at:
https://bugs.chromium.org/p/chromium/issues/entry?components=Infra%3ELUCI%3EBuildService%3EPresubmit%3ECV
"""

from __future__ import annotations

from typing import Sequence

from google.protobuf import json_format

from PB.go.chromium.org.luci.cv.api.v0 import (
    run as run_pb,
    service_runs as service_runs_pb,
)

from recipe_engine import recipe_api
from RECIPE_MODULES.recipe_engine.cv import api as cv_api

# Take revision from
# https://ci.chromium.org/p/infra-internal/g/infra-packagers/console
DEFAULT_CIPD_VERSION = 'git_revision:eb3279d25a7fb5b62e5492727891ce8babac98a8'


class ChangeVerifierApi(recipe_api.RecipeApi):
  """This module provides recipe API of LUCI Change Verifier."""

  PROD_HOST = 'luci-change-verifier.appspot.com'
  DEV_HOST = 'luci-change-verifier-dev.appspot.com'

  GerritChangeTuple = tuple[str, int]

  def search_runs(
      self,
      project: str,
      cls: (Sequence[GerritChangeTuple | run_pb.GerritChange]
            | GerritChangeTuple | run_pb.GerritChange | None) = None,
      limit: int | None = None,
      step_name: str | None = None,
      dev: bool = False,
  ):
    """Searches for Runs.

    Args:
      * project: LUCI project name.
      * cls: CLs, specified as (host, change number) tuples or
        run_pb.GerritChanges. A single tuple or GerritChange may also be passed.
        All Runs returned must include all of the given CLs, and Runs may also
        contain other CLs.
      * limit: max number of Runs to return. Defaults to 32.
      * step_name: optional custom step name in RPC steps.
      * dev: whether to use the dev instance of Change Verifier.

    Returns:
      A list of CV Runs ordered newest to oldest that match the given criteria.
    """
    assert limit is None or limit >= 0, limit
    limit = 32 if limit is None else limit

    assert isinstance(cls, (list, tuple, type(None))), cls
    gerrit_changes = None
    if isinstance(cls, tuple) or isinstance(cls, run_pb.GerritChange):
      cls = [cls]
    if cls is not None:
      gerrit_changes = []
      for cl in cls:
        if isinstance(cl, tuple):
          assert len(cl) == 2, cls
          host, change = cl
          assert isinstance(change, int), change
          gerrit_change = run_pb.GerritChange(host=host, change=change)
        else:
          assert isinstance(cl, run_pb.GerritChange)
          gerrit_change = cl
        assert gerrit_change.host.endswith(
            '-review.googlesource.com'), gerrit_change.host
        gerrit_changes.append(gerrit_change)

    runs = []
    input_data = service_runs_pb.SearchRunsRequest(
        predicate=service_runs_pb.RunPredicate(
            project=project, gerrit_changes=gerrit_changes))

    with self.m.step.nest(step_name or 'luci-change-verifier.SearchRuns'):
      page = 0
      while len(runs) < limit:
        # The result of a successful call will be a SearchRunsResponse
        # which includes runs and next_page_token.
        page += 1
        response = self._rpc(
            host=self.DEV_HOST if dev else self.PROD_HOST,
            service='cv.v0.Runs',
            method='SearchRuns',
            input_message=input_data,
            output_class=service_runs_pb.SearchRunsResponse,
            step_name="request page %d" % page)
        runs.extend(response.runs)
        page_token = response.next_page_token
        if not response.next_page_token:
          break
        input_data.page_token = response.next_page_token

    return runs[:limit]

  def _rpc(self,
           host: str,
           service: str,
           method: str,
           input_message,
           output_class,
           step_name: str | None = None):
    """Makes a RPC to the Change Verifier service.

    TODO(qyearsley): prpc could be encapsulated in a separate module.

    Args:
      * host: Service host, e.g. "luci-change-verifier.appspot.com".
      * service: the full service name, e.g. "cv.v0.Runs".
      * method: the name of the method, e.g. "SearchRuns".
      * input_message (proto message): A request proto message.
      * output_class (proto message class): The expected output proto class.
      * step_name: optional custom step name.

    Returns:
      A proto message (if successful).

    Raises:
      InfraFailure on prpc request failure.
    """
    step_name = step_name or ('luci-change-verifier.' + method)
    args = ['prpc', 'call', '-format=json', host, service + '.' + method]
    step_result = self.m.step(
        step_name,
        args,
        stdin=self.m.proto.input(input_message, 'JSONPB'),
        stdout=self.m.proto.output(output_class, 'JSONPB'),
        infra_step=True)
    return step_result.stdout

  @property
  def _version(self) -> str:
    if self._test_data.enabled:
      return 'swarming_module_pin'
    return DEFAULT_CIPD_VERSION  # pragma: no cover

  @property
  def _luci_cv(self) -> config_types.Path:
    return self.m.cipd.ensure_tool('infra/tools/luci-cv/${platform}',
                                   self._version)

  def match_config(self,
                   host: str,
                   change: int,
                   project: str | None = None,
                   config_name: str = cv_api.CONFIG_FILE) -> str | None:
    """Retrieve the applicable CV group for a given change."""
    assert host.endswith('-review.googlesource.com'), host
    assert isinstance(change, int), change
    config = self.m.luci_config.fetch_config_raw(config_name, project=project)

    change_url = f'{host}/{change}'
    if not change_url.startswith('https://'):
      change_url = f'https://{change_url}'

    cmd = [
        self._luci_cv,
        'match-config',
        self.m.raw_io.input_text(config),
        change_url,
    ]

    try:
      # TODO: b/369924790 - Switch to a JSON output option.
      step = self.m.step(
          'match-config',
          cmd,
          stdout=self.m.raw_io.output_text(),
          step_test_data=lambda: self.m.raw_io.test_api.stream_output_text('''
https://chromium-review.googlesource.com/123456:
  Location: Host: chromium-review.googlesource.com, Repo: chromium/src, Ref: refs/heads/main
  Matched: chromium-src
          '''),
      )

    except self.m.step.StepFailure:
      return None

    step.presentation.links['gerrit'] = change_url
    for line in step.stdout.splitlines():
      matched = 'Matched:'
      if line.strip().startswith(matched):
        result = line.strip().removeprefix(matched).strip()
        step.presentation.step_summary_text = result
        return result

    return None  # pragma: no cover
