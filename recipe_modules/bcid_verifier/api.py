# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""API for interacting with Software Verifier.

To successfully authenticate to this API, you must have the
https://www.googleapis.com/auth/bcid_verify OAuth scope.
"""

from __future__ import annotations

from recipe_engine import recipe_api

# Usage of the bcid_verifier recipe_module will have significant downstream
# impact and to avoid any production outage, we pin the latest known good build
# of the tool here. Upstream changes are intentionally left out.
_LATEST_STABLE_VERSION = 'git_revision:c83273f7e3850f045420d836d5d92d64dcad3667'

VERIFY_FOR_ENFORCEMENT = "VERIFY_FOR_ENFORCEMENT"
VERIFY_FOR_LOGGING = "VERIFY_FOR_LOGGING"

class BcidVerifierApi(recipe_api.RecipeApi):
  """API for interacting with Software Verifier"""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self.verification_mode = VERIFY_FOR_ENFORCEMENT

  @property
  def bcid_verifier_path(self):
    """Returns the path to the bcid_verifier binary.

    When the property is accessed the first time, the latest stable, released
    version of bcid_verifier will be installed using CIPD.
    """
    return self.m.cipd.ensure_tool(
        "infra/tools/security/bcid_verifier/${platform}", _LATEST_STABLE_VERSION)

  def verify_provenance(
      self,
      bcid_policy: str,
      artifact_path: str,
      attestation_path: str,
      log_only_mode: bool = False,
  ):
    """
    Calls the BCID Software Verifier API to verify provenance for an
    artifact.

    Args:
      * bcid_policy: This field name is slightly misleading, and it would be
        better if it was called resource_uri. This arg represents the full
        ResourceURI to use when verifying this artifact. It should include both
        the name of a valid BCID Policy or Resource Prefix, and the unique path
        to the artifact protected by this verification. As an example, a call to
        SoftwareVerifier to verify the provenance of a Chrome artifact before
        signing might use the following structure.
          bcid_policy: chrome_app://chrome/desktop/win/
          artifact path: chrome-signed/desktop-5c0tCh/132.0.6834.0/win-clang/chrome.zip
        Which would result in the following resource URI to use here:
          chrome_app://chrome/desktop/win/chrome-signed/desktop-5c0tCh/132.0.6834.0/win-clang/chrome.zip

      * artifact_path: Local file path to the artifact to be verified.
      * attestation_path: Local file path to the attestation (intoto.jsonl) file
        for the provided artifact.
      * log_only_mode:
        Whether to verify provenance in log only mode, and skip enforcement.
        Enforcement fails closed, and if unable to receive a response from
        Software Verifier, it will constitute a rejection. In log only mode,
        a failed request or a failure to verify will not be considered a
        failure.
    """
    if log_only_mode:
      self.verification_mode = VERIFY_FOR_LOGGING

    args = [
        self.bcid_verifier_path,
        '-bcid-policy',
        bcid_policy,
        '-artifact-path',
        artifact_path,
        '-attestation-path',
        attestation_path,
        'verification-mode',
        self.verification_mode,
    ]

    self.m.step('bcid_verifier: verify provenance', args)
