# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""API for interacting with the buildbucket service.

Depends on 'buildbucket' binary available in PATH:
https://godoc.org/go.chromium.org/luci/buildbucket/client/cmd/buildbucket
"""

from recipe_engine import recipe_api


class BuildbucketApi(recipe_api.RecipeApi):
  """A module for interacting with buildbucket."""

  def __init__(self, buildername, buildnumber, *args, **kwargs):
    super(BuildbucketApi, self).__init__(*args, **kwargs)
    self._buildername = buildername
    self._buildnumber = buildnumber
    self._properties = None
    self._service_account_key = None
    self._host = 'cr-buildbucket.appspot.com'

  def set_buildbucket_host(self, host):
    """Changes the buildbucket backend hostname used by this module.

    Args:
      host (str): buildbucket server host (e.g. 'cr-buildbucket.appspot.com').
    """
    self._host = host

  def use_service_account_key(self, key_path):
    """Tells this module to start using given service account key for auth.

    Otherwise the module is using the default account (when running on LUCI or
    locally), or no auth at all (when running on Buildbot).

    Exists mostly to support Buildbot environment. Recipe for LUCI environment
    should not use this.

    Args:
      key_path (str): a path to JSON file with service account credentials.
    """
    self._service_account_key = key_path

  @property
  def properties(self):
    """Returns (dict-like or None): The BuildBucket properties, if present."""
    if self._properties is None:
      # Not cached, load and deserialize from properties.
      props = self.m.properties.get('buildbucket')
      if props is not None:
        if isinstance(props, basestring):
          props = self.m.json.loads(props)
        self._properties = props
    return self._properties

  @property
  def build_id(self):
    """Returns int64 identifier of the current build.

    It is unique per buildbucket instance.
    In practice, it means globally unique.

    May return None if it is not a buildbucket build.
    """
    id = (self.properties or {}).get('build', {}).get('id')
    if isinstance(id, basestring):
      # JSON cannot hold int64 as a number
      id = int(id)
    return id

  def put(self, builds, **kwargs):
    """Puts a batch of builds.

    Args:
      builds (list): A list of dicts, where keys are:
        'bucket': (required) name of the bucket for the request.
        'parameters' (dict): (required) arbitrary json-able parameters that a
          build system would be able to interpret.
        'tags': (optional) a dict(str->str) of tags for the build. These will
          be added to those generated by this method and override them if
          appropriate. If you need to remove a tag set by default, set its value
          to None (for example, tags={'buildset': None} will ensure build is
          triggered without 'buildset' tag).

    Returns:
      A step that as its .stdout property contains the response object as
      returned by buildbucket.
    """
    build_specs = []
    for build in builds:
      build_specs.append(self.m.json.dumps({
        'bucket': build['bucket'],
        'parameters_json': self.m.json.dumps(build['parameters']),
        'tags': self._tags_for_build(build['bucket'], build['parameters'],
                                     build.get('tags')),
        'experimental': self.m.runtime.is_experimental,
      }))
    return self._call_service('put', build_specs, **kwargs)

  def cancel_build(self, build_id, **kwargs):
    return self._call_service('cancel', [build_id], **kwargs)

  def get_build(self, build_id, **kwargs):
    return self._call_service('get', [build_id], **kwargs)

  def _call_service(self, command, args, **kwargs):
    step_name = kwargs.pop('name', 'buildbucket.' + command)
    if self._service_account_key:
      args = ['-service-account-json', self._service_account_key] + args
    args = ['buildbucket', command, '-host', self._host] + args
    kwargs.setdefault('infra_step', True)
    return self.m.step(step_name, args, stdout=self.m.json.output(), **kwargs)

  def _tags_for_build(self, bucket, parameters, override_tags=None):
    buildbucket_info = self.properties or {}
    original_tags_list = buildbucket_info.get('build', {}).get('tags', [])

    original_tags = dict(t.split(':', 1) for t in original_tags_list)
    new_tags = {'user_agent': 'recipe'}

    for tag in ['buildset', 'gitiles_ref']:
      if tag in original_tags:
        new_tags[tag] = original_tags[tag]

    builder_name = parameters.get('builder_name')
    if builder_name:
      new_tags['builder'] = builder_name
    if self._buildnumber is not None:
      new_tags['parent_buildnumber'] = str(self._buildnumber)
    if self._buildername is not None:
      new_tags['parent_buildername'] = str(self._buildername)

    # TODO: this is Buildbot-specific.
    if bucket.startswith('master.'):
      new_tags['master'] = bucket[7:]

    new_tags.update(override_tags or {})
    return sorted(
        '%s:%s' % (k, v)
        for k, v in new_tags.iteritems()
        if v is not None)
