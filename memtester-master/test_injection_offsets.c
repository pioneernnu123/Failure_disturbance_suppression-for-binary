/* Run with: cc -DTEST_NARROW_WRITES -o test_injection_offsets
 *               test_injection_offsets.c tests.c output.c
 * This checks the original seven injection types against one shared buffer.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

#include "types.h"
#include "memtester.h"
#include "tests.h"
#include "output.h"

int use_phys = 0;
off_t physaddrbase = 0;
extern uintptr_t inject_bufa_start;
extern size_t inject_pagesize;
extern ssize_t inject_page_rel;
extern int inject_kind;
extern int inject_once;
extern int compare_regions(ulv *bufa, ulv *bufb, size_t count);

int main(void)
{
    const size_t page_size = 4096;
    const size_t target = 5;
    unsigned char *buffer = calloc(8, page_size);
    int kind;

    if (!buffer) return 2;
    rampage_expected = malloc(page_size);
    if (!rampage_expected) { free(buffer); return 2; }
    rampage_expected_count = page_size / sizeof(ul);
    out_initialize();
    rampage_test_base = (uintptr_t)buffer;
    inject_bufa_start = rampage_test_base;
    inject_pagesize = page_size;
    inject_page_rel = target;

    for (kind = 1; kind <= 7; kind++) {
        ulv *a = (ulv *)(buffer + target * page_size);
        ulv *b = (ulv *)((unsigned char *)a + page_size / 2);
        size_t count = (page_size / 2) / sizeof(ul);
        int result;

        memset(buffer + target * page_size, 255, page_size);
        inject_kind = kind;
        inject_once = 1;
        rampage_injection_offset = SIZE_MAX;
        rampage_reset_failure();
        if (kind == 1) result = test_stuck_address(a, page_size / sizeof(ul));
        else if (kind == 2) result = test_xor_comparison(a, b, count);
        else if (kind == 3) result = test_solidbits_comparison(a, b, count);
        else if (kind == 4) result = test_checkerboard_comparison(a, b, count);
        else if (kind == 5) result = test_walkbits0_comparison(a, b, count);
        else if (kind == 6) result = test_or_comparison(a, b, count);
#ifdef TEST_NARROW_WRITES
        else result = test_8bit_wide_random(a, b, count);
#else
        else break;
#endif
        if (result != -1 || rampage_failure_count != 1 ||
            rampage_failures[0].offset != target * page_size ||
            rampage_injection_offset != target * page_size ||
            rampage_failures[0].side != 'A' ||
            (rampage_failures[0].expected ^ rampage_failures[0].observed) != 1) {
            fprintf(stderr, "kind %d failed: result=%d failure=%zu injection=%zu side=%c\n",
                    kind, result, rampage_failures[0].offset,
                    rampage_injection_offset, rampage_failures[0].side);
            free(buffer);
            free(rampage_expected);
            return 1;
        }
    }
    {
        ulv *a = (ulv *)(buffer + target * page_size);
        ulv *b = (ulv *)((unsigned char *)a + page_size / 2);
        unsigned char *a_bytes = (unsigned char *)a;
        unsigned char *b_bytes = (unsigned char *)b;

        memset(buffer + target * page_size, 255, page_size);
        rampage_reset_failure();
        inject_kind = 0;
        if (test_and_comparison(a, b, (page_size / 2) / sizeof(ul)) != 0)
            return 1;
        a_bytes[1] ^= 1;
        b_bytes[1] ^= 1;
        if (compare_regions(a, b, (page_size / 2) / sizeof(ul)) != -1 ||
            rampage_failure_count != 2 ||
            rampage_failures[0].side != 'A' || rampage_failures[1].side != 'B' ||
            rampage_failures[0].offset != target * page_size + 1 ||
            rampage_failures[1].offset != target * page_size + page_size / 2 + 1) {
            fprintf(stderr, "equal wrong words did not identify both exact byte offsets\n");
            free(buffer);
            free(rampage_expected);
            return 1;
        }
    }
    free(rampage_expected);
    free(buffer);
    puts("all seven injection types reported the target byte offset");
    return 0;
}
