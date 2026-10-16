import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'companion'))
import server
from engine import Clip
from creative_edit import FEATURES


class PipelineTests(unittest.TestCase):
    def test_prepare_overlaps_render_but_both_stages_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as mocks:
            root = Path(folder)
            source, song = root / 'source.mp4', root / 'song.wav'
            source.touch()
            song.touch()
            release = threading.Event()
            render_started = threading.Event()
            second_prepared = threading.Event()
            threads, paths, states, preparations = [], [], [], []
            active = {'prepare': 0, 'render': 0}
            maximum = dict(active)
            def prepare(audio, temp, cancelled):
                active['prepare'] += 1
                maximum['prepare'] = max(maximum['prepare'], active['prepare'])
                preparations.append(len(preparations))
                if len(preparations) == 2:
                    self.assertTrue(render_started.is_set())
                    second_prepared.set()
                time.sleep(.015)
                active['prepare'] -= 1
                return str(song)
            def mix(_song, _clips, _options, temp, *_args):
                path = Path(temp) / 'mix.wav'
                path.touch()
                paths.append(path)
                return str(path)
            def render(clips, mix, output, *args, **kwargs):
                active['render'] += 1
                maximum['render'] = max(maximum['render'], active['render'])
                render_started.set()
                self.assertTrue(release.wait(5))
                self.assertTrue(Path(mix).is_file())
                Path(output).write_bytes(b'rendered')
                active['render'] -= 1
            for name, effect in [('prepare_audio', prepare), ('mix_audio', mix), ('run_resolve_worker', render)]:
                mocks.enter_context(patch.object(server, name, side_effect=effect))
            mocks.enter_context(patch.object(server, 'health', return_value={'ok': True}))
            mocks.enter_context(patch.object(server, 'audio_duration', return_value=2))
            mocks.enter_context(patch.object(server, 'beat_grid', return_value=[0, 2]))
            mocks.enter_context(patch('advanced_edit.edit_plan', return_value=[Clip(1, str(source), 0, 2, 0, 0, None, False)]))
            payload = {'sources': [{'id': 1, 'path': str(source), 'width': 200, 'height': 120, 'fps': 30}],
                       'audio': {'path': str(song)}, 'outputFolder': str(root), 'skipSetupChecks': True,
                       'options': {name: False for name in FEATURES}}
            def start(index):
                state = {'state': 'queued', 'cancelEvent': threading.Event(), 'eventLock': threading.Lock(), 'eventSequence': 0, 'events': []}
                server.JOBS[f'pipeline-{index}'] = state
                states.append(state)
                thread = threading.Thread(target=server.do_job, args=(f'pipeline-{index}', dict(payload)))
                threads.append(thread)
                thread.start()
            try:
                start(0)
                self.assertTrue(render_started.wait(5))
                start(1)
                self.assertTrue(second_prepared.wait(5), 'Preparation must run while the first render is blocked')
                start(2)
                time.sleep(.15)
                self.assertEqual(2, len(preparations), 'A third prepared edit must not fill disk while Resolve is busy')
                self.assertTrue(paths[0].is_file(), 'Media must survive until its render completes')
                states[2]['cancelEvent'].set()
                threads[2].join(2)
                self.assertFalse(threads[2].is_alive(), 'Queued cancellation must not wait for Resolve')
                self.assertEqual('cancelled', states[2]['state'])
                release.set()
                for thread in threads:
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                self.assertEqual(['complete', 'complete'], [s['state'] for s in states[:2]])
                self.assertEqual({'prepare': 1, 'render': 1}, maximum)
                self.assertTrue(all(not p.exists() for p in paths))
            finally:
                release.set()
                for state in states:
                    state['cancelEvent'].set()
                for thread in threads:
                    thread.join(5)
                for index in range(len(states)):
                    server.JOBS.pop(f'pipeline-{index}', None)

    def test_cancelled_stage_releases_its_permit(self):
        gate = threading.BoundedSemaphore(1)
        cancelled = threading.Event()
        with server.pipeline_slot(gate, cancelled):
            cancelled.set()
        self.assertTrue(gate.acquire(False))
        gate.release()
        with self.assertRaises(InterruptedError):
            with server.pipeline_slot(gate, cancelled):
                self.fail('Cancelled job acquired a stage')
        self.assertTrue(gate.acquire(False))
        gate.release()

    def test_preflight_and_health_do_not_touch_busy_resolve(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'connect', side_effect=AssertionError('Touched Resolve')):
            source = Path(folder) / 'video.mp4'
            source.touch()
            payload = {'sources': [{'path': str(source)}], 'audio': {'path': str(source)},
                       'outputFolder': folder, 'options': {'outputCodec': 'av1'}}
            self.assertEqual(payload['sources'], server.preflight(payload))
            with server.RENDER_LOCK:
                self.assertTrue(server.health_snapshot(allow_launch=True)['busy'])

    def test_shared_uploads_and_references_survive_early_cleanup(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'UPLOAD_ROOT', Path(folder)), patch.object(server, 'REFERENCE_ROOT', Path(folder)):
            uid, rid = 'b' * 32, 'c' * 32
            song, face = Path(folder) / (uid + '.wav'), Path(folder) / rid
            song.touch()
            face.touch()
            payload = {'audio': {'kind': 'upload', 'uploadId': uid}, 'references': [{'referenceId': rid}]}
            with server.LOCK:
                server.retain_job_resources('lease-1', payload)
                server.retain_job_resources('lease-2', payload)
            server.delete_uploaded_song(uid)
            server.delete_resource('reference', rid)
            server.release_job_resources('lease-1')
            self.assertTrue(song.is_file() and face.is_file())
            server.release_job_resources('lease-2')
            self.assertFalse(song.exists() or face.exists())


if __name__ == '__main__':
    unittest.main()
