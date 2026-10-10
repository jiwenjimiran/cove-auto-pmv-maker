import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
from face_analysis import FaceAnalyzer, cove_face_track


class CoveFaceDataTests(unittest.TestCase):
    samples = [
        {"performerId": 7, "time": 10.0, "center": 0.48, "width": 0.09, "score": 0.92},
        {"performerId": 7, "time": 11.0, "center": 0.50, "width": 0.09, "score": 0.94},
        {"performerId": 7, "time": 12.0, "center": 0.52, "width": 0.09, "score": 0.91},
    ]

    def test_linked_ai_faces_keyframes_select_portrait_without_image_match(self):
        track, performer, similarity = cove_face_track(self.samples, 10, 2, 0.59, 1920, 1080, [7], True)
        self.assertEqual(7, performer)
        self.assertIsNone(similarity)  # Cove-linked identity is not an SFace cosine score.
        self.assertTrue(all(0.25 < center < 0.75 for _time, center in track))
        analyzer = FaceAnalyzer.__new__(FaceAnalyzer)
        analyzer.recognizer = object()
        result = analyzer.analyze_match("missing.mp4", 10, 2, 0.59, True,
                                        allowed_performer_ids=[7], face_observations=self.samples,
                                        source_dimensions=(1920, 1080))
        self.assertEqual(7, result[1])

    def test_unlinked_or_sparse_data_cannot_claim_a_match(self):
        self.assertIsNone(cove_face_track(self.samples, 10, 2, 0.59, 1920, 1080, [8], True))
        sparse = [self.samples[0], {**self.samples[-1], "time": 17.0}]
        self.assertIsNone(cove_face_track(sparse, 10, 7, 0.59, 1920, 1080, [7], True))

    def test_fixed_crop_rejects_face_moving_outside_slice(self):
        moving = [
            {"performerId": 7, "time": 10 + index, "center": center, "width": 0.08, "score": 0.9}
            for index, center in enumerate((0.15, 0.5, 0.85))
        ]
        self.assertIsNone(cove_face_track(moving, 10, 2, 0.59, 1920, 1080, [7], False))


if __name__ == "__main__":
    unittest.main()
