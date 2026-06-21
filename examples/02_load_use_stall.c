#include "common.h"

int main(void) {
    print_string("02 load-use stall\n");

    volatile int data[1] = {41};
    int loaded = data[0];
    int dependent = loaded + 1;

    print_result(dependent == 42);
    program_exit();
    return 0;
}
