import io
import json
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mcp_client.signing import ReplayNonceStore, sign_request
from sandbox_runner import service


class _FakeVolume:
    def __init__(self, name='runner-volume'):
        self.name = name
        self.removed = False

    def remove(self, force=False):
        self.removed = True


class _FakeVolumes:
    def __init__(self):
        self.created = None

    def create(self, **_kwargs):
        self.created = _FakeVolume()
        return self.created

    def list(self, **_kwargs):
        return []


class _ExecResult:
    exit_code = 0
    output = (b'runner stdout', b'')


class _FakeContainer:
    def __init__(self, output_archive):
        self.output_archive = output_archive
        self.put_paths = []
        self.get_paths = []
        self.started = False
        self.removed = False

    def start(self):
        self.started = True

    def put_archive(self, path, _raw):
        self.put_paths.append(path)
        return True

    def exec_run(self, command, **_kwargs):
        if command[:2] == ['rm', '-f']:
            return _ExecResult()
        return _ExecResult()

    def get_archive(self, path):
        self.get_paths.append(path)
        return iter((self.output_archive,)), {}

    def kill(self):
        return None

    def remove(self, force=False):
        self.removed = True


class _FakeContainers:
    def __init__(self, output_archive):
        self.output_archive = output_archive
        self.created_kwargs = None
        self.created = None

    def create(self, **kwargs):
        self.created_kwargs = kwargs
        self.created = _FakeContainer(self.output_archive)
        return self.created

    def list(self, **_kwargs):
        return []


class _FakeDockerClient:
    def __init__(self, output_archive):
        self.volumes = _FakeVolumes()
        self.containers = _FakeContainers(output_archive)
        self.closed = False

    def close(self):
        self.closed = True


def _tar_bytes(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, content in files.items():
            if content is None:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o700
                archive.addfile(info)
                continue
            raw = content.encode('utf-8')
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


class SandboxRunnerServiceTests(unittest.TestCase):
    def setUp(self):
        service._NONCE_STORE = ReplayNonceStore(ttl_seconds=120, max_entries=128)

    def test_signed_request_is_accepted_once_and_replay_is_rejected(self):
        secret = 'test-sandbox-secret-' + ('x' * 32)
        body = json.dumps({'image': 'sandbox:test'}, separators=(',', ':')).encode('utf-8')
        timestamp = str(int(time.time()))
        nonce = 'nonce-for-one-request'
        headers = {
            'Content-Type': 'application/json',
            'X-App3-Sandbox-Timestamp': timestamp,
            'X-App3-Sandbox-Nonce': nonce,
            'X-App3-Sandbox-Signature': sign_request(secret, 'POST', '/v1/run', timestamp, nonce, body),
        }
        with mock.patch.dict(service.os.environ, {'SANDBOX_RUNNER_SECRET': secret}), mock.patch.object(
            service, '_execute', return_value={'ok': True, 'exit_code': 0}
        ):
            client = service.app.test_client()
            first = client.post('/v1/run', data=body, headers=headers)
            replay = client.post('/v1/run', data=body, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(replay.get_json()['error'], 'signature_nonce_replayed')

    def test_relative_path_validation_rejects_traversal_and_absolute_paths(self):
        for value in ('../escape', 'safe/../../escape', '/etc/passwd', r'C:\\Windows\\System32'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                service._safe_relative(value, strict_names=False)
        self.assertEqual(service._safe_relative('owner/session', strict_names=False), 'owner/session')

    def test_archive_extract_keeps_hidden_files_and_excludes_runner_internals(self):
        raw = _tar_bytes({
            '.': None,
            './result.txt': 'result',
            './.hidden': 'hidden',
            './.app3_runtime/secret.txt': 'runtime',
            './.app3_runner_stdin': 'stdin',
        })
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp).resolve()
            total = service._extract_archive_to_stage(raw, stage, 1024 * 1024)
            self.assertEqual((stage / 'result.txt').read_text(encoding='utf-8'), 'result')
            self.assertEqual((stage / '.hidden').read_text(encoding='utf-8'), 'hidden')
            self.assertFalse((stage / '.app3_runtime').exists())
            self.assertFalse((stage / '.app3_runner_stdin').exists())
            self.assertEqual(total, len('result') + len('hidden'))

    def test_execute_uses_only_ephemeral_volume_and_forces_network_off(self):
        output_archive = _tar_bytes({'./result.txt': 'done', './.hidden': 'kept'})
        fake_client = _FakeDockerClient(output_archive)
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp).resolve()
            sandbox_root = data_root / 'sandboxes'
            with mock.patch.object(service, 'SANDBOX_ROOT', sandbox_root), mock.patch.object(
                service, 'ALLOWED_IMAGE', 'sandbox:test'
            ), mock.patch.object(service, 'SKILLS_ROOT', data_root / 'missing-skills'), mock.patch.object(
                service, 'EXTENSION_ROOT', data_root / 'missing-extensions'
            ), mock.patch.object(service, '_docker_client', return_value=fake_client), mock.patch.object(
                service, '_prune_stale', return_value=None
            ):
                result = service._execute({
                    'image': 'sandbox:test',
                    'sandbox_rel': 'owner/session',
                    'argv': ['bash', '-lc', 'printf ok'],
                    'timeout_s': 3,
                })
            created = fake_client.containers.created_kwargs
            self.assertTrue(result['ok'])
            self.assertTrue(created['network_disabled'])
            self.assertTrue(created['read_only'])
            self.assertEqual(created['cap_drop'], ['ALL'])
            self.assertEqual(created['volumes'], {'runner-volume': {'bind': '/mnt/data', 'mode': 'rw'}})
            self.assertNotIn(str(data_root), json.dumps(created['volumes']))
            self.assertEqual(fake_client.containers.created.get_paths, ['/mnt/data/.'])
            target = sandbox_root / 'owner' / 'session'
            self.assertEqual((target / 'result.txt').read_text(encoding='utf-8'), 'done')
            self.assertEqual((target / '.hidden').read_text(encoding='utf-8'), 'kept')
            self.assertTrue(fake_client.volumes.created.removed)
            self.assertTrue(fake_client.containers.created.removed)
            self.assertTrue(fake_client.closed)


if __name__ == '__main__':
    unittest.main()
