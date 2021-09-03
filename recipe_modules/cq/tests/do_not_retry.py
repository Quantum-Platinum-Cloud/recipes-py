# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'buildbucket',
  'cq',
  'step',
]


from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api):
  assert not api.cq.do_not_retry_build
  api.cq.set_do_not_retry_build()
  assert api.cq.do_not_retry_build
  api.cq.set_do_not_retry_build()  # noop.


def GenTests(api):
  yield api.test('example')
