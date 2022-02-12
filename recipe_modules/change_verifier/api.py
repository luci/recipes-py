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

from google.protobuf import json_format

from PB.go.chromium.org.luci.cv.api.v0 import run as run_pb
from PB.go.chromium.org.luci.cv.api.v0 import service_runs as service_runs_pb

from recipe_engine import recipe_api


class ChangeVerifierApi(recipe_api.RecipeApi):
  """This module provides recipe API of LUCI Change Verifier."""

  PROD_HOST = 'luci-change-verifier.appspot.com'
  DEV_HOST = 'luci-change-verifier-dev.appspot.com'

  def search_runs(self, project, cls=None, limit=None, step_name=None,
                  dev=False):
    """Searches for Runs.

    Args:
      * project: LUCI project name.
      * cls (list[tuple[str, int]]|tuple[str, int]|None): CLs, specified as
        (host, change number) tuples. A single tuple may also be passed. All
        Runs returned must include all of the given CLs, and Runs may also
        contain other CLs.
      * limit (int): max number of Runs to return. Defaults to 32.
      * step_name (string): optional custom step name in RPC steps.
      * dev (bool): whether to use the dev instance of Change Verifier.

    Returns:
      A list of CV Runs ordered newest to oldest that match the given criteria.
    """
    assert limit is None or limit >= 0, limit
    limit = 32 if limit is None else limit

    assert isinstance(cls, (list, tuple, type(None))), cls
    gerrit_changes = None
    if isinstance(cls, tuple):
      cls = [cls]
    if cls is not None:
      assert all(len(cl_tuple) == 2 for cl_tuple in cls), cls
      gerrit_changes = []
      for (host, change) in cls:
        assert host.endswith('-review.googlesource.com'), host
        assert isinstance(change, int), change
        gerrit_changes.append(run_pb.GerritChange(host=host, change=change))

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
           host,
           service,
           method,
           input_message,
           output_class,
           step_name=None):
    """Makes a RPC to the Change Verifier service.

    TODO(qyearsley): prpc could be encapsulated in a separate module.

    Args:
      * host (string): Service host, e.g. "luci-change-verifier.appspot.com".
      * service (string): the full service name, e.g. "cv.v0.Runs".
      * method (string): the name of the method, e.g. "SearchRuns".
      * input_message (proto message): A request proto message.
      * output_class (proto message class): The expected output proto class.
      * step_name (string): optional custom step name.

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
