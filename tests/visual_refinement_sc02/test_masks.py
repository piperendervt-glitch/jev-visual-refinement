import unittest

import numpy as np

from visual_refinement_sc02.masks import normalize_masks, pixel_edge_bbox


class MaskGeometryTest(unittest.TestCase):
    def test_original_pixel_edges_and_overlap_are_preserved(self):
        raw = np.zeros((2, 4, 6), dtype=np.uint8)
        raw[0, 1:3, 1:4] = 1
        raw[1, 2:4, 3:6] = 1
        normalized = normalize_masks(raw, 6, 4)
        self.assertEqual(pixel_edge_bbox(normalized[0]), (1, 1, 4, 3))
        self.assertEqual(pixel_edge_bbox(normalized[1]), (3, 2, 6, 4))
        self.assertEqual(int(normalized[:, 2, 3].sum()), 2)

    def test_size_mismatch_is_not_silently_rescaled(self):
        with self.assertRaisesRegex(ValueError, "mask_original_shape_mismatch"):
            normalize_masks(np.ones((1, 640, 640)), 1280, 720)

    def test_zero_masks_are_valid(self):
        masks = normalize_masks(np.empty((0, 3, 5), dtype=np.uint8), 5, 3)
        self.assertEqual(masks.shape, (0, 3, 5))
