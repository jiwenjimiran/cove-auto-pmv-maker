import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "companion"))
from resolve_adapter import set_item_property


class TimelinePropertyTests(unittest.TestCase):
    def setUp(self):
        self.clip = SimpleNamespace(video_id=42, path="example.mp4", record_start=12.5, source_start=7.0)

    def test_retries_new_resolve_setter_after_timeline_item_initializes(self):
        class Item:
            attempts = 0
            def SetProperties(self, properties):
                self.attempts += 1
                return self.attempts == 3
            def GetProperties(self):
                return {"Scaling": 0, "RetimeAndScalingEnabled": True}

        item = Item()
        with patch("resolve_adapter.time.sleep"):
            set_item_property(item, "Scaling", 3.0, "pane scaling", self.clip, 2)
        self.assertEqual(item.attempts, 3)

    def test_project_fill_fallback_and_diagnostic_when_property_is_unavailable(self):
        class Item:
            def SetProperties(self, properties):
                return False
            def GetProperties(self):
                return {"Scaling": 0, "Pan": 0, "RetimeAndScalingEnabled": True}

        with patch("resolve_adapter.time.sleep"):
            set_item_property(Item(), "Scaling", 3.0, "pane scaling", self.clip, 2, project_fill=True)
            with self.assertRaisesRegex(RuntimeError, r"video 42 .*track 2.*Pan=100"):
                set_item_property(Item(), "Pan", 100, "pane position", self.clip, 2, project_fill=True)

    def test_older_resolve_uses_legacy_setter(self):
        class Item:
            def __init__(self):
                self.properties = {"Scaling": 0}
            def SetProperty(self, key, value):
                self.properties[key] = value
                return True
            def GetProperty(self):
                return self.properties

        item = Item()
        set_item_property(item, "Scaling", 3.0, "pane scaling", self.clip, 1)
        self.assertEqual(item.properties["Scaling"], 3.0)


if __name__ == "__main__":
    unittest.main()
