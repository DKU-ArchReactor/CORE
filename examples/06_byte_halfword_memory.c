#include "common.h"

int main(void) {
    print_string("06 byte halfword memory\n");

    volatile unsigned char bytes[2];
    volatile unsigned short halves[2];

    bytes[0] = 0x7F;
    bytes[1] = 0x80;
    halves[0] = 0x1234;
    halves[1] = 0xFEDC;

    int byte_ok = bytes[0] == 0x7F && bytes[1] == 0x80;
    int half_ok = halves[0] == 0x1234 && halves[1] == 0xFEDC;

    print_result(byte_ok && half_ok);
    program_exit();
    return 0;
}
