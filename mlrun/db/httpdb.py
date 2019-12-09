# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import time

import requests

from ..utils import dict_to_json, logger
from .base import RunDBError, RunDBInterface
from ..lists import RunList, ArtifactList

default_project = 'default'  # TODO: Name?

_artifact_keys = [
    'format',
    'inline',
    'key',
    'src_path',
    'target_path',
    'viewer',
]


def bool2str(val):
    return 'yes' if val else 'no'


class HTTPRunDB(RunDBInterface):
    kind = 'http'
    
    def __init__(self, base_url, user='', password='', token=''):
        self.base_url = base_url
        self.user = user
        self.password = password
        self.token = token

    def __repr__(self):
        cls = self.__class__.__name__
        return f'{cls}({self.base_url!r})'

    def api_call(self, method, path, error=None, params=None,
                 body=None, json=None, timeout=20):
        url = f'{self.base_url}/api/{path}'
        kw = {
            key: value
            for key, value in (('params', params), ('data', body), 
                               ('json', json))
            if value is not None
        }

        if self.user:
            kw['auth'] = (self.user, self.password)
        elif self.token:
            kw['headers'] = {'Authorization': 'Bearer ' + self.token}

        try:
            resp = requests.request(method, url, timeout=timeout, **kw)
            resp.raise_for_status()
            return resp
        except requests.RequestException as err:
            error = error or '{} {}, error: {}'.format(method, url, err)
            raise RunDBError(error) from err

    def _path_of(self, prefix, project, uid):
        project = project or default_project
        return f'{prefix}/{project}/{uid}'

    def connect(self, secrets=None):
        self.api_call('GET', 'healthz', timeout=3)
        return self

    def store_log(self, uid, project='', body=None, append=False):
        if not body:
            return

        path = self._path_of('log', project, uid)
        params = {'append': bool2str(append)}
        error = f'store log {project}/{uid}'
        self.api_call('POST', path, error, params, body)

    def get_log(self, uid, project='', offset=0, size=0):
        params = {'offset': offset, 'size': size}
        path = self._path_of('log', project, uid)
        error = f'get log {project}/{uid}'
        resp = self.api_call('GET', path, error, params=params)
        if resp.headers:
            state = resp.headers.get('function_status', '')

        return state, resp.content

    def watch_log(self, uid, project='', watch=True, offset=0):
        state, text = self.get_log(uid, project, offset=offset)
        if text:
            print(text.decode())
        if watch:
            while state in ['pending', 'running']:
                offset += len(text)
                time.sleep(2)
                state, text = self.get_log(uid, project, offset=offset)
                if text:
                    print(text.decode(), end='')

        return state

    def store_run(self, struct, uid, project='', iter=0):
        path = self._path_of('run', project, uid)
        params = {'iter': iter}
        error = f'store run {project}/{uid}'
        body = _as_json(struct)
        self.api_call('POST', path, error, params=params, body=body)

    def update_run(self, updates: dict, uid, project='', iter=0):
        path = self._path_of('run', project, uid)
        params = {'iter': iter}
        error = f'update run {project}/{uid}'
        body = _as_json(updates)
        self.api_call('PATCH', path, error, params=params, body=body)

    def read_run(self, uid, project='', iter=0):
        path = self._path_of('run', project, uid)
        params = {'iter': iter}
        error = f'get run {project}/{uid}'
        resp = self.api_call('GET', path, error, params=params)
        return resp.json()['data']

    def del_run(self, uid, project='', iter=0):
        path = self._path_of('run', project, uid)
        params = {'iter': iter}
        error = f'del run {project}/{uid}'
        self.api_call('DELETE', path, error, params=params)

    def list_runs(self, name='', uid=None, project='', labels=None,
                  state='', sort=True, last=0, iter=False):

        project = project or default_project
        params = {
            'name': name,
            'uid': uid,
            'project': project,
            'label': labels or [],
            'state': state,
            'sort': bool2str(sort),
            'iter': bool2str(iter),
        }
        error = 'list runs'
        resp = self.api_call('GET', 'runs', error, params=params)
        return RunList(resp.json()['runs'])

    def del_runs(self, name='', project='', labels=None, state='', days_ago=0):
        project = project or default_project
        params = {
            'name': name,
            'project': project,
            'label': labels or [],
            'state': state,
            'days_ago': str(days_ago),
        }
        error = 'del runs'
        self.api_call('DELETE', 'runs', error, params=params)

    def store_artifact(self, key, artifact, uid, tag='', project=''):
        path = self._path_of('artifact', project, uid) + '/' + key
        params = {
            'tag': tag,
        }

        error = f'store artifact {project}/{uid}/{key}'

        body = _as_json(artifact)
        self.api_call(
            'POST', path, error, params=params, body=body)

    def read_artifact(self, key, tag='', project=''):
        project = project or default_project
        tag = tag or 'latest'
        path = self._path_of('artifact', project, tag) + '/' + key
        error = f'read artifact {project}/{key}'
        resp = self.api_call('GET', path, error)
        return resp.content

    def del_artifact(self, key, tag='', project=''):
        path = self._path_of('artifact', project, key)  # TODO: uid?
        params = {
            'key': key,
            'tag': tag,
        }
        error = f'del artifact {project}/{key}'
        self.api_call('DELETE', path, error, params=params)

    def list_artifacts(self, name='', project='', tag='', labels=None):
        project = project or default_project
        params = {
            'name': name,
            'project': project,
            'tag': tag,
            'label': labels or [],
        }
        error = 'list artifacts'
        resp = self.api_call('GET', 'artifacts', error, params=params)
        values = ArtifactList(resp.json()['artifacts'])
        values.tag = tag
        return values

    def del_artifacts(
            self, name='', project='', tag='', labels=None, days_ago=0):
        project = project or default_project
        params = {
            'name': name,
            'project': project,
            'tag': tag,
            'label': labels or [],
            'days_ago': str(days_ago),
        }
        error = 'del artifacts'
        self.api_call('DELETE', 'artifacts', error, params=params)

    def store_function(self, func, name, project='', tag=''):
        params = {'tag': tag}
        project = project or default_project
        path = self._path_of('func', project, name)

        error = f'store function {project}/{name}'
        self.api_call(
            'POST', path, error, params=params, body=json.dumps(func))

    def get_function(self, name, project='', tag=''):
        params = {'tag': tag}
        project = project or default_project
        path = self._path_of('func', project, name)
        error = f'get function {project}/{name}'
        resp = self.api_call('GET', path, error, params=params)
        return resp.json()['func']

    def list_functions(self, name, project='', tag='', labels=None):
        params = {
            'project': project or default_project,
            'name': name,
            'tag': tag,
            'label': labels or [],
        }
        error = f'list functions'
        resp = self.api_call('GET', 'funcs', error, params=params)
        return resp.json()['funcs']

    def remote_builder(self, runtime, with_mlrun):
        try:
            req = {'function': runtime.to_dict(),
                   'with_mlrun': with_mlrun}
            resp = self.api_call('POST', 'build/function', json=req)
        except OSError as err:
            logger.error('error submitting build task: {}'.format(err))
            raise OSError(
                'error: cannot submit build, {}'.format(err))

        if not resp.ok:
            logger.error('bad resp!!\n{}'.format(resp.text))
            raise ValueError('bad function run response')

        return resp.json()

    def get_builder_status(self, name, project='', tag='', offset=-1):
        try:
            params = {'name': name,
                      'project': project,
                      'tag': tag,
                      'offset': str(offset)}
            resp = self.api_call('GET', 'build/status', params=params)
        except OSError as err:
            logger.error('error getting build status: {}'.format(err))
            raise OSError(
                'error: cannot get build status, {}'.format(err))

        if not resp.ok:
            logger.error('bad resp!!\n{}'.format(resp.text))
            raise ValueError('bad function run response')

        state = pod = ''
        if resp.headers:
            state = resp.headers.get('function_status', '')
            pod = resp.headers.get('builder_pod', '')

        return state, resp.content


def _as_json(obj):
    fn = getattr(obj, 'to_json', None)
    if fn:
        return fn()
    return dict_to_json(obj)
