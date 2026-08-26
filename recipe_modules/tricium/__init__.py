# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    cipd,
    context,
    file,
    findings,
    json,
    path,
    properties,
    proto,
    resultdb,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  cipd: cipd.API
  context: context.API
  file: file.API
  findings: findings.API
  json: json.API
  path: path.API
  properties: properties.API
  proto: proto.API
  resultdb: resultdb.API
  step: step.API

from .api import TriciumApi as API
