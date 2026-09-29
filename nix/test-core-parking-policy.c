// SPDX-License-Identifier: MIT
/* Host unit test for the pure policy step of core-parking.c. */
#define CORE_PARKING_NO_MAIN
#include "core-parking.c"

#include <assert.h>

static const struct policy P = {
	.period_ms = 50, .up_pct = 80, .up_samples = 2,
	.down_pct = 60, .down_samples = 4, .down_hold_ms = 1000,
	.rush_pct = 95, .min_k = 0, .boost_k = 3,
	.boost_hold_ms = 1500, .thermal_k = 3,
};

static int step(struct pstate *s, int load, int cap, int nr, int64_t t, int k,
		enum reason *why)
{
	struct sample x = { .load = load, .cap = cap, .nr = nr };

	return decide(&P, s, &x, t, k, 9, false, why);
}

int main(void)
{
	struct pstate s = { .low_since = -1 };
	enum reason why;
	int64_t t = 0;
	int k, i;

	/* Idle, 10 CPUs online: nothing before the hold, then one per hold. */
	k = 9;
	for (i = 0; i < 23; i++, t += 50)  /* 3 warm-up samples */
		assert(step(&s, 20, 10, 0, t, k, &why) == k && why == R_NONE);
	assert(step(&s, 20, 10, 0, t, k, &why) == 8 && why == R_DOWN);
	k = 8;
	t += 50;
	assert(step(&s, 20, 9, 0, t, k, &why) == 8);	/* hold restarted */
	for (; k > 0; ) {
		t += 1000;
		assert(step(&s, 20, k + 1, 0, t, k, &why) == k - 1 && why == R_DOWN);
		k--;
	}
	/* k == 0: CPU0 alone, cap 1: never below 0. */
	t += 2000;
	assert(step(&s, 5, 1, 0, t, 0, &why) == 0);

	/* Rush: one saturated sample with 4 runnable on 1 CPU -> +3 at once. */
	assert(step(&s, 100, 1, 4, t += 50, 0, &why) == 3 && why == R_RUSH);

	/* Up: mean of 2 samples above 80% per CPU -> +1, not before. */
	s = (struct pstate){ .low_since = -1 };
	assert(step(&s, 170, 2, 1, t += 50, 1, &why) == 1);	/* 1 sample */
	assert(step(&s, 170, 2, 1, t += 50, 1, &why) == 2 && why == R_UP);

	/* Hysteresis: 150% on 3 CPUs is neither up (>240) nor down (<120). */
	s = (struct pstate){ .low_since = -1 };
	for (i = 0; i < 100; i++)
		assert(step(&s, 150, 3, 1, t += 50, 2, &why) == 2);

	/* A spike resets the down hold. */
	s = (struct pstate){ .low_since = -1 };
	for (i = 0; i < 10; i++)
		assert(step(&s, 10, 3, 0, t += 50, 2, &why) == 2);
	for (i = 0; i < 4; i++)
		step(&s, 400, 3, 0, t += 50, 2, &why);
	for (i = 0; i < 20; i++)
		assert(step(&s, 10, 3, 0, t += 50, 2, &why) == 2);
	assert(s.low_since >= 0);

	/* Input boost floor, then decay after the hold. */
	s = (struct pstate){ .low_since = -1 };
	s.boost_until = t + 1500;
	assert(step(&s, 0, 1, 0, t += 50, 0, &why) == 3 && why == R_BOOST);
	for (i = 0; i < 20; i++)
		assert(step(&s, 0, 4, 0, t += 50, 3, &why) == 3);
	t += 1500;
	assert(step(&s, 0, 4, 0, t, 3, &why) == 2 && why == R_DOWN);

	/* Thermal cap: park one per step down to thermal_k, block unpark. */
	s = (struct pstate){ .low_since = -1, .hot = true };
	assert(step(&s, 900, 10, 12, t += 50, 9, &why) == 8 && why == R_THERMAL);
	assert(step(&s, 300, 4, 12, t += 50, 3, &why) == 3);

	/* Hold: everything. */
	s = (struct pstate){ .low_since = -1 };
	{
		struct sample x = { .load = 0, .cap = 1, .nr = 0 };

		assert(decide(&P, &s, &x, t, 0, 9, true, &why) == 9 && why == R_HOLD);
	}
	puts("core-parking-policy: pass");
	return 0;
}
