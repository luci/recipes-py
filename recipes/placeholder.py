# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.turboci.graph.orchestrator.v1.write_nodes_request import WriteNodesRequest

DEPS = [
  'buildbucket',
  'properties',
  'step',
  'swarming',
  'time',
]

from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct

from PB.recipe_engine import result as result_pb2
from PB.recipes.recipe_engine.placeholder import (
  InputProps, Step, FakeStep, CollectChildren,
  ChildBuild, Buildbucket, LifeTime, TurboCIWrite)
from PB.go.chromium.org.luci.buildbucket.proto.builder_common import BuilderID
from PB.go.chromium.org.luci.buildbucket.proto.common import Status

from PB.turboci.data.gerrit.v1.gob_source_check_options import GobSourceCheckOptions
from PB.turboci.data.gerrit.v1.gob_source_check_results import GobSourceCheckResults
from PB.turboci.data.gerrit.v1.gerrit_change_info import GerritChangeInfo

from recipe_engine import post_process

from recipe_engine import turboci

PROPERTIES = InputProps


def RunSteps(api, properties):
  def handlePres(pres, step_pb):
    pres.step_text = step_pb.step_text
    for name, link in step_pb.links.items():
      pres.links[name] = link
    for name, log in step_pb.logs.items():
      pres.logs[name] = log.splitlines()

    pres.status = {
      Status.FAILURE: 'FAILURE',
      Status.INFRA_FAILURE: 'EXCEPTION',
      Status.CANCELED: 'CANCELED',
    }.get(step_pb.status, 'SUCCESS')
    pres.had_timeout = step_pb.timeout
    pres.was_canceled = step_pb.canceled

    pres.properties = json_format.MessageToDict(step_pb.set_properties)

  def processStep(step: Step):
    match step.WhichOneof('type'):
      case 'fake_step':
        processFakeStep(step.name, step.fake_step)
      case 'child_build':
        child_build = step.child_build
        build = scheduleChildBuild(step.name, step.child_build)
        if child_build.id:
          child_map[child_build.id] = build.id
      case 'collect_children':
        collectChild(step.name, step.collect_children)
      case 'turboci_write':
        TurboCIWrite(step.name, step.turboci_write)
      case _:  # pragma: no cover
        assert False, 'unreachable'

  def processFakeStep(step_name: str, fake_step: FakeStep):
    if fake_step.children:
      with api.step.nest(step_name) as pres:
        handlePres(pres, fake_step)

        if fake_step.duration_secs > 0:
          api.time.sleep(
              fake_step.duration_secs, with_step=False, step_result=pres)

        for child in fake_step.children:
          processStep(child)
    else:
      result = api.step(step_name, cmd=None)
      handlePres(result.presentation, fake_step)
      if fake_step.duration_secs > 0:
        api.time.sleep(
            fake_step.duration_secs, with_step=False, step_result=result)

  def scheduleChildBuild(step_name: str, child_build: ChildBuild):
    assert child_build.buildbucket
    builder = child_build.buildbucket.builder

    can_outlive_parent = True
    swarming_parent_run_id = None
    child_tracking_service = "bb"
    bounded_child = "False"
    if child_build.life_time == LifeTime.BUILD_BOUND:
      bounded_child = "True"
      if ('luci.buildbucket.parent_tracking'
          in api.buildbucket.build.input.experiments):
        can_outlive_parent = False
      else:
        swarming_parent_run_id = api.swarming.task_id
        child_tracking_service = "swarming"

    req = api.buildbucket.schedule_request(
        builder=builder.builder,
        project=builder.project,
        bucket=builder.bucket,
        can_outlive_parent=can_outlive_parent,
        swarming_parent_run_id=swarming_parent_run_id,
        as_shadow_if_parent_is_led=True,
        led_inherit_parent=True,
        tags=api.buildbucket.tags(
            bounded_child=bounded_child,
            child_tracking_service=child_tracking_service),
    )
    return api.buildbucket.schedule([req], step_name=step_name)[0]

  def collectChild(step_name, collect_children):
    build_ids_to_collect = []
    for child_id in collect_children.child_build_step_ids:
      if child_map.get(child_id):
        build_ids_to_collect.append(child_map[child_id])
      else:
        raise api.step.InfraFailure('no build to collect for %s' % child_id)
    api.buildbucket.collect_builds(build_ids_to_collect, step_name=step_name)

  def TurboCIWrite(step_name: str, req: TurboCIWrite):
    reasons = req.reasons
    if not reasons:
      reasons = [turboci.reason(f'written by step {step_name!r}')]
    with api.step.nest(step_name) as pres:
      try:
        rawReq = WriteNodesRequest(reasons=reasons, checks=req.check_writes)
        pres.logs['request'] = str(rawReq)

        rawRsp = turboci.get_client().WriteNodes(rawReq)
        pres.logs['response'] = str(rawRsp)
      except turboci.TurboCIException as ex:
        pres.status = api.step.EXCEPTION
        pres.step_text = f'turboci.write_nodes failed'
        pres.logs['exception'] = f'{type(ex).__name__}: {ex}'

  if not (properties.status and properties.status & Status.ENDED_MASK):
    return result_pb2.RawResult(
      status=Status.FAILURE,
      summary_markdown=('must provide a final status in input properties; '
                        'got %s' % properties.status)
    )
  child_map = {}
  if properties.steps:
    for step in properties.steps:
      if step.WhichOneof('type') == 'child_build':
        id = step.child_build.id
        if step.child_build.id:
          if child_map.get(id, None) == 0:
            return result_pb2.RawResult(
                status=Status.FAILURE,
                summary_markdown=('multiple child_build steps have the same id:'
                                  ' %s' % id)
            )
          child_map[id] = 0

    for step in properties.steps:
      processStep(step)
  else:
    processStep(Step(name='hello world', fake_step=FakeStep(duration_secs=10)))

  return result_pb2.RawResult(status=properties.status)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(InputProps(status=Status.SUCCESS))
  )

  yield api.test(
      'presentation',
      api.properties(InputProps(
          steps = [
            Step(
                name='cool',
                fake_step=FakeStep(
                    step_text='text',
                    logs={'log': 'multiline\ndata'},
                    links={'link': 'https://example.com'},
                    status=Status.FAILURE,
                    set_properties=json_format.ParseDict({
                      "generic": "stuff",
                      "key": 100,
                    }, Struct()),
                    canceled=True,
                    timeout=True,
                    tags={'tag_key': 'tag_value'}
                ),
            ),
            Step(
                name='parent',
                fake_step=FakeStep(
                    duration_secs=10,
                    children=[
                        Step(name='a', fake_step=FakeStep()),
                        Step(name='b', fake_step=FakeStep()),
                    ],
                    tags={'tag_key': 'tag_value'}
                ),
            )
          ],
          status=Status.INFRA_FAILURE,
      )),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'missing final status',
      api.properties(InputProps()),
      api.post_process(
          post_process.SummaryMarkdownRE,
          "must provide a final status in input properties; got"),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  child_build_prop = InputProps(
      steps = [
          Step(
              name='child bounded',
              child_build=ChildBuild(
                  life_time=LifeTime.BUILD_BOUND,
                  buildbucket=Buildbucket(
                      builder=BuilderID(
                          project="project",
                          bucket="bucket",
                          builder="builder",
                      ),
                  ),
              ),
          ),
          Step(
              name='child detached',
              child_build=ChildBuild(
                  life_time=LifeTime.DETACHED,
                  buildbucket=Buildbucket(
                      builder=BuilderID(
                          project="project",
                          bucket="bucket",
                          builder="builder",
                      ),
                  ),
              ),
          ),
          Step(
              name='wait',
              fake_step=FakeStep(
                  duration_secs=10,
                  tags={'child_tag_key': 'child_tag_value'}
              ),
          )
      ],
      status=Status.SUCCESS,
  )

  yield api.test(
      'child_build_swarming',
      api.properties(child_build_prop)
  ) + api.properties(swarming_parent_run_id='1234')

  yield api.test(
      'child_build_buildbucket',
      api.properties(child_build_prop)
  ) + api.buildbucket.try_build(
      project='proj',
      builder='try-builder',
      git_repo='https://chrome-internal.googlesource.com/a/repo.git',
      revision='a' * 40,
      build_number=123,
      experiments=['luci.buildbucket.parent_tracking']
  ) + api.properties(swarming_parent_run_id='1234')

  yield api.test(
      'collect_children',
      api.properties(InputProps(
          steps = [
              Step(
                  name='child bounded',
                  child_build=ChildBuild(
                      id='child bounded id',
                      life_time=LifeTime.BUILD_BOUND,
                      buildbucket=Buildbucket(
                          builder=BuilderID(
                              project="project",
                              bucket="bucket",
                              builder="builder",
                          ),
                      ),
                  ),
              ),
              Step(
                  name='collect children',
                  collect_children=CollectChildren(
                      child_build_step_ids=['child bounded id'],
                  ),
              ),
          ],
          status=Status.SUCCESS,
      ))
  ) + api.buildbucket.try_build(
      project='proj',
      builder='try-builder',
      git_repo='https://chrome-internal.googlesource.com/a/repo.git',
      revision='a' * 40,
      build_number=123,
      experiments=['luci.buildbucket.parent_tracking']
  )

  yield api.test(
      'collect_children_duplicated_id',
      api.properties(InputProps(
          steps = [
              Step(
                  name='child bounded',
                  child_build=ChildBuild(
                      id='id',
                      life_time=LifeTime.BUILD_BOUND,
                      buildbucket=Buildbucket(
                          builder=BuilderID(
                              project="project",
                              bucket="bucket",
                              builder="builder",
                          ),
                      ),
                  ),
              ),
              Step(
                  name='child bounded another',
                  child_build=ChildBuild(
                      id='id',
                      life_time=LifeTime.BUILD_BOUND,
                      buildbucket=Buildbucket(
                          builder=BuilderID(
                              project="project",
                              bucket="bucket",
                              builder="builder",
                          ),
                      ),
                  ),
              ),
              Step(
                  name='collect children',
                  collect_children=CollectChildren(
                      child_build_step_ids=['id'],
                  ),
              ),
          ],
          status=Status.SUCCESS,
      )),
      status='FAILURE',
  )

  yield api.test(
      'collect_children_wrong_id',
      api.properties(InputProps(
          steps = [
              Step(
                  name='child bounded',
                  child_build=ChildBuild(
                      id='child bounded id',
                      life_time=LifeTime.BUILD_BOUND,
                      buildbucket=Buildbucket(
                          builder=BuilderID(
                              project="project",
                              bucket="bucket",
                              builder="builder",
                          ),
                      ),
                  ),
              ),
              Step(
                  name='collect children',
                  collect_children=CollectChildren(
                      child_build_step_ids=['id'],
                  ),
              ),
          ],
          status=Status.SUCCESS,
      )),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://chrome-internal.googlesource.com/a/repo.git',
          revision='a' * 40,
          build_number=123,
          experiments=['luci.buildbucket.parent_tracking']
      ),
      status='INFRA_FAILURE',
  )

  write_checks_input = InputProps(status=Status.SUCCESS)
  step = write_checks_input.steps.add(name='write bob')
  step.turboci_write.check_writes.append(turboci.check(
      'bob', kind='BUILD',
  ))
  step = write_checks_input.steps.add(name='add option to bob')
  step.turboci_write.check_writes.append(turboci.check(
      'bob', options=[GobSourceCheckOptions()], state='PLANNED',
  ))
  step = write_checks_input.steps.add(name='add result to bob')
  step.turboci_write.check_writes.append(turboci.check(
      'bob', results=[GobSourceCheckResults()], state='FINAL',
  ))
  step = write_checks_input.steps.add(name='fail to add late result to bob')
  step.turboci_write.check_writes.append(turboci.check(
      'bob', results=[GerritChangeInfo()], state='FINAL',
  ))
  assert len(write_checks_input.steps) == 4

  yield api.test(
      'write_checks',
      api.properties(write_checks_input),
  )
