# Copyright 2019 The LUCI Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Expects to this repo to be checked out as part of gclient checkout of
# https://chromium.googlesource.com/infra/infra.

LUCI_GO=../../../../../../../../go/src/go.chromium.org/luci
SRC=cv/api/recipe/v1
RES_REV=$(shell git -C $(LUCI_GO) describe --match=NeVeRmAtCh --always --abbrev=40 --dirty)

all:
	git -C $(LUCI_GO) show origin/master:$(SRC)/cq.proto >cq.proto
	echo 'These protos were copied from' > README.md
	echo "https://chromium.googlesource.com/infra/luci/luci-go/+/$(RES_REV)/cv/api/recipe/v1" >> README.md

wip:
	cp $(LUCI_GO)/$(SRC)/cq.proto cq.proto
	echo 'DO NOT COMMIT, copied from dirty checkout'> README.md
