#include "common.h"

int main(void) {
    print_string("03 forwarding\n");

    int a = 10;
    int b = a + 5;
    int c = b + 7;

    print_result(c == 22);
    program_exit();
    return 0;
}
