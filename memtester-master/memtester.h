/*
 * Very simple (yet, for some reason, very effective) memory tester.
 * Originally by Simon Kirby <sim@stormix.com> <sim@neato.org>
 * Version 2 by Charles Cazabon <charlesc-memtester@pyropus.ca>
 * Version 3 not publicly released.
 * Version 4 rewrite:
 * Copyright (C) 2004-2020 Charles Cazabon <charlesc-memtester@pyropus.ca>
 * Licensed under the terms of the GNU General Public License version 2 (only).
 * See the file COPYING for details.
 *
 * This file contains the declarations for external variables from the main file.
 * See other comments in that file.
 *
 */

#include <sys/types.h>
#include <stdint.h>
#include <stdio.h>

/* extern declarations. */

extern int use_phys;
extern off_t physaddrbase;

struct rampage_failure {
    size_t offset;
    char side;
    unsigned long expected;
    unsigned long observed;
};

extern uintptr_t rampage_test_base;
extern struct rampage_failure rampage_failures[2];
extern size_t rampage_failure_count;
extern size_t rampage_injection_offset;
extern FILE *rampage_result;
extern unsigned long *rampage_expected;
extern size_t rampage_expected_count;
extern void rampage_reset_failure(void);
