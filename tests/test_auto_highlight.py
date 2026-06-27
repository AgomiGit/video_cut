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

    def test_vision_summary_majority_votes_normalized_subjects(self):
        summary = ah.summarize_vision_captions(
            [
                {"description": "A seal swims near glass.", "subjects": ["seal"], "setting": "aquarium"},
                {"description": "A sea lion surfaces in an exhibit.", "subjects": ["sea lion"], "setting": "aquarium"},
                {"description": "A turtle is partly visible in water.", "subjects": ["turtle"], "setting": "aquarium"},
            ]
        )

        self.assertIn("marine_mammal", summary["stable_subjects"])
        self.assertEqual(summary["subject_counts"]["marine_mammal"], 2)
        self.assertIn("aquatic_animal", summary["unstable_subjects"])

    def test_project_focus_downweights_one_off_subjects(self):
        candidates = [
            {
                "id": "seg_001",
                "transcript": "",
                "signals": {
                    "vision": {
                        "summary": {
                            "subjects": ["dolphin"],
                            "normalized_subjects": ["marine_mammal"],
                            "subject_counts": {"marine_mammal": 1},
                            "description": "A dolphin-like animal in an aquarium.",
                        }
                    }
                },
            },
            {
                "id": "seg_002",
                "transcript": "",
                "signals": {
                    "vision": {
                        "summary": {
                            "subjects": ["water"],
                            "normalized_subjects": [],
                            "subject_counts": {},
                            "description": "Water and rocks in an exhibit.",
                        }
                    }
                },
            },
        ]

        focus = ah.infer_project_focus(candidates)
        marine = next(item for item in focus["focus_terms"] if item["term"] == "marine_mammal")

        self.assertLess(marine["weight"], 6)
        self.assertEqual(marine["candidate_support"], 1)

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

    def test_select_segments_keeps_highlights_after_soft_target(self):
        scored = [
            {"id": "a", "start": 0, "end": 20, "duration_sec": 20, "final_score": 9, "is_standalone": True, "avoid_reason": "none"},
            {"id": "b", "start": 30, "end": 50, "duration_sec": 20, "final_score": 8.4, "is_standalone": True, "avoid_reason": "none"},
            {"id": "c", "start": 60, "end": 80, "duration_sec": 20, "final_score": 7.8, "is_standalone": True, "avoid_reason": "none"},
        ]

        selected = ah.select_segments(scored, target_duration=40)

        self.assertEqual([item["id"] for item in selected], ["a", "b", "c"])

    def test_select_segments_stops_low_quality_after_soft_target(self):
        scored = [
            {"id": "a", "start": 0, "end": 20, "duration_sec": 20, "final_score": 9, "is_standalone": True, "avoid_reason": "none"},
            {"id": "b", "start": 30, "end": 50, "duration_sec": 20, "final_score": 8.4, "is_standalone": True, "avoid_reason": "none"},
            {"id": "c", "start": 60, "end": 80, "duration_sec": 20, "final_score": 4.0, "is_standalone": True, "avoid_reason": "none"},
        ]

        selected = ah.select_segments(scored, target_duration=40)

        self.assertEqual([item["id"] for item in selected], ["a", "b"])

    def test_resolve_target_duration_defaults_to_source_retention(self):
        self.assertEqual(ah.resolve_target_duration(180, None), 54)
        self.assertEqual(ah.resolve_target_duration(600, None), 180)
        self.assertEqual(ah.resolve_target_duration(600, 90), 90)

    def test_max_segments_scales_with_dynamic_target(self):
        self.assertLess(ah.max_segments_for_target(54), ah.max_segments_for_target(180))
        self.assertLessEqual(ah.max_segments_for_target(600), ah.MAX_SELECTED_SEGMENTS)

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

    def test_select_segments_skips_visually_similar_scenes(self):
        def candidate(candidate_id, start, score, description):
            return {
                "id": candidate_id,
                "start": start,
                "end": start + 20,
                "duration_sec": 20,
                "final_score": score,
                "is_standalone": True,
                "avoid_reason": "none",
                "signals": {
                    "vision": {
                        "summary": {
                            "description": description,
                            "normalized_subjects": ["marine_mammal"],
                            "stable_subjects": ["marine_mammal"],
                            "settings": ["aquarium"],
                        }
                    }
                },
            }

        scored = [
            candidate("a", 0, 9, "A seal swims in a rocky aquarium enclosure."),
            candidate("b", 45, 8, "A sea lion swims in the same rocky aquarium enclosure."),
            candidate("c", 120, 7, "People react beside a bright outdoor sign and entrance."),
        ]

        selected = ah.select_segments(scored, target_duration=45)

        self.assertEqual([item["id"] for item in selected], ["a", "c"])

    def test_split_long_candidate_marks_event_windows(self):
        candidate = ah.Candidate("seg_000", 0, 70, " ".join(["普通對話"] * 4), {})
        segments = [
            {"start": 2, "end": 5, "text": "普通對話"},
            {"start": 30, "end": 34, "text": "哇 你看 牠游過來了！"},
            {"start": 55, "end": 58, "text": "普通對話"},
        ]

        splits = ah.split_long_candidate(candidate, segments, duration=70)

        self.assertTrue(any(item.signals.get("split_reason") == "transcript_event" for item in splits))
        self.assertTrue(any(item.start <= 30 <= item.end for item in splits))

    def test_expand_with_visual_subclips_anchors_on_visual_peak(self):
        candidates = [
            {
                "id": "seg_000",
                "start": 0,
                "end": 70,
                "duration_sec": 70,
                "transcript": "普通對話 哇 牠游過來了 普通對話",
                "signals": {},
            }
        ]
        segments = [
            {"start": 2, "end": 5, "text": "普通對話"},
            {"start": 31, "end": 34, "text": "哇 牠游過來了"},
            {"start": 56, "end": 58, "text": "普通對話"},
        ]
        visuals = {
            "seg_000": {
                "thumbnails": [
                    {"time": 8, "path": "thumbnails/seg_000/thumb_00.jpg"},
                    {"time": 32, "path": "thumbnails/seg_000/thumb_01.jpg"},
                    {"time": 60, "path": "thumbnails/seg_000/thumb_02.jpg"},
                ],
                "visual_quality": {"brightness": 0.5, "contrast": 0.2, "sharpness": 0.1},
                "visual_quality_samples": [
                    {"brightness": 0.5, "contrast": 0.1, "sharpness": 0.04},
                    {"brightness": 0.52, "contrast": 0.25, "sharpness": 0.14},
                    {"brightness": 0.5, "contrast": 0.1, "sharpness": 0.04},
                ],
                "ocr": {"text": "", "place_hits": []},
                "vision": {
                    "captions": [
                        {"time": 8, "path": "thumbnails/seg_000/thumb_00.jpg", "description": "Water and rocks.", "subjects": ["water"], "setting": "aquarium"},
                        {
                            "time": 32,
                            "path": "thumbnails/seg_000/thumb_01.jpg",
                            "description": "A seal swims close to aquarium glass.",
                            "subjects": ["seal"],
                            "setting": "aquarium",
                            "visual_hook": "close-up",
                            "actions": ["swimming"],
                        },
                        {"time": 60, "path": "thumbnails/seg_000/thumb_02.jpg", "description": "Empty water.", "subjects": ["water"], "setting": "aquarium"},
                    ],
                    "summary": {
                        "description": "A seal swims close to aquarium glass.",
                        "stable_subjects": ["marine_mammal"],
                        "normalized_subjects": ["marine_mammal"],
                        "subject_counts": {"marine_mammal": 2},
                    },
                },
            }
        }

        expanded = ah.expand_with_visual_subclips(candidates, visuals, segments, duration=70)
        subclips = [item for item in expanded if item["signals"].get("split_reason") == "visual_event"]

        self.assertTrue(subclips)
        self.assertTrue(any(item["start"] <= 32 <= item["end"] for item in subclips))
        self.assertEqual(subclips[0]["signals"]["candidate_type"], "subclip")
        self.assertEqual(subclips[0]["signals"]["thumbnails"][0]["path"], "thumbnails/seg_000/thumb_01.jpg")
        self.assertIn("marine_mammal", subclips[0]["signals"]["vision"]["summary"]["normalized_subjects"])

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
        self.assertEqual(plan["selected_segments"][0]["source_start"], 2.5)
        self.assertEqual(plan["selected_segments"][0]["source_end"], 32.5)
        self.assertEqual(plan["selected_segments"][0]["original_source_start"], 5)

    def test_build_review_report_explains_selected_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 30,
                    "selected_duration_sec": 25,
                    "selected_segments": [
                        {
                            "segment_id": "seg_001",
                            "role": "hook",
                            "source_start": 5,
                            "source_end": 30,
                            "duration_sec": 25,
                            "original_source_start": 7,
                            "original_source_end": 28,
                            "title": "海豹靠近",
                            "reason": "海豹貼近玻璃",
                            "final_score": 8.4,
                        }
                    ],
                },
            )
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {
                        "id": "seg_001",
                        "start": 7,
                        "end": 28,
                        "duration_sec": 21,
                        "title": "海豹靠近",
                        "summary": "海豹游到玻璃前",
                        "transcript": "哇 你看牠過來了",
                        "tags": ["反應", "主體重點"],
                        "scores": {"hook": 9, "focus": 7},
                        "heuristic_scores": {"focus_score": 7},
                        "final_score": 8.4,
                        "avoid_reason": "none",
                        "scoring_source": "heuristic",
                        "signals": {
                            "keywords": ["你看"],
                            "emotion_words": ["哇"],
                            "place_words": [],
                            "thumbnails": [
                                {"time": 9, "path": "thumbnails/seg_001/thumb_00.jpg"},
                                {"time": 18, "path": "thumbnails/seg_001/thumb_01.jpg"},
                            ],
                            "vision": {
                                "summary": {
                                    "description": "A seal swims close to the aquarium glass.",
                                    "stable_subjects": ["marine_mammal"],
                                }
                            },
                            "focus": {"score": 7, "matched_terms": [{"display": "海洋動物"}]},
                        },
                    },
                    {
                        "id": "seg_002",
                        "start": 40,
                        "end": 62,
                        "duration_sec": 22,
                        "title": "另一段互動",
                        "summary": "分數較低所以沒有入選",
                        "transcript": "你好 你好",
                        "tags": ["對話"],
                        "scores": {"hook": 5},
                        "final_score": 5.0,
                        "avoid_reason": "none",
                        "scoring_source": "heuristic",
                        "signals": {"focus": {"score": 2}},
                    }
                ],
            )
            ah.write_json(tmp_path / "project_focus.json", {"summary": "海洋動物"})

            report = ah.write_review_report(tmp_path)
            markdown = (tmp_path / "review_report.md").read_text(encoding="utf-8")

        self.assertEqual(report["version"], "review_report_v1")
        self.assertEqual(report["selected_segments"][0]["segment_id"], "seg_001")
        self.assertEqual(report["selected_segments"][0]["visual_subjects"], ["marine_mammal"])
        self.assertEqual(report["selected_segments"][0]["thumbnails"][0]["path"], "thumbnails/seg_001/thumb_00.jpg")
        self.assertEqual(report["contact_sheet"], "review_contact_sheet.jpg")
        self.assertEqual(report["near_miss_segments"][0]["segment_id"], "seg_002")
        self.assertIn("skip_reason", report["near_miss_segments"][0])
        self.assertIn("海豹靠近", markdown)
        self.assertIn("海洋動物", markdown)
        self.assertIn("thumbnails/seg_001/thumb_00.jpg", markdown)
        self.assertIn("Near Misses", markdown)

    def test_contact_sheet_inputs_uses_middle_thumbnail_when_available(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            thumb_dir = tmp_path / "thumbnails" / "seg_001"
            thumb_dir.mkdir(parents=True)
            first = thumb_dir / "thumb_00.jpg"
            middle = thumb_dir / "thumb_01.jpg"
            first.write_bytes(b"fake")
            middle.write_bytes(b"fake")
            report = {
                "selected_segments": [
                    {
                        "thumbnails": [
                            {"path": "thumbnails/seg_001/thumb_00.jpg"},
                            {"path": "thumbnails/seg_001/thumb_01.jpg"},
                        ]
                    }
                ]
            }

            paths = ah.contact_sheet_inputs(report, tmp_path)

        self.assertEqual(paths, [middle])

    def test_padding_clamps_and_avoids_neighbor_overlap(self):
        selected = [
            {"start": 0, "end": 24, "duration_sec": 24},
            {"start": 26, "end": 50, "duration_sec": 24},
        ]

        bounds = ah.padded_segment_bounds(selected, source_duration=60, padding=3)

        self.assertEqual(bounds[0], (0.0, 25.0))
        self.assertEqual(bounds[1], (25.0, 53.0))

    def test_plan_parser_defaults_to_clip_padding(self):
        parser = ah.build_parser()

        args = parser.parse_args(["plan", "work/sample_video"])

        self.assertEqual(args.clip_padding, 2.5)
        self.assertIsNone(args.target_duration)
        self.assertEqual(args.retention_ratio, 0.3)

    def test_report_parser_accepts_work_dir(self):
        parser = ah.build_parser()

        args = parser.parse_args(["report", "work/sample_video"])

        self.assertEqual(args.work_dir, "work/sample_video")
        self.assertEqual(args.func, ah.command_report)

    def test_render_defaults_compress_to_phone_resolution(self):
        parser = ah.build_parser()

        args = parser.parse_args(["render", "work/sample_video"])

        self.assertEqual(args.output_size, "1080x1920")
        self.assertEqual(args.crf, 28)
        self.assertEqual(args.preset, "medium")
        self.assertEqual(args.audio_bitrate, "128k")
        self.assertEqual(args.fade_duration, 0.25)

    def test_render_encoding_args_include_scale_and_crf(self):
        settings = ah.RenderSettings(output_size="720x1280", crf=30, preset="slow", audio_bitrate="96k")

        args = ah.render_encoding_args(settings)

        self.assertIn("scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1", args)
        self.assertIn("-crf", args)
        self.assertIn("30", args)
        self.assertIn("slow", args)
        self.assertIn("96k", args)

    def test_render_encoding_args_include_fade_when_enabled(self):
        settings = ah.RenderSettings(output_size="720x1280", crf=30, preset="slow", audio_bitrate="96k", fade_duration=0.25)

        args = ah.render_encoding_args(settings, clip_duration=10)

        self.assertIn("fade=t=in:st=0:d=0.25", args[1])
        self.assertIn("fade=t=out:st=9.75:d=0.25", args[1])
        self.assertIn("afade=t=in:st=0:d=0.25,afade=t=out:st=9.75:d=0.25", args)

    def test_video_bitrate_overrides_crf_for_render_encoding(self):
        settings = ah.RenderSettings(output_size="1080x1920", crf=28, preset="medium", audio_bitrate="128k", video_bitrate="3500k")

        args = ah.render_encoding_args(settings)

        self.assertIn("-b:v", args)
        self.assertIn("3500k", args)
        self.assertNotIn("-crf", args)

    def test_output_size_arg_rejects_invalid_size(self):
        with self.assertRaises(Exception):
            ah.output_size_arg("vertical")


if __name__ == "__main__":
    unittest.main()
