# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
from recipe_engine import recipe_api

# Usage of bcid_reporter recipe_module will have significant downstream impact
# and to avoid any production outage, we are pinning the latest known good build
# of the tool here. Upstream changes are intentionally left out.
_LATEST_STABLE_VERSION = 'git_revision:3d14b689ac33c182daa4c0602819ede40bb4e128'


class BcidReporterApi(recipe_api.RecipeApi):
  """API for interacting with Provenance server using the broker tool."""

  def __init__(self, **kwargs):
    super(BcidReporterApi, self).__init__(**kwargs)
    self._broker_bin = None

    if self._test_data.enabled:
      self._pid = self._test_data.get('pid', 12345)
    else:  # pragma: no cover
      self._pid = os.getpid()

  @property
  def bcid_reporter_path(self):
    """Returns the path to the broker binary.

    When the property is accessed the first time, the latest stable, released
    broker will be installed using cipd.
    """
    if self._broker_bin is None:
      reporter_dir = self.m.path['start_dir'].join('reporter')
      ensure_file = self.m.cipd.EnsureFile().add_package(
          'infra/tools/security/provenance_broker/${platform}',
          _LATEST_STABLE_VERSION)
      self.m.cipd.ensure(reporter_dir, ensure_file)
      self._broker_bin = reporter_dir.join('snoopy_broker')
    return self._broker_bin

  def report_stage(self, stage, server_url=None):
    """Reports task stage to local provenance server.

    Args:
      * stage (str) - The stage at which task is executing currently, e.g.
        "start". Concept of task stage is native to Provenance service, this is
        a way of self-reporting phase of a task's lifecycle. This information is
        used in conjunction with process-inspected data to make security policy
        decisions.
        Valid stages: (start, fetch, compile, upload, upload-complete, test).
      * server_url (Optional[str]) - URL for the local provenance server, the
        broker tool will use default if not specified.
    """
    args = [
      self.bcid_reporter_path,
      '-report-stage',
      '-stage',
      stage,
    ]

    if server_url:
      args.extend(['-backend-url', server_url])

    # When task starts, they must report recipe name and recipe's process id.
    if stage == "start":
      args.extend(['-recipe', self.m.properties['recipe']])
    if stage == "start":
      args.extend(['-pid', self._pid])

    self.m.step('snoop: report_stage', args)

  def report_cipd(self, digest, pkg, iid, server_url=None):
    """Reports cipd digest to local provenance server.

    This is used to report produced artifacts hash and metadata to provenance,
    it is used to generate provenance.

    Args:
      * digest (str) - The hash of the artifact.
      * pkg (str) - Name of the cipd package built.
      * iid (str) - Instance ID of the package.
      * server_url (Optional[str]) - URL for the local provenance server, the
        broker tool will use default if not specified.
    """
    args = [
      self.bcid_reporter_path,
      '-report-cipd',
      '-digest',
      digest,
      '-pkg-name',
      pkg,
      '-iid',
      iid,
    ]

    if server_url:
      args.extend(['-backend-url', server_url])

    self.m.step('snoop: report_cipd', args)

  def report_gcs(self, digest, guri, server_url=None):
    """Reports gcs digest to local provenance server.

    This is used to report produced artifacts hash and metadata to provenance,
    it is used to generate provenance.

    Args:
      * digest (str) - The hash of the artifact.
      * guri (str) - Name of the GCS artifact built. This is the unique GCS URI,
        e.g. gs://bucket/path/to/binary.
      * server_url (Optional[str]) - URL for the local provenance server, the
        broker tool will use default if not specified.
    """
    args = [
      self.bcid_reporter_path,
      '-report-gcs',
      '-digest',
      digest,
      '-gcs-uri',
      guri,
    ]

    if server_url:
      args.extend(['-backend-url', server_url])

    self.m.step('snoop: report_gcs', args)

  def report_sbom(self, digest, guri, sbom_subject, server_url=None):
    """Reports SBOM gcs digest to local provenance server.

    This is used to report the SBOM metadata to provenance, along with
    the hash of the artifact it represents. It is also used to generate
    provenance.

    Args:
      * digest (str) - The hash of the SBOM.
      * guri (str) - This is the unique GCS URI for the SBOM,
        e.g. gs://bucket/path/to/sbom.
      * sbom_subject (str) - The hash of the artifact the SBOM was produced
        for.
      * server_url (Optional[str]) - URL for the local provenance server, the
        broker tool will use default if not specified.
    """
    args = [
        self.bcid_reporter_path,
        '-report-gcs',
        '-digest',
        digest,
        '-gcs-uri',
        guri,
        '-sbom-subject',
        sbom_subject,
    ]

    if server_url:
      args.extend(['-backend-url', server_url])

    self.m.step('snoop: report_sbom', args)
