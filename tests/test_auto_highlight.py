import argparse
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import auto_highlight as ah


class AutoHighlightTests(unittest.TestCase):
    def run_args(self, **overrides):
        args = {
            "input": "input.mp4",
            "out": "work/video1",
            "whisper_model": "small",
            "force": False,
            "visuals": False,
            "thumbnail_count": 3,
            "ocr_languages": "chi_tra+eng",
            "output_size": "1080x1920",
            "target_duration": 60,
            "retention_ratio": ah.DEFAULT_TARGET_RETENTION_RATIO,
            "clip_padding": ah.DEFAULT_CLIP_PADDING,
            "selection_mode": "duration",
            "review_mode": "off",
            "review_top_candidates": 20,
            "crf": ah.DEFAULT_RENDER_CRF,
            "preset": ah.DEFAULT_RENDER_PRESET,
            "audio_bitrate": ah.DEFAULT_AUDIO_BITRATE,
            "video_bitrate": "",
            "fade_duration": ah.DEFAULT_FADE_DURATION,
            "quality_mode": "manual",
        }
        args.update(overrides)
        return argparse.Namespace(**args)

    def test_format_time_rounds_to_hh_mm_ss(self):
        self.assertEqual(ah.format_time(829.4), "00:13:49")
        self.assertEqual(ah.format_time(3661.2), "01:01:01")

    def test_init_work_dir_rejects_different_source_video(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            first = tmp_path / "first.mp4"
            second = tmp_path / "second.mp4"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            out_dir = tmp_path / "work"

            with mock.patch.object(ah, "video_duration", return_value=10.0):
                ah.init_work_dir(out_dir, first)
                with self.assertRaises(SystemExit):
                    ah.init_work_dir(out_dir, second)

    def test_init_work_dir_allows_same_legacy_source_without_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "source.mp4"
            source.write_bytes(b"source")
            out_dir = tmp_path / "work"
            out_dir.mkdir()
            ah.write_json(out_dir / "source.json", {"source_video": str(source.resolve()), "duration_sec": 10.0})

            with mock.patch.object(ah, "video_duration", return_value=10.0):
                ah.init_work_dir(out_dir, source)

            updated = ah.read_json(out_dir / "source.json")
            self.assertEqual(updated["fingerprint"]["size_bytes"], len(b"source"))

    def test_extract_audio_force_regenerates_existing_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "source.mp4"
            source.write_bytes(b"source")
            out_dir = tmp_path / "work"
            out_dir.mkdir()
            audio = out_dir / "audio.wav"
            audio.write_bytes(b"old")

            with mock.patch.object(ah, "require_tool"), mock.patch.object(ah, "run_command") as run_command:
                result = ah.extract_audio(source, out_dir, force=True)

            self.assertEqual(result, audio)
            self.assertFalse(audio.exists())
            self.assertEqual(run_command.call_count, 1)

    def test_invalidate_generated_artifacts_keeps_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(tmp_path / "source.json", {"source_video": "/tmp/source.mp4"})
            for name in ("audio.wav", "transcript.json", "review_contact_sheet.jpg"):
                (tmp_path / name).write_bytes(b"generated")
            for name in ("clips", "thumbnails", "output"):
                path = tmp_path / name
                path.mkdir()
                (path / "generated.txt").write_text("generated", encoding="utf-8")

            ah.invalidate_generated_artifacts(tmp_path)

            self.assertTrue((tmp_path / "source.json").exists())
            self.assertFalse((tmp_path / "audio.wav").exists())
            self.assertFalse((tmp_path / "review_contact_sheet.jpg").exists())
            self.assertFalse((tmp_path / "clips").exists())

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

    def test_bool_value_parses_string_false(self):
        self.assertFalse(ah.bool_value("false"))
        self.assertFalse(ah.bool_value("0"))
        self.assertTrue(ah.bool_value("yes"))

    def test_parse_first_json_finds_first_object_and_ignores_preamble(self):
        parsed = ah.parse_first_json(
            "thinking...\n"
            '{"summary":"usable summary","title":"title"}\n'
            "extra text"
        )

        self.assertEqual(parsed["summary"], "usable summary")
        self.assertEqual(parsed["title"], "title")

    def test_score_with_heuristic_populates_expected_fields(self):
        candidate = {
            "id": "seg_001",
            "start": 0,
            "end": 20,
            "duration_sec": 20,
            "transcript": "哇 你看",
            "signals": {
                "keywords": ["哇", "你看"],
                "emotion_words": ["哇"],
                "place_words": [],
                "speech_density": 0.5,
                "utterance_count": 2,
                "question_exclamation_count": 1,
            },
        }
        scored = ah.score_with_heuristic(candidate)

        self.assertEqual(scored["scoring_source"], "heuristic")
        self.assertIn("heuristic_scores", scored)
        self.assertIn("tags", scored)
        self.assertGreater(scored["final_score"], 0)

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

    def test_select_segments_does_not_pad_target_with_weak_segments(self):
        scored = [
            {"id": "a", "start": 0, "end": 24, "duration_sec": 24, "final_score": 3.8, "is_standalone": True, "avoid_reason": "none"},
            {"id": "b", "start": 80, "end": 104, "duration_sec": 24, "final_score": 2.3, "is_standalone": True, "avoid_reason": "none"},
            {"id": "c", "start": 150, "end": 174, "duration_sec": 24, "final_score": 1.2, "is_standalone": True, "avoid_reason": "none"},
            {"id": "d", "start": 190, "end": 214, "duration_sec": 24, "final_score": 0.9, "is_standalone": True, "avoid_reason": "none"},
        ]

        selected = ah.select_segments(scored, target_duration=90)

        self.assertEqual([item["id"] for item in selected], ["a", "b"])

    def test_select_segments_allows_weak_continuation_near_strong_segment(self):
        scored = [
            {"id": "a", "start": 0, "end": 24, "duration_sec": 24, "final_score": 3.8, "is_standalone": True, "avoid_reason": "none"},
            {"id": "b", "start": 80, "end": 104, "duration_sec": 24, "final_score": 2.3, "is_standalone": True, "avoid_reason": "none"},
            {"id": "c", "start": 104, "end": 128, "duration_sec": 24, "final_score": 1.2, "is_standalone": True, "avoid_reason": "none"},
            {"id": "d", "start": 190, "end": 214, "duration_sec": 24, "final_score": 0.9, "is_standalone": True, "avoid_reason": "none"},
        ]

        selected = ah.select_segments(scored, target_duration=90)

        self.assertEqual([item["id"] for item in selected], ["a", "b", "c"])

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

    def test_content_first_selection_prioritizes_visual_highlights(self):
        def candidate(candidate_id, start, final_score, visual_event, place, quality):
            return {
                "id": candidate_id,
                "start": start,
                "end": start + 20,
                "duration_sec": 20,
                "final_score": final_score,
                "is_standalone": True,
                "avoid_reason": "none",
                "heuristic_scores": {
                    "visual_event_score": visual_event,
                    "visual_interest_score": visual_event,
                    "place_score": place,
                    "focus_score": place,
                    "emotion_score": 0,
                    "keyword_score": 0,
                },
                "signals": {"visual_quality": quality},
            }

        scored = [
            candidate("talk", 0, 7.0, 0.0, 0.0, {"brightness": 0.3, "contrast": 0.05, "sharpness": 0.02}),
            candidate("view", 40, 5.0, 5.0, 6.0, {"brightness": 0.52, "contrast": 0.3, "sharpness": 0.12}),
            candidate("weak", 80, 2.0, 0.2, 0.0, {"brightness": 0.25, "contrast": 0.02, "sharpness": 0.01}),
        ]

        selected = ah.select_segments_content_first(scored, target_duration=120)

        self.assertEqual([item["id"] for item in selected], ["view"])

    def test_auto_render_profile_uses_1080p_for_low_quality_selected_clips(self):
        plan = {"selected_segments": [{"segment_id": "indoor"}, {"segment_id": "soft"}]}
        scored = [
            {
                "id": "indoor",
                "signals": {
                    "visual_quality": {"brightness": 0.28, "contrast": 0.2, "sharpness": 0.04},
                    "vision": {"summary": {"description": "An indoor museum hallway with dim light."}},
                },
            },
            {
                "id": "soft",
                "signals": {
                    "visual_quality": {"brightness": 0.36, "contrast": 0.18, "sharpness": 0.035},
                    "vision": {"summary": {"description": "A soft tunnel scene inside a building."}},
                },
            },
        ]

        profile = ah.choose_auto_render_profile(plan, scored)

        self.assertEqual(profile["profile"], "1080p")
        self.assertEqual(profile["output_size"], "1920x1080")

    def test_auto_render_profile_uses_4k_for_bright_outdoor_selected_clips(self):
        plan = {"selected_segments": [{"segment_id": "lake"}, {"segment_id": "market"}, {"segment_id": "mountain"}]}
        scored = [
            {
                "id": "lake",
                "signals": {
                    "visual_quality": {"brightness": 0.52, "contrast": 0.24, "sharpness": 0.08},
                    "vision": {"summary": {"description": "A bright outdoor lake landscape with forest and sky."}},
                },
            },
            {
                "id": "market",
                "signals": {
                    "visual_quality": {"brightness": 0.47, "contrast": 0.26, "sharpness": 0.075},
                    "vision": {"summary": {"description": "An outdoor market by a river under clear sky."}},
                },
            },
            {
                "id": "mountain",
                "signals": {
                    "visual_quality": {"brightness": 0.5, "contrast": 0.22, "sharpness": 0.07},
                    "vision": {"summary": {"description": "A mountain landscape and rural hill outside."}},
                },
            },
        ]

        profile = ah.choose_auto_render_profile(plan, scored)

        self.assertEqual(profile["profile"], "4k")
        self.assertEqual(profile["output_size"], "3840x2160")

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

    def test_visual_subclip_windows_ignore_quality_only_peaks(self):
        candidate = {
            "id": "seg_000",
            "start": 0,
            "end": 80,
            "duration_sec": 80,
        }
        visual = {
            "thumbnails": [
                {"time": 12, "path": "thumbnails/seg_000/thumb_00.jpg"},
                {"time": 38, "path": "thumbnails/seg_000/thumb_01.jpg"},
                {"time": 64, "path": "thumbnails/seg_000/thumb_02.jpg"},
            ],
            "visual_quality_samples": [
                {"brightness": 0.52, "contrast": 0.3, "sharpness": 0.2},
                {"brightness": 0.52, "contrast": 0.35, "sharpness": 0.2},
                {"brightness": 0.52, "contrast": 0.3, "sharpness": 0.2},
            ],
            "vision": {
                "captions": [
                    {"time": 12, "description": "Clear blue water and rocks.", "subjects": ["water"], "setting": "aquarium"},
                    {"time": 38, "description": "A clear empty tank.", "subjects": ["water"], "setting": "aquarium"},
                    {"time": 64, "description": "Bright water with glass reflections.", "subjects": ["water"], "setting": "aquarium"},
                ],
                "summary": {"description": "Water and rocks.", "normalized_subjects": [], "stable_subjects": []},
            },
        }

        windows = ah.visual_subclip_windows(candidate, visual)

        self.assertEqual(windows, [])

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
                        "signals": {
                            "focus": {"score": 2},
                            "thumbnails": [{"time": 51, "path": "thumbnails/seg_002/thumb_00.jpg"}],
                            "vision": {"summary": {"description": "A decent but lower ranked aquarium moment.", "stable_subjects": ["aquarium"]}},
                        },
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
        self.assertEqual(report["near_miss_segments"][0]["thumbnails"][0]["path"], "thumbnails/seg_002/thumb_00.jpg")
        self.assertIn("海豹靠近", markdown)
        self.assertIn("海洋動物", markdown)
        self.assertIn("thumbnails/seg_001/thumb_00.jpg", markdown)
        self.assertIn("thumbnails/seg_002/thumb_00.jpg", markdown)
        self.assertIn("Near Misses", markdown)

    def test_compute_plan_confidence_green_for_stable_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 60,
                    "selected_duration_sec": 60,
                    "selected_segments": [
                        {"segment_id": "seg_001", "role": "hook", "source_start": 0, "source_end": 20, "duration_sec": 20, "final_score": 9},
                        {"segment_id": "seg_002", "role": "highlight", "source_start": 30, "source_end": 50, "duration_sec": 20, "final_score": 8},
                        {"segment_id": "seg_003", "role": "ending", "source_start": 70, "source_end": 90, "duration_sec": 20, "final_score": 7},
                    ],
                },
            )
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {"id": "seg_001", "start": 0, "end": 20, "duration_sec": 20, "final_score": 9, "scores": {"hook": 9, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "哇 你看", "signals": {}},
                    {"id": "seg_002", "start": 30, "end": 50, "duration_sec": 20, "final_score": 8, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "你好", "signals": {}},
                    {"id": "seg_003", "start": 70, "end": 90, "duration_sec": 20, "final_score": 7, "scores": {"hook": 7, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "結尾", "signals": {}},
                    {"id": "seg_004", "start": 110, "end": 130, "duration_sec": 20, "final_score": 5, "scores": {"hook": 5, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "備選", "signals": {}},
                ],
            )

            confidence = ah.compute_plan_confidence(tmp_path)
            self.assertTrue((tmp_path / "plan_confidence.json").exists())

        self.assertEqual(confidence["status"], "green")
        self.assertEqual(confidence["recommended_action"], "render")

    def test_compute_plan_confidence_red_for_empty_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 60,
                    "selected_duration_sec": 0,
                    "selected_segments": [],
                },
            )
            ah.write_json(tmp_path / "scored_segments.json", [])

            confidence = ah.compute_plan_confidence(tmp_path)

        self.assertEqual(confidence["status"], "red")
        self.assertEqual(confidence["recommended_action"], "codex_rerank")
        self.assertIn("selected_segments_zero", [rule["rule"] for rule in confidence["red_rules"]])

    def test_compute_plan_confidence_yellow_for_short_uncertain_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 60,
                    "selected_duration_sec": 42,
                    "selected_segments": [
                        {"segment_id": "seg_001", "role": "hook", "source_start": 0, "source_end": 21, "duration_sec": 21, "final_score": 8.0},
                        {"segment_id": "seg_002", "role": "ending", "source_start": 40, "source_end": 61, "duration_sec": 21, "final_score": 7.9},
                    ],
                },
            )
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {"id": "seg_001", "start": 0, "end": 21, "duration_sec": 21, "final_score": 8.0, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "哇", "signals": {}},
                    {"id": "seg_002", "start": 40, "end": 61, "duration_sec": 21, "final_score": 7.9, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "你好", "signals": {}},
                    {"id": "seg_003", "start": 80, "end": 101, "duration_sec": 21, "final_score": 7.85, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "備選", "signals": {}},
                ],
            )

            confidence = ah.compute_plan_confidence(tmp_path)

        self.assertEqual(confidence["status"], "yellow")
        self.assertEqual(confidence["recommended_action"], "codex_review")

    def test_build_gpt_review_packet_includes_handoff_context(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 60,
                    "selected_duration_sec": 42,
                    "selected_segments": [
                        {"segment_id": "seg_001", "role": "hook", "source_start": 0, "source_end": 21, "duration_sec": 21, "final_score": 8.0},
                        {"segment_id": "seg_002", "role": "ending", "source_start": 40, "source_end": 61, "duration_sec": 21, "final_score": 7.9},
                    ],
                },
            )
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {"id": "seg_001", "start": 0, "end": 21, "duration_sec": 21, "title": "開場", "summary": "強開場", "final_score": 8.0, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "哇", "signals": {"thumbnails": [{"path": "thumbnails/seg_001/thumb_00.jpg"}]}},
                    {"id": "seg_002", "start": 40, "end": 61, "duration_sec": 21, "title": "結尾", "summary": "可當結尾", "final_score": 7.9, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "你好", "signals": {}},
                    {"id": "seg_003", "start": 80, "end": 101, "duration_sec": 21, "title": "備選", "summary": "接近入選", "final_score": 7.85, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "備選", "signals": {}},
                ],
            )
            confidence = ah.compute_plan_confidence(tmp_path)

            packet = ah.build_gpt_review_packet(tmp_path, confidence, top_candidate_limit=2)
            self.assertTrue((tmp_path / "gpt_review_packet.json").exists())

        self.assertEqual(packet["reviewer"], "codex_cli")
        self.assertEqual(packet["confidence"]["status"], "yellow")
        self.assertEqual(len(packet["top_candidates"]), 2)
        self.assertEqual(packet["selected_segments"][0]["candidate"]["segment_id"], "seg_001")
        self.assertIn("apply-review", packet["instructions"]["apply"])
        self.assertIn("Do not edit edit_plan.json directly", packet["instructions"]["do_not"])

    def test_render_review_summary_prints_yellow_handoff_steps(self):
        out_dir = Path("/tmp/work/video1")
        confidence = {
            "status": "yellow",
            "confidence_score": 0.64,
            "recommended_action": "codex_review",
            "triggered_rules": [{"rule": "selected_segments_under_3", "value": 2}],
        }
        packet = {
            "target_duration_sec": 60,
            "selected_duration_sec": 42,
            "selected_segments": [
                {
                    "role": "hook",
                    "candidate": {
                        "segment_id": "seg_001",
                        "time": "00:00:00-00:00:21",
                        "final_score": 8.0,
                        "title": "開場",
                    },
                }
            ],
            "near_miss_segments": [
                {
                    "segment_id": "seg_003",
                    "time": "00:01:20-00:01:41",
                    "final_score": 7.85,
                    "title": "備選",
                    "skip_reason": "duration budget",
                }
            ],
            "review_report": {"path": "review_report.md", "contact_sheet": "review_contact_sheet.jpg"},
        }

        summary = ah.render_review_summary(out_dir, confidence, packet)

        self.assertIn("Status: yellow", summary)
        self.assertIn("selected_segments_under_3: 2", summary)
        self.assertIn("1. seg_001 hook 00:00:00-00:00:21 score=8.0 開場", summary)
        self.assertIn("- seg_003 00:01:20-00:01:41 score=7.85 備選 (skip: duration budget)", summary)
        self.assertIn("codex_review_result.json", summary)
        self.assertIn("python3 auto_highlight.py apply-review /tmp/work/video1", summary)

    def test_command_review_summary_writes_packet_and_logs_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 60,
                    "selected_duration_sec": 42,
                    "selected_segments": [
                        {"segment_id": "seg_001", "role": "hook", "source_start": 0, "source_end": 21, "duration_sec": 21, "final_score": 8.0},
                        {"segment_id": "seg_002", "role": "ending", "source_start": 40, "source_end": 61, "duration_sec": 21, "final_score": 7.9},
                    ],
                },
            )
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {"id": "seg_001", "start": 0, "end": 21, "duration_sec": 21, "title": "開場", "summary": "強開場", "final_score": 8.0, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "哇", "signals": {}},
                    {"id": "seg_002", "start": 40, "end": 61, "duration_sec": 21, "title": "結尾", "summary": "可當結尾", "final_score": 7.9, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "你好", "signals": {}},
                    {"id": "seg_003", "start": 80, "end": 101, "duration_sec": 21, "title": "備選", "summary": "接近入選", "final_score": 7.85, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "備選", "signals": {}},
                ],
            )
            args = argparse.Namespace(work_dir=str(tmp_path), top_candidates=2, near_misses=1)

            with mock.patch.object(ah, "log") as log:
                ah.command_review_summary(args)

            summary = log.call_args.args[0]

            self.assertTrue((tmp_path / "plan_confidence.json").exists())
            self.assertTrue((tmp_path / "gpt_review_packet.json").exists())
            self.assertIn("Review Summary", summary)
            self.assertIn("Status: yellow", summary)
            self.assertIn("python3 auto_highlight.py apply-review", summary)

    def test_apply_codex_review_approve_keeps_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(tmp_path / "source.json", {"source_video": "/tmp/input.mp4", "duration_sec": 120})
            plan = {
                "version": "edit_plan_v1",
                "source_video": "/tmp/input.mp4",
                "output_video": "/tmp/highlight.mp4",
                "target_duration_sec": 60,
                "selected_duration_sec": 50,
                "selected_segments": [
                    {"segment_id": "seg_001", "role": "hook", "source_start": 0, "source_end": 25, "duration_sec": 25, "clip_padding_sec": 2.5},
                    {"segment_id": "seg_002", "role": "ending", "source_start": 40, "source_end": 65, "duration_sec": 25, "clip_padding_sec": 2.5},
                ],
            }
            scored = [
                {"id": "seg_001", "start": 2.5, "end": 22.5, "duration_sec": 20, "title": "開場", "summary": "保留", "final_score": 8, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "開場", "signals": {}},
                {"id": "seg_002", "start": 42.5, "end": 62.5, "duration_sec": 20, "title": "結尾", "summary": "保留", "final_score": 7, "scores": {"hook": 7, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "結尾", "signals": {}},
            ]
            ah.write_json(tmp_path / "edit_plan.json", plan)
            ah.write_json(tmp_path / "scored_segments.json", scored)
            confidence = ah.compute_plan_confidence(tmp_path)
            ah.build_gpt_review_packet(tmp_path, confidence)
            ah.write_json(tmp_path / "codex_review_result.json", {"version": "codex_review_result_v1", "decision": "approve", "reason": "current plan is good"})

            applied = ah.apply_codex_review(tmp_path)

            self.assertFalse(applied["changed"])
            self.assertEqual(ah.read_json(tmp_path / "edit_plan.json"), plan)
            self.assertFalse((tmp_path / "edit_plan.before_codex_review.json").exists())

    def test_apply_codex_review_replace_and_reorder_updates_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(tmp_path / "source.json", {"source_video": "/tmp/input.mp4", "duration_sec": 160})
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 60,
                    "selected_duration_sec": 50,
                    "selected_segments": [
                        {"segment_id": "seg_001", "role": "hook", "source_start": 0, "source_end": 25, "duration_sec": 25, "clip_padding_sec": 2.5},
                        {"segment_id": "seg_002", "role": "ending", "source_start": 40, "source_end": 65, "duration_sec": 25, "clip_padding_sec": 2.5},
                    ],
                },
            )
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {"id": "seg_001", "start": 2.5, "end": 22.5, "duration_sec": 20, "title": "開場", "summary": "保留", "final_score": 8, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "開場", "signals": {}},
                    {"id": "seg_002", "start": 42.5, "end": 62.5, "duration_sec": 20, "title": "弱結尾", "summary": "替換", "final_score": 7, "scores": {"hook": 7, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "弱", "signals": {}},
                    {"id": "seg_003", "start": 92.5, "end": 112.5, "duration_sec": 20, "title": "更好結尾", "summary": "更好", "final_score": 7.5, "scores": {"hook": 7, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "好", "signals": {}},
                ],
            )
            confidence = ah.compute_plan_confidence(tmp_path)
            ah.build_gpt_review_packet(tmp_path, confidence)
            ah.write_json(
                tmp_path / "codex_review_result.json",
                {
                    "version": "codex_review_result_v1",
                    "decision": "revise",
                    "reason": "replace weak ending and put the stronger ending first",
                    "operations": [
                        {"op": "replace", "remove": "seg_002", "add": "seg_003"},
                        {"op": "reorder", "segment_ids": ["seg_003", "seg_001"]},
                    ],
                },
            )

            applied = ah.apply_codex_review(tmp_path)
            updated = ah.read_json(tmp_path / "edit_plan.json")

            self.assertTrue(applied["changed"])
            self.assertTrue((tmp_path / "edit_plan.before_codex_review.json").exists())
            self.assertTrue((tmp_path / "edit_plan.gpt_reviewed.json").exists())
            self.assertEqual([segment["segment_id"] for segment in updated["selected_segments"]], ["seg_003", "seg_001"])
            self.assertEqual(updated["selected_segments"][0]["role"], "hook")
            self.assertEqual(updated["selected_segments"][0]["source_start"], 90.0)
            self.assertEqual(updated["selected_segments"][1]["source_start"], 0.0)
            self.assertTrue((tmp_path / "codex_review_apply_result.json").exists())

    def test_apply_codex_review_rejects_segment_outside_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ah.write_json(tmp_path / "source.json", {"source_video": "/tmp/input.mp4", "duration_sec": 120})
            ah.write_json(
                tmp_path / "edit_plan.json",
                {
                    "version": "edit_plan_v1",
                    "source_video": "/tmp/input.mp4",
                    "output_video": "/tmp/highlight.mp4",
                    "target_duration_sec": 60,
                    "selected_duration_sec": 25,
                    "selected_segments": [
                        {"segment_id": "seg_001", "role": "hook", "source_start": 0, "source_end": 25, "duration_sec": 25, "clip_padding_sec": 2.5},
                    ],
                },
            )
            ah.write_json(
                tmp_path / "scored_segments.json",
                [
                    {"id": "seg_001", "start": 2.5, "end": 22.5, "duration_sec": 20, "title": "開場", "summary": "保留", "final_score": 8, "scores": {"hook": 8, "clarity": 8}, "scoring_source": "heuristic", "is_standalone": True, "avoid_reason": "none", "transcript": "開場", "signals": {}},
                ],
            )
            confidence = ah.compute_plan_confidence(tmp_path)
            ah.build_gpt_review_packet(tmp_path, confidence)
            ah.write_json(
                tmp_path / "codex_review_result.json",
                {"version": "codex_review_result_v1", "decision": "rerank", "selected_segment_ids": ["seg_999"], "reason": "invalid"},
            )

            with self.assertRaises(SystemExit):
                ah.apply_codex_review(tmp_path)

    def test_command_run_review_auto_green_continues_to_render(self):
        args = self.run_args(review_mode="auto")
        confidence = {"status": "green", "confidence_score": 0.9, "recommended_action": "render"}

        with (
            mock.patch.object(ah, "command_prepare") as prepare,
            mock.patch.object(ah, "command_score") as score,
            mock.patch.object(ah, "command_plan") as plan,
            mock.patch.object(ah, "command_review_gate", return_value=confidence) as review_gate,
            mock.patch.object(ah, "command_render") as render,
        ):
            ah.command_run(args)

        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(score.call_count, 1)
        self.assertEqual(plan.call_count, 1)
        self.assertEqual(review_gate.call_count, 1)
        self.assertEqual(render.call_count, 1)

    def test_command_run_review_auto_yellow_stops_before_render_and_mentions_apply_review(self):
        args = self.run_args(review_mode="auto", out="work/yellow")
        confidence = {"status": "yellow", "confidence_score": 0.64, "recommended_action": "codex_review"}

        with (
            mock.patch.object(ah, "command_prepare"),
            mock.patch.object(ah, "command_score"),
            mock.patch.object(ah, "command_plan"),
            mock.patch.object(ah, "command_review_gate", return_value=confidence),
            mock.patch.object(ah, "command_render") as render,
        ):
            with self.assertRaises(SystemExit) as raised:
                ah.command_run(args)

        message = str(raised.exception)
        self.assertIn("gpt_review_packet.json", message)
        self.assertIn("codex_review_result.json", message)
        self.assertIn("apply-review work/yellow", message)
        self.assertNotIn("update edit_plan.json", message)
        self.assertEqual(render.call_count, 0)

    def test_command_run_review_always_stops_before_render_even_when_green(self):
        args = self.run_args(review_mode="always")
        confidence = {"status": "green", "confidence_score": 0.91, "recommended_action": "render"}

        with (
            mock.patch.object(ah, "command_prepare"),
            mock.patch.object(ah, "command_score"),
            mock.patch.object(ah, "command_plan"),
            mock.patch.object(ah, "command_review_gate", return_value=confidence),
            mock.patch.object(ah, "command_render") as render,
        ):
            with self.assertRaises(SystemExit) as raised:
                ah.command_run(args)

        self.assertIn("apply-review work/video1", str(raised.exception))
        self.assertEqual(render.call_count, 0)

    def test_command_run_review_off_skips_gate_and_renders(self):
        args = self.run_args(review_mode="off")

        with (
            mock.patch.object(ah, "command_prepare"),
            mock.patch.object(ah, "command_score"),
            mock.patch.object(ah, "command_plan"),
            mock.patch.object(ah, "command_review_gate") as review_gate,
            mock.patch.object(ah, "command_render") as render,
        ):
            ah.command_run(args)

        self.assertEqual(review_gate.call_count, 0)
        self.assertEqual(render.call_count, 1)

    def test_command_apply_review_passes_custom_review_result_path(self):
        args = argparse.Namespace(work_dir="/tmp/work", review_result="/tmp/custom_review.json")
        applied = {"decision": "revise", "changed": True}

        with (
            mock.patch.object(ah, "apply_codex_review", return_value=applied) as apply_review,
            mock.patch.object(ah, "log"),
        ):
            ah.command_apply_review(args)

        self.assertEqual(apply_review.call_args.args[0], Path("/tmp/work"))
        self.assertEqual(apply_review.call_args.args[1], Path("/tmp/custom_review.json"))

    def test_contact_sheet_inputs_uses_middle_thumbnail_for_selected_and_near_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            selected_dir = tmp_path / "thumbnails" / "seg_001"
            near_miss_dir = tmp_path / "thumbnails" / "seg_002"
            selected_dir.mkdir(parents=True)
            near_miss_dir.mkdir(parents=True)
            first = selected_dir / "thumb_00.jpg"
            middle = selected_dir / "thumb_01.jpg"
            near_miss = near_miss_dir / "thumb_00.jpg"
            first.write_bytes(b"fake")
            middle.write_bytes(b"fake")
            near_miss.write_bytes(b"fake")
            report = {
                "selected_segments": [
                    {
                        "thumbnails": [
                            {"path": "thumbnails/seg_001/thumb_00.jpg"},
                            {"path": "thumbnails/seg_001/thumb_01.jpg"},
                        ]
                    }
                ],
                "near_miss_segments": [{"thumbnails": [{"path": "thumbnails/seg_002/thumb_00.jpg"}]}],
            }

            paths = ah.contact_sheet_inputs(report, tmp_path)

        self.assertEqual(paths, [middle, near_miss])

    def test_contact_sheet_sections_keep_selected_and_near_miss_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            selected_dir = tmp_path / "thumbnails" / "seg_001"
            near_miss_dir = tmp_path / "thumbnails" / "seg_002"
            selected_dir.mkdir(parents=True)
            near_miss_dir.mkdir(parents=True)
            selected = selected_dir / "thumb_00.jpg"
            near_miss = near_miss_dir / "thumb_00.jpg"
            selected.write_bytes(b"fake")
            near_miss.write_bytes(b"fake")
            report = {
                "selected_segments": [{"thumbnails": [{"path": "thumbnails/seg_001/thumb_00.jpg"}]}],
                "near_miss_segments": [{"thumbnails": [{"path": "thumbnails/seg_002/thumb_00.jpg"}]}],
            }

            sections = ah.contact_sheet_sections(report, tmp_path)

        self.assertEqual(sections, [("selected", [selected]), ("near_miss", [near_miss])])

    def test_write_contact_sheet_label_image_creates_visible_label_strip(self):
        with tempfile.TemporaryDirectory() as directory:
            label_path = Path(directory) / "label.ppm"

            ah.write_contact_sheet_label_image("Selected", label_path, width=200)

            data = label_path.read_bytes()

        self.assertTrue(data.startswith(b"P6\n200 48\n255\n"))
        self.assertIn(b"\xf2\xf2\xf2", data)

    def test_write_contact_sheet_renders_section_tiles_before_stacking(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            for segment_id in ("seg_001", "seg_002", "seg_003"):
                thumb_dir = tmp_path / "thumbnails" / segment_id
                thumb_dir.mkdir(parents=True)
                (thumb_dir / "thumb_00.jpg").write_bytes(b"fake")
            report = {
                "contact_sheet": "review_contact_sheet.jpg",
                "selected_segments": [{"thumbnails": [{"path": "thumbnails/seg_001/thumb_00.jpg"}]}],
                "near_miss_segments": [
                    {"thumbnails": [{"path": "thumbnails/seg_002/thumb_00.jpg"}]},
                    {"thumbnails": [{"path": "thumbnails/seg_003/thumb_00.jpg"}]},
                ],
            }

            with (
                mock.patch.object(ah.shutil, "which", return_value="/usr/bin/ffmpeg"),
                mock.patch.object(ah, "write_contact_sheet_tile") as write_tile,
                mock.patch.object(ah, "stack_contact_sheet_tiles") as stack_tiles,
            ):
                output = ah.write_contact_sheet(tmp_path, report)

        self.assertEqual(output, tmp_path / "review_contact_sheet.jpg")
        self.assertEqual(write_tile.call_count, 2)
        self.assertEqual(write_tile.call_args_list[0].args[2], 2)
        self.assertEqual(write_tile.call_args_list[1].args[2], 2)
        self.assertEqual(write_tile.call_args_list[0].args[3], "Selected")
        self.assertEqual(write_tile.call_args_list[1].args[3], "Near Misses")
        self.assertEqual(stack_tiles.call_count, 1)

    def test_write_contact_sheet_tile_stacks_label_with_tile(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            image_path = tmp_path / "thumb.jpg"
            output_path = tmp_path / "section.jpg"
            image_path.write_bytes(b"fake")

            with (
                mock.patch.object(ah, "run_command") as run_command,
                mock.patch.object(ah, "stack_contact_sheet_tiles") as stack_tiles,
            ):
                ah.write_contact_sheet_tile([image_path], output_path, columns=1, label="Selected")

        self.assertEqual(run_command.call_count, 1)
        self.assertEqual(run_command.call_args.args[0][-1], str(tmp_path / "section_tile.jpg"))
        self.assertEqual(stack_tiles.call_count, 1)
        self.assertEqual(stack_tiles.call_args.args[0][0], tmp_path / "section_label.ppm")
        self.assertEqual(stack_tiles.call_args.args[0][1], tmp_path / "section_tile.jpg")
        self.assertEqual(stack_tiles.call_args.args[1], output_path)

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

    def test_profile_keywords_are_used_for_candidate_generation(self):
        transcript = {
            "duration_sec": 40,
            "segments": [
                {"start": 10, "end": 13, "text": "這個展覽入口很漂亮"},
                {"start": 25, "end": 27, "text": "普通對話"},
            ],
        }
        profile = ah.load_profile("travel")

        candidates = ah.generate_candidates_from_transcript(transcript, profile=profile)

        self.assertTrue(candidates)
        self.assertIn("入口", candidates[0]["signals"]["profile_keywords"])

    def test_profile_scoring_adds_auditable_boost(self):
        candidate = {
            "id": "seg_001",
            "final_score": 4.0,
            "tags": ["視覺地點"],
            "heuristic_scores": {"place_score": 6.0, "visual_event_score": 2.0, "focus_score": 3.0},
            "signals": {"profile_keywords": ["入口"], "visual_quality": {"brightness": 0.52, "contrast": 0.2, "sharpness": 0.08}},
        }

        scored = ah.apply_profile_scoring([candidate], ah.load_profile("travel"))

        self.assertGreater(scored[0]["final_score"], 4.0)
        self.assertEqual(scored[0]["profile_adjusted_from"], 4.0)
        self.assertEqual(scored[0]["profile_name"], "travel")

    def test_subtitle_cues_map_source_times_to_output_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            out_dir = Path(directory)
            ah.write_json(
                out_dir / "edit_plan.json",
                {
                    "selected_segments": [
                        {"segment_id": "seg_001", "source_start": 10, "source_end": 20},
                        {"segment_id": "seg_002", "source_start": 40, "source_end": 45},
                    ]
                },
            )
            ah.write_json(
                out_dir / "transcript.json",
                {
                    "segments": [
                        {"start": 12, "end": 14, "text": "第一段"},
                        {"start": 41, "end": 42, "text": "第二段"},
                    ]
                },
            )

            cues = ah.subtitle_cues_for_plan(out_dir)

        self.assertEqual(cues[0]["start"], 2.0)
        self.assertEqual(cues[0]["end"], 4.0)
        self.assertEqual(cues[1]["start"], 11.0)
        self.assertEqual(cues[1]["end"], 12.0)

    def test_doctor_warns_on_stale_html_report(self):
        with tempfile.TemporaryDirectory() as directory:
            out_dir = Path(directory)
            source_video = out_dir / "source.mp4"
            source_video.write_bytes(b"video")
            ah.write_json(out_dir / "source.json", {"source_video": str(source_video), "duration_sec": 20, "fingerprint": ah.source_fingerprint(source_video)})
            ah.write_json(out_dir / "transcript.json", {"segments": []})
            ah.write_json(out_dir / "candidates.json", [])
            ah.write_json(out_dir / "scored_segments.json", [])
            ah.write_json(out_dir / "edit_plan.json", {"selected_segments": []})
            report_path = out_dir / "review_report.json"
            html_path = out_dir / "review_report.html"
            report_path.write_text("{}", encoding="utf-8")
            html_path.write_text("<html></html>", encoding="utf-8")
            os.utime(html_path, (1000, 1000))
            os.utime(report_path, (2000, 2000))

            report = ah.doctor_check(out_dir)

        fingerprint_checks = [check for check in report["checks"] if check["name"] == "source_fingerprint"]
        self.assertTrue(fingerprint_checks)
        self.assertEqual(fingerprint_checks[0]["status"], "ok")
        self.assertEqual(fingerprint_checks[0]["detail"], "")
        stale_checks = [check for check in report["checks"] if check["name"] == "review_report.html"]
        self.assertTrue(stale_checks)
        self.assertEqual(stale_checks[0]["status"], "warn")

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

    def test_render_writes_output_inside_current_work_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out_dir = root / "current"
            stale_dir = root / "stale"
            out_dir.mkdir()
            source_video = root / "source.mp4"
            source_video.write_bytes(b"video")
            ah.write_json(
                out_dir / "edit_plan.json",
                {
                    "source_video": str(source_video),
                    "output_video": str(stale_dir / "output" / "highlight.mp4"),
                    "selected_segments": [{"source_start": 0, "source_end": 1}],
                },
            )
            settings = ah.RenderSettings(output_size="640x360", crf=35, preset="veryfast", audio_bitrate="96k")

            with mock.patch.object(ah, "require_tool"), mock.patch.object(ah, "run_command") as run_command:
                ah.render_edit_plan(out_dir, settings)

            concat_command = run_command.call_args_list[-1].args[0]

        self.assertEqual(Path(concat_command[-1]), out_dir / "output" / "highlight.mp4")

    def test_output_size_arg_rejects_invalid_size(self):
        with self.assertRaises(Exception):
            ah.output_size_arg("vertical")


if __name__ == "__main__":
    unittest.main()
