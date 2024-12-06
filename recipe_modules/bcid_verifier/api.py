# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""API for interacting with BCID Verifier via the OnePlatform API.

To successfully authenticate to this API, you must have the
https://www.googleapis.com/auth/bcid_verify OAuth scope.
"""

from recipe_engine import recipe_api

# This is not used for any type of enforcement, and is a free text string which
# describes the origin of the verification request.
_VERIFICATION_POINT_NAME = "luci-bcid-verifier"
# Verification Types
_VERIFY_FOR_ENFORCEMENT = "VERIFY_FOR_ENFORCEMENT"
_VERIFY_FOR_LOGGING = "VERIFY_FOR_LOGGING"


class BcidVerifierApi(recipe_api.RecipeApi):
  """API for interacting with the BCID for Software One Platform API."""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)

    self.verification_mode = _VERIFY_FOR_ENFORCEMENT

  def _form_request_data(
      self,
      bcid_policy: str,
      artifact_hash: str,
      attestation: str,
  ) -> dict:
    """
    Forms the HTTP request for the OnePlatform API.

    Args:
      bcid_policy: Name of the BCID policy name to verify provenance with
      artifact_hash: The SHA256 of the artifact which is being verified.
      attestation: The content of the artifact attestation.

    Returns:
      A dictionary of data populated with context expected by the Software
      Verifier OnePlatform API endpoint.
    """
    return {
        "resourceToVerify": bcid_policy,
        "context": {
            "verificationPurpose": f"{self.verification_mode}",
            "enforcementPointName": _VERIFICATION_POINT_NAME,
        },
        "artifactInfo": {
            "digests": {
                "sha256": f"{artifact_hash}"
            },
            "attestations": [f"{attestation}"],
        },
    }

  def verify_provenance(
      self,
      bcid_policy: str,
      artifact_path: str,
      attestation_path: str,
      log_only_mode: bool = False,
  ):
    """
    Calls the BCID Software Verifier OnePlatformAPI to verify provenance for an
    artifact.

    Args:
      bcid_policy: Name of the BCID policy name to verify provenance with.
      artifact_path: local file path to the artifact to be verified.
      attestation_path: local file path to the attestation (intoto.jsonl) file
        for the provided artifact.
      log_only_mode:
        Whether to verify provenance in log only mode, and skip enforcement.
        Enforcement fails closed, and if unable to receive a response from
        Software Verifier, it will constitute a rejection.
    """
    if log_only_mode:
      self.verification_mode = _VERIFY_FOR_LOGGING

    # Compute the SHA265 for the artifact we intend to verify.
    artifact_hash = self.m.file.file_hash(artifact_path)

    attestation_name = self.m.path.basename(attestation_path)
    attestation_content = self.m.file.read_text(
        f"Read provenance file: {attestation_name}", attestation_path)

    request_data = self._form_request_data(
        bcid_policy,
        artifact_hash,
        attestation_content,
    )

    # TODO: Get appropriate OAuth token and make HTTP request to OnePlatform
    # API. Ensure that requests include a reasonable timeout and if verification
    # is enforced, this causes a failure.
