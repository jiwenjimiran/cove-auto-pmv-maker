import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'companion'))
from creative_edit import FEATURES, direct, image_effect, time_knots
from creative_pixels import (anamorphic, glow, interpolate, light_rays, optical_flow_pair,
                             outline_echo, person_mask, sky_mask, swirly_bokeh, video_call, replace_sky)
from engine import Clip, probe, run
from music_analysis import BeatGrid
from transition_edit import (TRANSITIONS, FrameReader, compose_scene, morph_compatible,
                             plan_transitions, prepare_transitions, transition_frame)


def fixture():
    y, x = np.indices((120, 200))
    frame = np.zeros((120, 200, 3), np.uint8)
    frame[:] = (30, 25, 25)
    frame[(x // 10 + y // 10) % 2 == 0] = (85, 65, 55)
    cv2.rectangle(frame, (75, 25), (125, 110), (100, 170, 230), -1)
    cv2.circle(frame, (35, 25), 10, (255, 255, 255), -1)
    return frame


class ExpressiveEffectTests(unittest.TestCase):
    def test_glow_is_visible_between_beats(self):
        frame = fixture()
        plan = dict(dominant=None, hits=[], strength=1, drift=False, scale=0,
                    direction=1, color=False, bloom=True, cue={'luma': 112})
        out = image_effect(frame, .75, 2, plan)
        delta = np.abs(out.astype(float) - frame).mean()
        self.assertGreater(delta, .5)
        self.assertLess(delta, 3)

    def test_each_look_has_a_visible_independent_change(self):
        frame = fixture()
        for effect in (glow, anamorphic, light_rays, outline_echo, video_call):
            with self.subTest(effect=effect.__name__):
                output = effect(frame, 1)
                self.assertEqual(frame.shape, output.shape)
                self.assertEqual(output.dtype, np.uint8)
                self.assertGreater(np.abs(output.astype(float) - frame).mean(), 1)

    def test_bokeh_protects_foreground_and_changes_background(self):
        frame = fixture()
        mask = np.zeros(frame.shape[:2], np.float32)
        mask[20:115, 70:130] = 1
        output = swirly_bokeh(frame, mask, 1)
        np.testing.assert_array_equal(output[mask == 1], frame[mask == 1])
        self.assertGreater(np.abs(output[mask == 0].astype(float) - frame[mask == 0]).mean(), 3)
        np.testing.assert_array_equal(swirly_bokeh(frame, np.zeros_like(mask)), frame)

    def test_bundled_person_model_runs_without_face_records(self):
        mask = person_mask(np.zeros((120, 200, 3), np.uint8))
        self.assertEqual(mask.shape, (120, 200))
        self.assertTrue(np.isfinite(mask).all())
        self.assertGreaterEqual(mask.min(), 0)
        self.assertLessEqual(mask.max(), 1)

    def test_sky_key_requires_top_connected_sky(self):
        frame = np.full((120, 200, 3), (50, 50, 50), np.uint8)
        frame[40:90, 40:160] = (230, 150, 80)
        self.assertFalse(sky_mask(frame).any())
        frame[:65] = (230, 150, 80)
        mask = sky_mask(frame)
        self.assertGreater(mask.mean(), .4)
        output = replace_sky(frame, mask)
        np.testing.assert_array_equal(output[95:], frame[95:])
        self.assertGreater(np.abs(output[:40].astype(float) - frame[:40]).mean(), 10)

    def test_speed_curves_have_slow_pockets_and_exact_bounds(self):
        for effect in ('speedRamps', 'superSlowMotion'):
            knots = np.array(time_knots(3, [(1.5, 1)], {'motion': 2}, {}, effect))
            rates = np.diff(knots[:, 1]) / np.diff(knots[:, 0])
            np.testing.assert_equal(knots[[0, -1]], [[0, 0], [3, 3]])
            self.assertTrue((rates > 0).all())
            self.assertLess(rates.min(), .35 if effect == 'speedRamps' else .15)
            self.assertGreater(rates.max(), 1.3)

    def test_optical_flow_keeps_a_translated_object_sharp(self):
        first = np.zeros((120, 200, 3), np.uint8)
        cv2.circle(first, (70, 60), 15, (240, 240, 240), -1)
        second = np.roll(first, 8, axis=1)
        result = interpolate(first, second, .5)
        gray = result.mean(axis=2)
        ys, xs = np.where(gray > 200)
        self.assertAlmostEqual(float(xs.mean()), 74, delta=1)
        self.assertGreater(len(xs), 600)
        np.testing.assert_array_equal(interpolate(first, second, 0), first)
        np.testing.assert_array_equal(interpolate(first, second, 1), second)

    def test_automatic_director_uses_multiple_families(self):
        clips = [Clip(n, f'{n}.mp4', 0, 2, n * 2, 0, None, True) for n in range(14)]
        beats = BeatGrid([n / 2 for n in range(57)], tempo=120, energy=[(0, .8)])
        cue = {'motion': 1, 'direction': 1, 'peak': 1, 'luma': 112, 'sharpness': 80}
        with patch('creative_edit.analyze_shot', return_value=cue):
            _, plans = direct(clips, beats, {})
            used = {p['dominant'] for p in plans}
            self.assertTrue({'beatPunch', 'impactRecoil', 'speedRamps', 'superSlowMotion', 'rgbSplit'} <= used)
            self.assertFalse(any(p['look'] in ('videoCall', 'skyReplacement') for p in plans))
            _, plans = direct(clips, beats, {name: False for name in FEATURES})
            self.assertTrue(all(not p['dominant'] and not p['look'] and not p['bloom'] for p in plans))

    def test_transition_endpoints_and_slide_contain_both_shots(self):
        a = np.full((120, 200, 3), (20, 30, 210), np.uint8)
        b = np.full((120, 200, 3), (210, 30, 20), np.uint8)
        for family in TRANSITIONS:
            plan = dict(family=family, strength=1, direction=1)
            np.testing.assert_array_equal(transition_frame(a, b, 0, plan), a)
            np.testing.assert_array_equal(transition_frame(a, b, 1, plan), b)
        middle = transition_frame(a, b, .5, dict(family='slideTransitions', strength=1, direction=1))
        self.assertGreater(middle[:30, :, 2].mean(), 190)
        self.assertGreater(middle[-30:, :, 0].mean(), 190)
        self.assertFalse(morph_compatible(a, b))
        self.assertTrue(morph_compatible(a, a))

    def test_morph_requires_matching_structure_not_only_colors(self):
        a = np.full((120, 200, 3), 55, np.uint8)
        cv2.circle(a, (55, 60), 24, (90, 90, 90), -1)
        b = np.roll(a, 90, axis=1)
        self.assertLess(np.abs(a.astype(float) - b).mean(), 10)
        self.assertFalse(morph_compatible(a, b))
        self.assertTrue(morph_compatible(a, np.roll(a, 3, axis=1)))
        self.assertTrue(morph_compatible(a, np.clip(a + 10, 0, 255)))

    def test_windows_do_not_overlap_or_change_edit_length(self):
        clips = [Clip(n, f'{n}.mp4', 0, 1, n, 0, None, True) for n in range(8)]
        plans = plan_transitions(clips, [], {}, 30)
        self.assertEqual({p['family'] for p in plans}, set(TRANSITIONS))
        for p in plans:
            self.assertLess(p['startFrame'] / 30, p['cut'])
            self.assertGreater((p['startFrame'] + p['frames']) / 30, p['cut'])
            self.assertLessEqual((p['startFrame'] + p['frames']) / 30, 8)
        self.assertTrue(all(a['startFrame'] + a['frames'] <= b['startFrame'] for a, b in zip(plans, plans[1:])))
        self.assertEqual([], plan_transitions(clips, [], {key: False for key in TRANSITIONS}, 30))

    def test_real_transition_and_grid_composition(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            colors = ['red', 'green', 'blue', 'yellow']
            for n, color in enumerate(colors):
                path = str(Path(folder) / f'{n}.mp4')
                run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'color={color}:s=200x120:r=30:d=2', '-c:v', 'libx264', path])
                paths.append(path)
            clips = [Clip(n, paths[n], 0, 1, 0, n, None, False, layout_role='grid') for n in range(4)]
            clips += [Clip(n, paths[(n + 1) % 4], 0, 1, 1, n, None, False, layout_role='grid') for n in range(4)]
            options = dict(layoutModes=['grid'], **{name: name == 'slideTransitions' for name in TRANSITIONS})
            reader = FrameReader()
            try:
                frame = compose_scene(clips, .5, .5, 200, 120, options, reader)
            finally:
                reader.close()
            self.assertGreater(frame[20, 20, 2], 200)
            self.assertGreater(frame[90, 20, 0], 200)
            overlays, receipts = prepare_transitions(clips, [], options, Path(folder) / 'transitions', 200, 120, 30,
                                                      threading.Event(), lambda *_: None)
            self.assertEqual(len(overlays), 1)
            info = probe(overlays[0].path)
            self.assertAlmostEqual(float(info['format']['duration']), receipts[0]['frames'] / 30, delta=.04)
            self.assertTrue(overlays[0].transition_overlay)
            self.assertFalse(any(stream['codec_type'] == 'audio' for stream in info['streams']))
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(InterruptedError):
                prepare_transitions(clips, [], options, Path(folder) / 'cancelled', 200, 120, 30, cancelled, lambda *_: None)


if __name__ == '__main__':
    unittest.main()
