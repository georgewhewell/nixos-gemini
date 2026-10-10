# SPDX-License-Identifier: GPL-2.0-only
"""Original progressive-frame reference marking for H.264 test fixtures.

Use the public dec_ref_pic_marking syntax: MMCO4 sets the allowed index
range, MMCO6 marks the current picture, and MMCO3 promotes the preceding
short-term picture. Index order deliberately differs from frame-number order.
"""


MODES = ('none', 'all', 'mixed', 'promote')


def long_term_indices(refs, mode):
    if mode == 'none':
        return {}
    if mode == 'promote':
        return {frame: refs - 1 - frame for frame in range(refs - 1)}
    frames = range(refs) if mode == 'all' else range(0, refs, 2)
    return {frame: refs - frame if frame else 0 for frame in frames}


def write_reference_marking(bits, frame, refs, mode):
    if not frame:
        bits.put(0)  # no_output_of_prior_pics_flag
        bits.put(int(mode in ('all', 'mixed')))  # long_term_reference_flag
        return
    indices = long_term_indices(refs, mode)
    operations = []
    if mode != 'none' and frame == 1:
        operations.append((4, refs))  # max_long_term_frame_idx_plus1
    if mode == 'promote':
        operations.append((3, 0, indices[frame - 1]))
    elif frame in indices:
        operations.append((6, indices[frame]))
    bits.put(int(bool(operations)))
    if operations:
        for operation in operations:
            for value in operation:
                bits.ue(value)
        bits.ue(0)
