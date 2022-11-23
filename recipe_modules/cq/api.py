# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Recipe API for LUCI CQ, the pre-commit testing system."""

from future.utils import iteritems

import re

from google.protobuf import json_format as json_pb

from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb2

from recipe_engine import recipe_api


class CQApi(recipe_api.RecipeApi):
  """This module provides recipe API of LUCI CQ, aka pre-commit testing system.

  The CQ service is being replaced with a service now named LUCI Change
  Verifier (CV); for more information see:
    https://chromium.googlesource.com/infra/luci/luci-go/+/HEAD/cv

  TODO(qyearsley): Rename parts of this from CQ -> CV as appropriate.
  """

  # Common Run modes.
  DRY_RUN = 'DRY_RUN'
  QUICK_DRY_RUN = 'QUICK_DRY_RUN'
  FULL_RUN = 'FULL_RUN'

  class CQInactive(Exception):
    """Incorrect usage of CQApi method requiring active CQ."""

  def __init__(self, input_props, **kwargs):
    super(CQApi, self).__init__(**kwargs)
    self._input = input_props
    self._active = False
    self._output = cq_pb2.Output()

  def initialize(self):
    if self._input.active or (
      # legacy style
      'dry_run' in self.m.properties.get('$recipe_engine/cq', {})):
      self._active = True
    if self._active and not self._input.run_mode:
      # backfill
      self._input.run_mode = (
        self.DRY_RUN if self._input.dry_run else self.FULL_RUN)

  @property
  def active(self):
    """Returns whether CQ is active for this build."""
    return self._active

  @property
  def run_mode(self):
    """Returns the mode(str) of the CQ Run that triggers this build.

    Raises:
      CQInactive if CQ is not active for this build.
    """
    self._enforce_active()
    return self._input.run_mode

  @property
  def experimental(self):
    """Returns whether this build is triggered for a CQ experimental builder.

    See `Builder.experiment_percentage` doc in [CQ
    config](https://chromium.googlesource.com/infra/luci/luci-go/+/main/cv/api/config/v2/config.proto)

    Raises:
      CQInactive if CQ is not active for this build.
    """
    self._enforce_active()
    return self._input.experimental

  @property
  def top_level(self):
    """Returns whether CQ triggered this build directly.

    Can be spoofed. *DO NOT USE FOR SECURITY CHECKS.*

    Raises:
      CQInactive if CQ is not active for this build.
    """
    self._enforce_active()
    return self._input.top_level

  @property
  def ordered_gerrit_changes(self):
    """Returns list[bb_common_pb2.GerritChange] in order in which CLs should be
    applied or submitted.

    Raises:
      CQInactive if CQ is not active for this build.
    """
    self._enforce_active()
    assert self.m.buildbucket.build.input.gerrit_changes, (
        'you must simulate buildbucket.input.gerrit_changes in your test '
        'in order to use api.cq.ordered_gerrit_changes')
    return self.m.buildbucket.build.input.gerrit_changes

  @property
  def props_for_child_build(self):
    """Returns properties dict meant to be passed to child builds.

    These will preserve the CQ context of the current build in the
    about-to-be-triggered child build.

    ```python
    properties = {'foo': bar, 'protolike': proto_message}
    properties.update(api.cq.props_for_child_build)
    req = api.buildbucket.schedule_request(
        builder='child',
        gerrit_changes=list(api.buildbucket.build.input.gerrit_changes),
        properties=properties)
    child_builds = api.buildbucket.schedule([req])
    api.cq.record_triggered_builds(*child_builds)
    ```

    The contents of returned dict should be treated as opaque blob,
    it may be changed without notice.
    """
    if not self._input.active:
      return {}
    msg = cq_pb2.Input()
    msg.CopyFrom(self._input)
    msg.top_level = False
    return {'$recipe_engine/cq':
        json_pb.MessageToDict(msg, preserving_proto_field_name=True)}

  @property
  def cl_group_key(self):
    """Returns a string that is unique for a current set of Gerrit change
    patchsets (or, equivalently, buildsets).

    The same `cl_group_key` will be used if another Attempt is made for the
    same set of changes at a different time.

    Raises:
      CQInactive if CQ is not active for this build.
    """
    return self._extract_unique_cq_tag('cl_group_key')

  @property
  def equivalent_cl_group_key(self):
    """Returns a string that is unique for a given set of Gerrit changes
    disregarding trivial patchset differences.

    For example, when a new "trivial" patchset is uploaded, then the
    cl_group_key will change but the equivalent_cl_group_key will stay the same.

    Raises:
      CQInactive if CQ is not active for this build.
    """
    return self._extract_unique_cq_tag('equivalent_cl_group_key')

  @property
  def triggered_build_ids(self):
    """Returns recorded Buildbucket build IDs as a list of integers."""
    return [bid for bid in self._output.triggered_build_ids]

  def record_triggered_builds(self, *builds):
    """Adds IDs of given Buildbucket builds to the list of triggered build IDs.

    Must be called after some step.

    Expected usage:
      ```python
        api.cq.record_triggered_builds(*api.buildbucket.schedule([req1, req2]))
      ```

    Args:
      * [`Build`](https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto)
        objects, typically returned by `api.buildbucket.schedule`.
    """
    return self.record_triggered_build_ids(*[b.id for b in builds])

  def record_triggered_build_ids(self, *build_ids):
    """Adds the given Buildbucket build IDs to the list of triggered build IDs.

    Must be called after some step.

    Args:
      * build_ids (list of int or string): Buildbucket build IDs.
    """
    if not build_ids:
      return
    self._output.triggered_build_ids.extend(int(bid) for bid in build_ids)
    self._write_output_props(
      triggered_build_ids=[
        str(bid) for bid in self._output.triggered_build_ids
      ],
    )

  @property
  def do_not_retry_build(self):
    return self._output.retry == cq_pb2.Output.OUTPUT_RETRY_DENIED

  def set_do_not_retry_build(self):
    """Instruct CQ to not retry this build.

    This mechanism is used to reduce duration of CQ attempt and save testing
    capacity if retrying will likely return an identical result.
    """
    if self._output.retry == cq_pb2.Output.OUTPUT_RETRY_DENIED:
      return
    self._output.retry = cq_pb2.Output.OUTPUT_RETRY_DENIED
    self._write_output_props(
      cur_step= self.m.step('TRYJOB DO NOT RETRY', cmd=None),
      do_not_retry=True,
    )

  @property
  def allowed_reuse_modes(self):
    return [m for m in self._output.reusability.mode_allowlist]

  def allow_reuse_for(self, *modes):
    """Instructs CQ that this build can be reused in a future Run if
    and only if its mode is in the provided modes.

    Overwrites all previously set values.
    """
    # TODO(yiwzhang): Expose low-level method to modify reuse if needed.
    if not modes:
      raise ValueError('expected at least 1 modes, got 0')
    del self._output.reusability.mode_allowlist[:]
    self._output.reusability.mode_allowlist.extend(modes)
    # TODO(crbug/1225047): Stop populating _output.reuse after CQDaemon is
    # decommissioned. For now, CQDaemon will still use this field to decide
    # reusability.
    del self._output.reuse[:]
    self._output.reuse.extend(
        cq_pb2.Output.Reuse(mode_regexp=m) for m in modes)
    self._write_output_props()

  @property
  def owner_is_googler(self):
    """Returns whether the Run/Attempt owner is a Googler.

    DO NOT USE: this is a temporary workaround for crbug.com/1259887 that is
    supposed to be used by builders in Chrome project only.
    Raises:
      CQInactive if CQ is not active for this build.
      ValueError if the builder is not in Chrome project.
    """
    self._enforce_active()
    if (self.m.buildbucket.build.builder.project != 'chrome' and
        not self.m.buildbucket.build.builder.project.startswith('chrome-m')):
      raise ValueError('owner_is_googler can only be called for chrome project')
    return self._input.owner_is_googler

  def _extract_unique_cq_tag(self, suffix):
    key = 'cq_' + suffix
    self._enforce_active()
    for t in self.m.buildbucket.build.tags:
      if t.key == key:
        return t.value
    raise ValueError('Can\'t find tag with key %r' % key)  # pragma: nocover

  def _write_output_props(self, cur_step=None, **addition_props):
    # TODO(iannucci): add API to set properties regardless of the current step.
    if not cur_step:
      cur_step = self.m.step.active_result
      assert cur_step, 'must be called after some step'
    output = cq_pb2.Output()
    output.CopyFrom(self._output)
    cur_step.presentation.properties['$recipe_engine/cq/output'] = output
    for k, v in iteritems(addition_props):
      cur_step.presentation.properties[k] = v

  def _enforce_active(self):
    if not self._active:
      raise self.CQInactive()
