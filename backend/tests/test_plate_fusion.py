from app.cv.plate_fusion import PlateRead, align, fuse_plate_reads


def read(frame, text, conf=0.9, sharp=100.0, area=1000.0):
    return PlateRead(frame, frame / 5, text, [0.0 if c == "?" else conf for c in text], sharp, area, conf)


def test_recovers_plate_from_shifted_partial_reads():
    fused = fuse_plate_reads([read(12, "MH12DE??33"), read(18, "??12DE1433"), read(24, "MH12??14??")])
    assert fused.text == "MH12DE1433"


def test_aligns_reads_without_wildcard_padding():
    fused = fuse_plate_reads([read(1, "MH12DE14"), read(2, "12DE1433"), read(3, "DE1433", 0.85)])
    assert fused.text == "MH12DE1433"


def test_unobserved_slot_is_never_invented():
    fused = fuse_plate_reads([read(1, "MH12??1433"), read(2, "MH12??1433")])
    assert fused.text == "MH12??1433"
    assert fused.slots[4].candidates == []


def test_low_confidence_single_frame_is_rejected():
    reads = [read(1, "MH12DE1433", 0.92), PlateRead(2, 0.4, "MH12DE1433", [0.92] * 9 + [0.7], 100, 1000, 0.9)]
    assert fuse_plate_reads(reads).text == "MH12DE1433"
    single = PlateRead(1, 0.2, "MH12DE1433", [0.92] * 9 + [0.70], 100, 1000, 0.9)
    assert fuse_plate_reads([single]).text == "MH12DE143?"


def test_conflicting_slot_emits_unknown_with_runner_ups():
    fused = fuse_plate_reads([read(1, "MH12DE1833", 0.8), read(2, "MH12DE1B33", 0.8)])
    slot = fused.slots[7]
    assert slot.char == "?"
    assert {char for char, _ in slot.candidates} == {"8", "B"}
    assert "8" not in fused.text[7] and "B" not in fused.text[7]


def test_sharper_frames_outvote_blurry_frames():
    fused = fuse_plate_reads([
        read(1, "MH12DE1433", 0.9, sharp=400, area=4000),
        read(2, "MH12DE1433", 0.9, sharp=350, area=3500),
        read(3, "MH12DE1833", 0.9, sharp=10, area=300),
    ])
    assert fused.text == "MH12DE1433"


def test_noise_reads_are_filtered():
    fused = fuse_plate_reads([read(1, "MH12DE1433"), read(2, "X"), read(3, "ABCDEFGHIJKLMNOP")])
    assert fused.text == "MH12DE143 3".replace(" ", "")
    assert fused.reads_rejected == 2


def test_empty_input():
    fused = fuse_plate_reads([])
    assert fused.text == "" and fused.known_count == 0


def test_alignment_handles_offset():
    pairs = align("MH12DE1433", "DE14")
    assert pairs == [(4, 0), (5, 1), (6, 2), (7, 3)]


def test_slots_keep_source_frame_evidence():
    fused = fuse_plate_reads([read(12, "MH12DE1433"), read(18, "MH12DE1433")])
    assert {vote.frame_idx for vote in fused.slots[0].evidence} == {12, 18}
    assert fused.to_dict()["slots"][0]["evidence"][0]["char"] == "M"


def test_repeated_character_ocr_artefact_is_rejected():
    fused = fuse_plate_reads([read(1, "WWWWWWW"), read(2, "WWWWWW")])
    assert fused.text == "" and fused.reads_rejected == 2


def test_unrelated_read_cannot_extend_plate():
    fused = fuse_plate_reads([read(1, "MH12DE1433"), read(2, "MH12DE1433"), read(3, "QWXYZK7788")])
    assert fused.text == "MH12DE1433" and fused.reads_rejected == 1


def test_fused_plate_never_exceeds_slot_limit():
    fused = fuse_plate_reads([read(1, "ABCDEFGHJK"), read(2, "EFGHJKLMNP"), read(3, "HJKLMNPRST")])
    assert len(fused.slots) <= 10


def test_digits_only_withholds_letters_from_unsupported_scripts():
    fused = fuse_plate_reads([read(1, "1AB9876"), read(2, "10B9876")], digits_only=True)
    assert fused.text == "???9876"
    assert fused.slots[0].unknown_reason.startswith("withheld")


def test_derived_stack_is_not_counted_as_independent_frames():
    stacked = PlateRead(-1, 1.0, "MH12DE1433", [0.7] * 10, 100, 1000, 0.7, "stack", derived=True)
    single = PlateRead(1, 0.2, "MH12DE1433", [0.7] * 10, 100, 1000, 0.7)
    fused = fuse_plate_reads([single, stacked])
    assert fused.text == "?" * 10


def test_repeated_conflicting_frames_emit_unknown_with_reason():
    fused = fuse_plate_reads([read(1, "MH12DE1433"), read(2, "MH12DE1433"), read(3, "MH12DE1433"),
                              read(4, "MH12DE1439"), read(5, "MH12DE1439")])
    assert fused.text == "MH12DE143?"
    assert "disagree" in fused.slots[9].unknown_reason
    assert {c for c, _ in fused.slots[9].candidates} == {"3", "9"}


def test_character_only_in_processed_variants_stays_unknown():
    processed = PlateRead(1, 0.2, "MH12DE1433", [0.95] * 10, 100, 1000, 0.95,
                          char_source_supported=[True] * 9 + [False])
    fused = fuse_plate_reads([processed])
    assert fused.text == "MH12DE143?"
    assert "image processing" in fused.slots[9].unknown_reason


def test_other_frame_source_pixels_can_support_processed_character():
    processed = PlateRead(1, 0.2, "MH12DE1433", [0.95] * 10, 100, 1000, 0.95,
                          char_source_supported=[True] * 9 + [False])
    fused = fuse_plate_reads([processed, read(2, "MH12DE1433", 0.9)])
    assert fused.text == "MH12DE1433" and fused.slots[9].source_supported_frames == 1


def test_reads_with_conflicting_length_keep_only_agreed_positions():
    fused = fuse_plate_reads([read(1, "TN09WA4"), read(2, "TN09WA4"), read(3, "9WA43330"), read(4, "9WA43330")])
    assert len(fused.slots) <= 10
    assert any("plate length" in (slot.unknown_reason or "") for slot in fused.slots)
    assert "4333" not in fused.text


def test_read_that_saw_a_dropped_character_opens_its_slot():
    fused = fuse_plate_reads([read(1, "UP16R4569"), read(2, "UP16R4569"), read(3, "UP16RX4569"),
                              read(4, "UP16RX4569")])
    assert fused.text == "UP16RX4569"


def test_rare_edge_character_is_removed_as_ocr_artefact():
    reads = [read(i, "QX51TKU") for i in range(1, 11)] + [read(11, "HQX51TKU")]
    assert fuse_plate_reads(reads).text == "QX51TKU"


def test_single_frame_insertion_does_not_add_a_plate_position():
    reads = [read(i, "ZR61QKT") for i in range(1, 11)] + [read(11, "ZR61QPKT")]
    fused = fuse_plate_reads(reads)
    assert fused.text == "ZR61QKT" and len(fused.slots) == 7
