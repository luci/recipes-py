# Copyright 2022 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    cipd,
    cv,
    luci_config,
    proto,
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  cipd: cipd.API
  cv: cv.API
  luci_config: luci_config.API
  proto: proto.API
  raw_io: raw_io.API
  step: step.API

from .api import ChangeVerifierApi as API
