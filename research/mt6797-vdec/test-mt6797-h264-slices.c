/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <linux/errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mt6797-h264-controls.h"
typedef __u8 u8;
#include "multislice64-fixture.h"

static unsigned int ue_bits(unsigned int value)
{
	unsigned int bits = 1;
	while ((value + 1) >> bits)
		bits++;
	return 2 * bits - 1;
}

static void check_packet(const u8 *packet, size_t bytes, int predicted,
			const unsigned int *counts, unsigned int count)
{
	const u8 *first = packet;
	size_t offset = 0, first_bytes = 0;
	unsigned int mb = 0, checked = 0;
	struct v4l2_ctrl_h264_slice_params a = {
		.header_bit_size = predicted ? 26 : 28,
	};

	while (offset < bytes) {
		size_t end = offset;
		struct v4l2_ctrl_h264_slice_params b;
		while (end < bytes) {
			if (end + 4 <= bytes && !memcmp(packet + end, "\0\0\0\1", 4))
				break;
			end++;
		}
		assert(checked < count);
		if (!checked)
			first_bytes = end;
		b = a;
		b.first_mb_in_slice = mb;
		b.header_bit_size = (predicted ? 25 : 27) + ue_bits(mb);
		assert(!mt6797_h264_slice_headers_match(&a, first, first_bytes,
						      &b, packet + offset, end - offset));
		mb += counts[checked++];
		offset = end == bytes ? end : end + 4;
	}
	assert(checked == count && mb == 16);
}

int main(void)
{
	const unsigned int one[] = { 16 }, two[] = { 8, 8 }, four[] = { 4, 4, 4, 4 };
	const unsigned int uneven[] = { 1, 5, 3, 7 };
	unsigned int sixteen[16];
	for (unsigned int i = 0; i < 16; i++)
		sixteen[i] = 1;
#define PACKET(name, predicted, counts) \
	check_packet(name, sizeof(name), predicted, counts, sizeof(counts) / sizeof(counts[0]))
	PACKET(multislice_full_nal, 0, one);
	PACKET(multislice_full_p_nal, 1, one);
	PACKET(multislice_packet, 0, two);
	PACKET(multislice_two_p_packet, 1, two);
	PACKET(multislice_four_packet, 0, four);
	PACKET(multislice_four_p_packet, 1, four);
	PACKET(multislice_sixteen_packet, 0, sixteen);
	PACKET(multislice_sixteen_p_packet, 1, sixteen);
	PACKET(multislice_uneven_packet, 0, uneven);
	PACKET(multislice_uneven_p_packet, 1, uneven);
#undef PACKET
	struct v4l2_ctrl_h264_slice_params a = { .header_bit_size = 28 };
	struct v4l2_ctrl_h264_slice_params b = { .header_bit_size = 34, .first_mb_in_slice = 8 };
	assert(!mt6797_h264_slice_headers_match(&a, multislice_first_nal, sizeof(multislice_first_nal),
					      &b, multislice_last_nal, sizeof(multislice_last_nal)));
	u8 changed[sizeof(multislice_last_nal)];
	for (unsigned int bit = 0; bit < b.header_bit_size; bit++) {
		memcpy(changed, multislice_last_nal, sizeof(changed));
		changed[bit / 8] ^= 1U << (7 - bit % 8);
		assert(mt6797_h264_slice_headers_match(&a, multislice_first_nal,
			 sizeof(multislice_first_nal), &b, changed, sizeof(changed)) < 0);
	}
	memcpy(changed, multislice_last_nal, sizeof(changed));
	changed[sizeof(changed) - 2] ^= 1; /* Slice data is deliberately outside the header contract. */
	assert(!mt6797_h264_slice_headers_match(&a, multislice_first_nal, sizeof(multislice_first_nal),
					      &b, changed, sizeof(changed)));
	for (unsigned int bytes = 0; bytes < 5; bytes++)
		assert(mt6797_h264_slice_headers_match(&a, multislice_first_nal,
			 sizeof(multislice_first_nal), &b, multislice_last_nal, bytes) < 0);
	for (unsigned int bits = 0; bits < 34; bits++) {
		b.header_bit_size = bits;
		assert(mt6797_h264_slice_headers_match(&a, multislice_first_nal,
			 sizeof(multislice_first_nal), &b, multislice_last_nal,
			 sizeof(multislice_last_nal)) < 0);
	}
	b.header_bit_size = 16385;
	assert(mt6797_h264_slice_headers_match(&a, multislice_first_nal,
		 sizeof(multislice_first_nal), &b, multislice_last_nal,
		 sizeof(multislice_last_nal)) == -EINVAL);
	puts("PASS 54 original traced slice headers; header mutations, truncation and bounds rejected");
	return 0;
}
