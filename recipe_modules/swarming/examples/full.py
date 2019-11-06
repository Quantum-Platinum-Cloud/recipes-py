# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import difflib
from recipe_engine.recipe_api import Property


DEPS = [
  'cipd',
  # TODO(crbug.com/1022039): This shouldn't be needed since it's only accessed
  # inside swarming/api.py, and swarming/__init__.py lists this dep.
  'isolated',
  'json',
  'path',
  'runtime',
  'step',
  'swarming',
]

EXECUTION_TIMEOUT_SECS = 3600

def RunSteps(api):
  # Create a new Swarming task request.
  request = (api.swarming.task_request().
      with_name('recipes-go').
      with_priority(100).
      with_service_account("account@example.iam.gserviceaccount.com").
      with_user('defaultuser').
      with_tags({'key': ['value1', 'value2']})
  )

  ensure_file = api.cipd.EnsureFile()
  ensure_file.add_package('infra/git/${platform}', 'version:2.14.1.chromium10')

  # Configure the first slice.
  request = (request.with_slice(0, request[0].
        with_command(['recipes', 'run', '"example"']).
        with_dimensions(pool='example.pool', os='Debian').
        with_cipd_ensure_file(ensure_file).
        with_env_vars(SOME_VARNAME='stuff', GOPATH='$HOME/go').
        with_env_prefixes(PATH=["path/to/bin/dir", "path/to/other/bin/dir"]).
        with_isolated('606d94add94223636ee516c6bc9918f937823ccc').
        with_expiration_secs(3600).
        with_io_timeout_secs(600).
        with_execution_timeout_secs(EXECUTION_TIMEOUT_SECS).
        with_idempotent(True).
        with_lower_priority(True).
        with_containment_type('AUTO').
        with_limit_processes(16).
        with_limit_total_committed_memory(1024*1024*1024).
        with_named_caches({'cache_name': 'cache/path'}),
      )
  )

  # Append a slice that is a variation of the last one as a starting point.
  request = request.add_slice(request[-1].
    with_grace_period_secs(20).
    with_secret_bytes('shh, don\'t tell').
    with_outputs(['my/output/file'])
  )

  # There should be three task slices at this point.
  assert len(request) == 2

  # Assert from_josnish(x.to_jonish()) == x
  jsonish = request.to_jsonish()
  from_jsonish = api.swarming.TaskRequest.from_jsonish(api, jsonish)
  back_to_jsonish = from_jsonish.to_jsonish()
  diff = list(difflib.unified_diff(
      api.json.dumps(jsonish, indent=2).splitlines(),
      api.json.dumps(back_to_jsonish, indent=2).splitlines()))
  assert not diff, ''.join(diff)

  # Dimensions, and environment variables and prefixes can be unset.
  slice = request[-1]
  assert not cmp(slice.dimensions, {'pool': 'example.pool', 'os': 'Debian'})
  assert not cmp(
      slice.env_vars, {'SOME_VARNAME': 'stuff', 'GOPATH': '$HOME/go'})
  assert not cmp(
      slice.env_prefixes,
      {'PATH' : ["path/to/bin/dir", "path/to/other/bin/dir"]})

  slice = (slice.
    with_dimensions(os=None).
    with_env_vars(GOPATH=None).
    with_env_prefixes(PATH=None)
  )

  assert cmp(slice.dimensions, {'pool': 'example.pool'}) == 0
  assert cmp(slice.env_vars, {'SOME_VARNAME': 'stuff'}) == 0
  assert cmp(slice.env_prefixes, {}) == 0

  # Setting environment prefixes is additive.
  slice = slice.with_env_prefixes(PATH=['a']).with_env_prefixes(PATH=['b'])
  assert cmp(slice.env_prefixes, {'PATH': ['a', 'b']}) == 0

  # Trigger the task request.
  metadata = api.swarming.trigger('trigger 1 task', requests=[request])

  # From the request metadata, one can access the task's name, id, and
  # associated UI link.
  assert len(metadata) == 1
  metadata[0].name
  metadata[0].id
  metadata[0].task_ui_link

  # Collect the result of the task by metadata.
  output_dir = api.path.mkdtemp('swarming')
  results = api.swarming.collect('collect', metadata, output_dir=output_dir,
                                 timeout='5m')
  # Or collect by by id.
  results += api.swarming.collect('collect other pending task', ['0'])

  results[0].name
  results[0].id
  results[0].state
  results[0].success
  results[0].output
  results[0].outputs
  results[0].output_dir
  results[0].isolated_outputs

  # Raise an error if something went wrong.
  if not results[0].success:
    try:
      results[0].analyze()
    except api.step.StepFailure:
      pass
    except Exception as ex: # pragma: no cover
      raise AssertionError("wrong exception raised: %r" % ex)

  with api.swarming.on_path():
    api.step('some step with swarming on path', [])

  with api.swarming.with_server('https://some-server.com'):
    api.swarming.trigger('trigger on some-server.com', requests=[request])
    api.swarming.collect('collect on some-server.com', ['0'])

  # verify swarming server correctly reverts
  api.swarming.trigger('trigger on original server', requests=[request])
  api.swarming.collect('collect on original server', ['0'])

  api.swarming.trigger('trigger with cancel extra tasks', requests=[request],
                       cancel_extra_tasks=True)
  api.swarming.collect('collect with cancel extra tasks', ['0'])


def GenTests(api):
  yield api.test('basic')
  yield api.test('experimental') + api.runtime(
      is_luci=False, is_experimental=True)
  yield (api.test('override_swarming') +
         api.swarming.properties(server='bananas.example.com',
                                 version='release')
  )

  states = {state.name : api.swarming.TaskState[state.name]
            for state in api.swarming.TaskState if state not in [
              api.swarming.TaskState.INVALID,
              api.swarming.TaskState.PENDING,
              api.swarming.TaskState.RUNNING,
              api.swarming.TaskState.TIMED_OUT,
            ]}
  states['unreachable'] = None

  for name, value in states.iteritems():

    result = api.swarming.task_result(
      id='0', name='recipes-go', state=value, outputs=('out.tar'),
    )
    yield (api.test('collect_with_state_%s' % name) +
      api.override_step_data('collect', api.swarming.collect([result]))
    )

  timeout_result = api.swarming.task_result(
      id='100', name='recipes-go', duration=EXECUTION_TIMEOUT_SECS - 1, state=api.swarming.TaskState.TIMED_OUT,
  )
  yield (api.test('collect_with_state_TIMED_OUT') +
    api.override_step_data('collect', api.swarming.collect([timeout_result]))
  )

  io_timeout_result = api.swarming.task_result(
      id='0', name='recipes-go', duration=EXECUTION_TIMEOUT_SECS - 1, state=api.swarming.TaskState.TIMED_OUT,
  )
  yield (api.test('collect_with_state_TIMED_OUT_by_io') +
    api.override_step_data('collect', api.swarming.collect([io_timeout_result]))
  )

  execution_timeout_result = api.swarming.task_result(
      id='0', name='recipes-go', duration=EXECUTION_TIMEOUT_SECS + 1, state=api.swarming.TaskState.TIMED_OUT,
  )
  yield (api.test('collect_with_state_TIMED_OUT_by_execution') +
    api.override_step_data('collect', api.swarming.collect([execution_timeout_result]))
  )

  failed_result = api.swarming.task_result(
      id='0', name='recipes-go', state=api.swarming.TaskState.COMPLETED,
      failure=True, outputs=('out.tar'),
  )
  yield (api.test('collect_with_state_COMPLETED_and_failed') +
    api.override_step_data('collect', api.swarming.collect([failed_result]))
  )
