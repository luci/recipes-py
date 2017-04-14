# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy


# TODO(iannucci): This value is split with the autoroller recipe which lives in
# the infra.git repo. It's pretty dumb to have this duplication.
#
# Additionally, this detection is a bit cheezy. Some alternatives:
#   * identify the recipe autoroller account(s). This is nice because the
#     accounts are verified (unlike the commit message), but it's awkward
#     because there's no consistent set of accounts that we can encode here, so
#     we'd have to plumb it through as an option. Worth consideration.
#   * Add an `Autoroller: recipes` footer or something to the commit message and
#     have gerrit verify this. This would be more difficult (beause we'd have to
#     program gerrit to have an ACL for this footer, a function it doesn't
#     currently have), but it would be more general.
_AUTOROLLER_PREFIX = 'Roll recipe dependencies'


class RollCandidate(object):
  """RollCandidate holds a single, consistent package_pb2.Package representing
  a potential autoroll candidate.
  """

  def __init__(self, package_pb):
    """
    Args:
      package_pb (package_pb2.Package) - Read-only Package message, will be
        copied internally.
    """
    self.package_pb = copy.deepcopy(package_pb)

  def changelist(self, repos):
    """Returns changelist for this RollCandidate.

    This will return all CommitMetadata in every repo that was rolled by this
    RollCandidate.

    This excludes commits which were created by the autoroller.

    Args:
      repos dict(project_id, CommitList) - The repo CommitList mapping obtained
        by calling candidate_algorithm.get_roll_candidates().

    Returns dict(project_id, [CommitMetadata])
    """
    ret = {}
    for pid, dep in self.package_pb.deps.iteritems():
      rolled = [
        # The [1:] is to skip the very first commit, which is the commit value
        # that the autoroller started with.
        meta for meta in repos[pid].changelist(dep.revision)[1:]
        if not (
            meta.message_lines and
            meta.message_lines[0].startswith(_AUTOROLLER_PREFIX)
        )
      ]
      if rolled:
        ret[pid] = rolled
    return ret
