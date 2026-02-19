# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import datetime
import os

from recipe_engine import recipe_api
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

# Usage of bcid_reporter recipe_module will have significant downstream impact
# and to avoid any production outage, we are pinning the latest known good build
# of the tool here. Upstream changes are intentionally left out.
_LATEST_STABLE_VERSION = 'git_revision:94ca00f962f62fd49166b3d7fbeb0056dfc3499e'

# Spike is failing intermittently due to issues calling the swarming API, this
# retry can decorate each report method.
def retry(raise_on_failure=True):
  return exponential_retry(
      3, datetime.timedelta(seconds=5), raise_on_failure=raise_on_failure)


class BcidReporterApi(recipe_api.RecipeApi):
  """API for interacting with Provenance server using the broker tool."""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
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
      reporter_dir = self.m.path.start_dir / 'reporter'
      ensure_file = self.m.cipd.EnsureFile().add_package(
          'infra/tools/security/provenance_broker/${platform}',
          _LATEST_STABLE_VERSION)
      self.m.cipd.ensure(reporter_dir, ensure_file)
      self._broker_bin = reporter_dir / 'snoopy_broker'
    return self._broker_bin

  @retry(raise_on_failure=False)
  def report_stage(self, stage, server_url=None):
    """Reports task stage to local provenance server. This is best-effort and
    won't abort the execution on errors.

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

  @retry()
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

  @retry()
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

  @retry()
  def report_sbom(self, digest, guri, sbom_subjects=None, server_url=None):
    """Reports SBOM gcs digest to local provenance server.

    This is used to report the SBOM metadata to provenance, along with
    the hash of the artifact it represents. It is also used to generate
    provenance.

    Args:
      * digest (str) - The hash of the SBOM.
      * guri (str) - This is the unique GCS URI for the SBOM,
        e.g. gs://bucket/path/to/sbom.
      * sbom_subjects (str list or str) - The hash values corresponding to the
        artifacts that this SBOM covers.
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

    if isinstance(sbom_subjects, list):
      for s in sbom_subjects:
        args.extend(['-sbom-subject', s])
    elif isinstance(sbom_subjects, str):
      args.extend(['-sbom-subject', sbom_subjects])

    if server_url:
      args.extend(['-backend-url', server_url])

    self.m.step('snoop: report_sbom', args)

  def create_from_yaml(
      self,
      pkg_def,
      refs=None,
      tags=None,
      metadata=None,
      pkg_vars=None,
      compression_level=None,
      verification_timeout=None,
  ):
    """Builds and uploads a package based on on-disk YAML package definition
    file and reports cipd digest to local provenance server.

    This builds, uploads and reports the package in one step.

    Args:
      * pkg_def - The path to the yaml file.
      * refs - A list of ref names to set for the package instance.
      * tags - A map of tag name -> value to set for the package instance.
      * metadata - A list of metadata entries to attach.
      * pkg_vars - A map of var name -> value to use for vars
        referenced in package definition file.
      * compression_level - Deflate compression level. If None, defaults to 5
        (0 - disable, 1 - best speed, 9 - best compression).
      * verification_timeout - Duration string that controls the time to
        wait for backend-side package hash verification. Valid time units are
        "s", "m", "h". Default is "5m".

    Returns the CIPDApi.Pin instance.
    """
    package_path = self.m.path.mkstemp(prefix="bcid_cipd_")
    pin = self.m.cipd.build_from_yaml(pkg_def, package_path, pkg_vars,
                                      compression_level)
    pin = self.m.cipd.register(
        pin.package,
        package_path,
        refs,
        tags,
        metadata,
        verification_timeout,
    )

    try:
      package_hash = self.m.file.file_hash(package_path, test_data='deadbeef')
      self.report_cipd(package_hash, pin.package, pin.instance_id)
    except Exception:  # pragma: no cover
      self.m.step.active_result.presentation.status = self.m.step.WARNING
      raise

    return pin

  def create_from_pkg(
      self,
      pkg_def,
      refs=None,
      tags=None,
      metadata=None,
      compression_level=None,
      verification_timeout=None,
  ):
    """Builds and uploads a package based on a PackageDefinition object and
    reports cipd digest to local provenance server.

    This builds, uploads and reports the package in one step.

    Args:
      * pkg_def - The description of the package we want to create.
      * refs - A list of ref names to set for the package instance.
      * tags - A map of tag name -> value to set for the package instance.
      * metadata - A list of metadata entries to attach.
      * compression_level - Deflate compression level. If None, defaults to 5
        (0 - disable, 1 - best speed, 9 - best compression).
      * verification_timeout - Duration string that controls the time to
        wait for backend-side package hash verification. Valid time units are
        "s", "m", "h". Default is "5m".

    Returns the CIPDApi.Pin instance.
    """
    package_path = self.m.path.mkstemp(prefix="bcid_cipd_")
    pin = self.m.cipd.build_from_pkg(pkg_def, package_path, compression_level)
    pin = self.m.cipd.register(
        pin.package,
        package_path,
        refs,
        tags,
        metadata,
        verification_timeout,
    )

    try:
      package_hash = self.m.file.file_hash(package_path, test_data='deadbeef')
      self.report_cipd(package_hash, pin.package, pin.instance_id)
    except Exception:  # pragma: no cover
      self.m.step.active_result.presentation.status = self.m.step.WARNING

    return pin
