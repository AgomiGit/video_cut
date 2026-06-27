import tempfile
import unittest
from pathlib import Path

import auto_highlight as ah


class AutoHighlightTests(unittest.TestCase):
    def test_format_time_rounds_to_hh_mm_ss(self):
        self.assertEqual(ah.format_time(829.4), "00:13:49")
        self.assertEqual(ah.format_time(3661.2), "01:01:01")

    def test_generate_candidates_merges_keyword_windows(self):
        transcript = {
            "duration_sec": 80,
            "segments": [
                {"start": 10, "end": 14, "text": "哇 你看這邊"},
                {"start": 18, "end": 22, "text": "這個夜市排隊好多人"},
                {"start": 55, "end": 59, "text": "普通的一段對話"},
            ],
        }

        candidates = ah.generate_candidates_from_transcript(transcript)

        self.assertTrue(candidates)
        self.assertLessEqual(candidates[0]["start"], 10)
        self.assertGreaterEqual(candidates[0]["end"], 22)
        self.assertIn("哇", candidates[0]["signals"]["keywords"])

    def test_generate_candidates_falls_back_to_speech_clusters(self):
        transcript = {
            "duration_sec": 63,
            "segments": [
                {"start": 3.57, "end": 8.46, "text": "嗨老婆嗨"},
                {"start": 8.72, "end": 11.02, "text": "恭喜你入境嘍"},
                {"start": 45.59, "end": 47.13, "text": "你不要說句話"},
                {"start": 49.17, "end": 50.71, "text": "你在幹嘛"},
            ],
        }

        candidates = ah.generate_candidates_from_transcript(transcript)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["signals"]["fallback_reason"], "speech_cluster")
        self.assertIn("恭喜你入境", candidates[0]["transcript"])

    def test_generate_candidates_adds_subclips_for_long_segments(self):
        transcript = {
            "duration_sec": 70,
            "segments": [
                {"start": 2, "end": 6, "text": "你看牠在這裡"},
                {"start": 14, "end": 18, "text": "牠游過來了"},
                {"start": 28, "end": 32, "text": "哇好近"},
                {"start": 42, "end": 46, "text": "牠又回來"},
                {"start": 54, "end": 58, "text": "你好"},
            ],
        }

        candidates = ah.generate_candidates_from_transcript(transcript)
        subclips = [item for item in candidates if item["signals"].get("candidate_type") == "subclip"]

        self.assertGreaterEqual(len(subclips), 2)
        self.assertTrue(all(12 <= item["duration_sec"] <= 28 for item in subclips))

    def test_merge_transcript_strings_removes_sliding_window_overlap(self):
        left = "你看牠潛到水裡 哇好大隻喔 好大隻喔"
        right = "哇好大隻喔 好大隻喔 他跟你打招呼耶"

        merged = ah.merge_transcript_strings(left, right)

        self.assertEqual(merged, "你看牠潛到水裡 哇好大隻喔 好大隻喔 他跟你打招呼耶")

    def test_sample_timestamps_avoids_edges(self):
        self.assertEqual(ah.sample_timestamps(10, 40, 3), [12.0, 25.0, 38.0])

    def test_frame_quality_from_gray_reports_brightness_and_edges(self):
        raw = bytes([0, 255, 0, 255])

        quality = ah.frame_quality_from_gray(raw, width=2, height=2)

        self.assertEqual(quality["brightness"], 0.5)
        self.assertGreater(quality["contrast"], 0.4)
        self.assertGreater(quality["sharpness"], 0.4)

    def test_attach_visual_signals_enriches_candidate(self):
        candidates = [{"id": "seg_001", "signals": {"keywords": ["哇"]}}]
        visuals = {
            "seg_001": {
                "visual_quality": {"brightness": 0.5, "contrast": 0.2, "sharpness": 0.1},
                "visual_quality_penalty": 0.0,
                "ocr": {"text": "入口", "place_hits": ["入口"]},
                "vision": {"summary": {"description": "An animal close-up in an aquarium.", "subjects": ["animal"], "settings": ["aquarium"]}},
                "thumbnails": [{"path": "thumbnails/seg_001/thumb_00.jpg", "time": 12.0}],
            }
        }

        enriched = ah.attach_visual_signals(candidates, visuals)

        self.assertEqual(enriched[0]["signals"]["ocr"]["place_hits"], ["入口"])
        self.assertIn("aquarium", enriched[0]["signals"]["vision"]["summary"]["settings"])
        self.assertEqual(enriched[0]["signals"]["thumbnails"][0]["time"], 12.0)

    def test_parse_vision_response_accepts_json_and_plain_text(self):
        parsed = ah.parse_vision_response(
            '{"description":"A large animal near glass.","subjects":["animal"],"setting":"aquarium","actions":["swimming"],"visual_hook":"close-up","quality_note":"clear"}'
        )
        fallback = ah.parse_vision_response("A dark indoor aquarium scene.")

        self.assertEqual(parsed["setting"], "aquarium")
        self.assertEqual(parsed["subjects"], ["animal"])
        self.assertEqual(fallback["description"], "A dark indoor aquarium scene.")

    def test_vision_response_missing_image_detection(self):
        parsed = {"description": "No image was provided for analysis.", "setting": "", "visual_hook": "", "quality_note": ""}

        self.assertTrue(ah.vision_response_missing_image(parsed))

    def test_vision_summary_influences_tags_and_scores(self):
        candidate = {
            "id": "seg_001",
            "duration_sec": 20,
            "transcript": "普通對話",
            "signals": {
                "keywords": [],
                "emotion_words": [],
                "place_words": [],
                "speech_density": 0.2,
                "utterance_count": 2,
                "question_exclamation_count": 0,
                "vision": {
                    "summary": {
                        "description": "A close-up animal scene inside an aquarium.",
                        "subjects": ["animal"],
                        "settings": ["aquarium"],
                        "visual_hooks": ["close-up"],
                    }
                },
            },
        }

        self.assertIn("視覺亮點", ah.infer_tags(candidate))
        scores = ah.heuristic_scores(candidate)
        self.assertGreater(scores["place_score"], 0)
        self.assertGreater(scores["visual_interest_score"], 0)

    def test_project_focus_infers_main_subject_from_visuals(self):
        candidates = [
            {
                "id": "seg_001",
                "transcript": "你看牠在水裡",
                "signals": {
                    "vision": {
                        "summary": {
                            "description": "A seal swimming inside an aquarium exhibit.",
                            "subjects": ["seal", "person"],
                            "settings": ["aquarium"],
                        }
                    }
                },
            },
            {
                "id": "seg_002",
                "transcript": "普通對話",
                "signals": {
                    "vision": {
                        "summary": {
                            "description": "A seal near rocks in a marine park.",
                            "subjects": ["seal"],
                            "settings": ["marine park"],
                        }
                    }
                },
            },
        ]

        focus = ah.infer_project_focus(candidates)
        terms = [item["term"] for item in focus["focus_terms"]]

        self.assertIn("marine_mammal", terms)
        self.assertIn("aquarium", terms)

    def test_focus_signal_increases_score_and_tags_candidate(self):
        base_candidate = {
            "id": "seg_001",
            "duration_sec": 20,
            "transcript": "普通對話",
            "signals": {
                "keywords": [],
                "emotion_words": [],
                "place_words": [],
                "speech_density": 0.2,
                "utterance_count": 2,
                "question_exclamation_count": 0,
                "vision": {
                    "summary": {
                        "description": "A seal close to the glass inside an aquarium.",
                        "subjects": ["seal"],
                        "settings": ["aquarium"],
                    }
                },
            },
        }
        project_focus = {
            "summary": "海洋動物、水族館場景",
            "focus_terms": [
                {"term": "marine_mammal", "display": "海洋動物", "weight": 10, "aliases": ["seal", "海豹", "海獅", "海象"]},
                {"term": "aquarium", "display": "水族館場景", "weight": 6, "aliases": ["aquarium", "水族館"]},
            ],
        }

        focused = ah.attach_focus_signals([base_candidate], project_focus)[0]
        scores = ah.heuristic_scores(focused)

        self.assertGreater(scores["focus_score"], 0)
        self.assertGreater(scores["total_heuristic_score"], ah.heuristic_scores(base_candidate)["total_heuristic_score"])
        self.assertIn("主體重點", ah.infer_tags(focused))

    def test_select_segments_rejects_overlapping_and_nearby_segments(self):
        scored = [
            {"id": "a", "start": 10, "end": 40, "duration_sec": 30, "final_score": 9, "is_standalone": True, "avoid_reason": "none"},
            {"id": "b", "start": 20, "end": 45, "duration_sec": 25, "final_score": 8, "is_standalone": True, "avoid_reason": "none"},
            {"id": "c", "start": 90, "end": 115, "duration_sec": 25, "final_score": 7, "is_standalone": True, "avoid_reason": "none"},
        ]

        selected = ah.select_segments(scored, target_duration=60)

        self.assertEqual([item["id"] for item in selected], ["a", "c"])

    def test_select_segments_allows_adjacent_short_highlights(self):
        scored = [
            {"id": "a", "start": 0, "end": 20, "duration_sec": 20, "final_score": 9, "is_standalone": True, "avoid_reason": "none"},
            {"id": "b", "start": 24, "end": 44, "duration_sec": 20, "final_score": 8, "is_standalone": True, "avoid_reason": "none"},
            {"id": "c", "start": 48, "end": 68, "duration_sec": 20, "final_score": 7, "is_standalone": True, "avoid_reason": "none"},
        ]

        selected = ah.select_segments(scored, target_duration=60)

        self.assertEqual([item["id"] for item in selected], ["a", "b", "c"])

    def test_select_segments_prefers_subclips_when_available(self):
        scored = [
            {"id": "long", "start": 0, "end": 60, "duration_sec": 60, "final_score": 10, "is_standalone": True, "avoid_reason": "none", "signals": {}},
            {
                "id": "a",
                "start": 0,
                "end": 20,
                "duration_sec": 20,
                "final_score": 8,
                "is_standalone": True,
                "avoid_reason": "none",
                "signals": {"candidate_type": "subclip"},
            },
            {
                "id": "b",
                "start": 24,
                "end": 44,
                "duration_sec": 20,
                "final_score": 7,
                "is_standalone": True,
                "avoid_reason": "none",
                "signals": {"candidate_type": "subclip"},
            },
            {
                "id": "c",
                "start": 48,
                "end": 68,
                "duration_sec": 20,
                "final_score": 6,
                "is_standalone": True,
                "avoid_reason": "none",
                "signals": {"candidate_type": "subclip"},
            },
        ]

        selected = ah.select_segments(scored, target_duration=60)

        self.assertEqual([item["id"] for item in selected], ["a", "b", "c"])

    def test_build_edit_plan_uses_scored_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(tmp_path / "source.json", {"source_video": "/tmp/input.mp4", "duration_sec": 120})
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {
                        "id": "seg_001",
                        "start": 5,
                        "end": 30,
                        "duration_sec": 25,
                        "title": "開場",
                        "summary": "有明確反應",
                        "final_score": 8,
                        "is_standalone": True,
                        "avoid_reason": "none",
                    }
                ],
            )

            plan = ah.build_edit_plan(tmp_path, target_duration=30)

        self.assertEqual(plan["version"], "edit_plan_v1")
        self.assertEqual(plan["selected_segments"][0]["segment_id"], "seg_001")
        self.assertEqual(plan["selected_segments"][0]["role"], "hook")


if __name__ == "__main__":
    unittest.main()
