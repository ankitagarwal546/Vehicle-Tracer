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
